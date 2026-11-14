"""Build this week's report.

  python -m trend.main                      # full run (uses ANTHROPIC_API_KEY if set)
  python -m trend.main --no-llm --out /tmp/x   # dry run: descriptions instead of summaries
"""

import argparse
import json
import logging
import os
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import anthropic
import httpx

from trend import github_api, scrape, wif
from trend.config import Config, load_config
from trend.history import History, week_of, week_range
from trend.llm import ClaudeSummarizer, FallbackSummarizer
from trend.models import Entry, Repo
from trend.render import Report, render_index, render_report

log = logging.getLogger("trend")
KST = timezone(timedelta(hours=9))


def _dedupe(repos: list[Repo], exclude: set[str]) -> list[Repo]:
    seen, out = set(exclude), []
    for r in repos:
        if r.full_name not in seen:
            seen.add(r.full_name)
            out.append(r)
    return out


def collect_overall(client: httpx.Client, today: date, top_n: int) -> tuple[list[Repo], list[Repo], list[str]]:
    """Returns (top, extras_pool, warnings)."""
    warnings = []
    new_repos = []
    try:
        new_repos = github_api.search_new_repos(client, today)
    except httpx.HTTPError as e:
        log.warning("search for new repos failed: %s", e)
    try:
        trending = scrape.fetch_trending(client)
    except (httpx.HTTPError, ValueError) as e:
        log.warning("trending scrape failed, falling back to search: %s", e)
        if not new_repos:
            raise RuntimeError("both Trending and Search API failed") from e
        warnings.append("GitHub Trending 페이지 수집에 실패해 Search API(최근 7일 생성 + 스타순) 결과로 대체했습니다.")
        trending = new_repos
    top = trending[:top_n]
    return top, _dedupe(trending[top_n:] + new_repos, {r.full_name for r in top}), warnings


def collect_category_pools(client: httpx.Client, cfg: Config, today: date) -> dict[str, list[Repo]]:
    pools: dict[str, list[Repo]] = {}
    for cat in cfg.categories:
        found: list[Repo] = []
        for lang in cat.languages:
            try:
                found += scrape.fetch_trending(client, lang)[:10]
            except (httpx.HTTPError, ValueError) as e:
                log.warning("trending/%s failed: %s", lang, e)
        for topic in cat.topics:
            try:
                found += github_api.search_topic(client, topic, today, cfg.topic_created_within_days)
            except httpx.HTTPError as e:
                log.warning("topic search %s failed: %s", topic, e)
            time.sleep(2.5)  # Search API: 30 req/min authenticated
        pools[cat.id] = _dedupe(found, set())
    return pools


def run(cfg: Config, out: Path, today: date, claude: anthropic.Anthropic | None) -> Path:
    week = week_of(today)
    start, end = week_range(week)
    history = History(out / "data" / "history.json")
    summarizer = ClaudeSummarizer(cfg.model, claude) if claude else FallbackSummarizer()
    warnings: list[str] = []
    if not claude:
        warnings.append("LLM 요약 없이 생성되었습니다 (레포 설명으로 대체).")

    with github_api.make_client() as client:
        top, extras_pool, w = collect_overall(client, today, cfg.top_n)
        warnings += w
        pools = collect_category_pools(client, cfg, today)

        # Curated sections only show repos not featured in earlier weeks, and never repeat Top N.
        taken = {r.full_name for r in top}
        fresh = lambda rs: [r for r in rs if r.full_name not in taken and not history.featured_before(r.full_name, week)]
        pools = {cid: fresh(rs) for cid, rs in pools.items()}
        extras_pool = fresh(extras_pool)

        cat_picks, extra_picks = summarizer.select(cfg.categories, pools, extras_pool, cfg.category_max, cfg.extras_max)

        by_name = {r.full_name: r for rs in [top, extras_pool, *pools.values()] for r in rs}
        picked_names = [n for picks in cat_picks.values() for n, _ in picks] + [n for n, _ in extra_picks]
        to_describe = top + [by_name[n] for n in picked_names]
        for repo in to_describe:
            try:
                github_api.enrich(client, repo)
            except httpx.HTTPError as e:
                log.warning("enrich %s failed: %s", repo.full_name, e)

    summaries = summarizer.summarize_many(to_describe)

    def entry(name: str, rank: int | None = None, reason: str | None = None) -> Entry:
        return Entry(repo=by_name[name], summary=summaries[name], rank=rank,
                     streak=history.streak(name, week), pick_reason=reason)

    top_entries = [entry(r.full_name, rank=i) for i, r in enumerate(top, 1)]
    cat_entries = [(c, [entry(n) for n, _ in cat_picks.get(c.id, [])]) for c in cfg.categories]
    extra_entries = [entry(n, reason=why or None) for n, why in extra_picks]

    overview = summarizer.overview(
        [f"{e.repo.full_name}: {e.summary.what}" for e in top_entries]
        + [f"[{c.id}] {e.repo.full_name}: {e.summary.what}" for c, es in cat_entries for e in es]
    )
    if isinstance(summarizer, ClaudeSummarizer) and summarizer.failures * 2 > summarizer.calls:
        raise SystemExit(f"{summarizer.failures}/{summarizer.calls} Claude calls failed; aborting before any commit")
    if isinstance(summarizer, ClaudeSummarizer) and summarizer.failures:
        warnings.append(f"Claude 호출 {summarizer.failures}건이 실패해 일부 내용을 레포 설명으로 대체했습니다.")

    report = Report(
        week=week, start=start, end=end,
        generated_at=datetime.now(KST).strftime("%Y-%m-%d %H:%M KST"),
        overview=overview, top=top_entries, categories=cat_entries, extras=extra_entries, warnings=warnings,
    )
    report_path = out / "weekly" / f"{week}.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_report(report), encoding="utf-8")
    (out / "README.md").write_text(render_index(out / "weekly"), encoding="utf-8")

    history.record([e.repo.full_name for e in top_entries + extra_entries]
                   + [e.repo.full_name for _, es in cat_entries for e in es], week)
    history.save()
    _write_latest(out / "data" / "latest.json", report)
    return report_path


def _write_latest(path: Path, rep: Report) -> None:
    """Compact digest consumed by trend.notify (Slack)."""
    item = lambda e: {"full_name": e.repo.full_name, "url": e.repo.url, "what": e.summary.what}
    payload = {
        "week": rep.week,
        "report_path": f"weekly/{rep.week}.md",
        "overview": rep.overview,
        "warnings": rep.warnings,
        "top": [{"rank": e.rank, **item(e)} for e in rep.top],
        "categories": [{"title": c.title, "first": item(es[0]) if es else None} for c, es in rep.categories],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def preflight_auth(claude: anthropic.Anthropic) -> None:
    """Fail the run (no commit) on credential misconfiguration instead of silently
    producing a summary-less report that would also pollute history."""
    try:
        claude.models.list(limit=1)
    except anthropic.AnthropicError as e:
        raise SystemExit(f"Claude authentication failed; aborting before any commit: {e}") from e


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", type=Path, default=Path("config.yaml"))
    ap.add_argument("--out", type=Path, default=Path("."))
    ap.add_argument("--date", type=date.fromisoformat, default=None, help="run date (KST), for testing")
    ap.add_argument("--no-llm", action="store_true")
    args = ap.parse_args()

    # An empty ANTHROPIC_API_KEY (unset Actions secret) would shadow WIF credentials in the SDK.
    if not os.environ.get("ANTHROPIC_API_KEY"):
        os.environ.pop("ANTHROPIC_API_KEY", None)
    use_wif = wif.wif_configured()
    use_llm = not args.no_llm and (bool(os.environ.get("ANTHROPIC_API_KEY")) or use_wif)
    if not args.no_llm and not use_llm:
        log.warning("no Anthropic credentials (API key or WIF); running without LLM")
    claude = None
    if use_llm:
        if os.environ.get("ANTHROPIC_API_KEY"):
            claude = anthropic.Anthropic()
        else:
            log.info("using Workload Identity Federation")
            claude = anthropic.Anthropic(credentials=wif.make_credentials())
        preflight_auth(claude)
    today = args.date or datetime.now(KST).date()
    path = run(load_config(args.config), args.out, today, claude)
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
