from datetime import date
from pathlib import Path

from trend.config import Category, load_config
from trend.history import History, previous_week, week_of, week_range
from trend.llm import FallbackSummarizer, _Pick, _CategoryPicks, _SelectionOut, _validate_selection, clean_text
from trend.models import Entry, Repo, Summary
from trend.notify import build_digest
from trend.render import Report, render_index, render_report
from trend.scrape import parse_trending

FIXTURE = Path(__file__).parent / "fixtures" / "trending_weekly.html"
ROOT = Path(__file__).parent.parent


def cat(cid: str) -> Category:
    return Category(id=cid, title=cid.upper(), description="", languages=[], topics=[])


# --- scrape ---

def test_parse_trending_fixture():
    repos = parse_trending(FIXTURE.read_text(encoding="utf-8"))
    assert len(repos) == 15
    first = repos[0]
    assert first.full_name == "sherlock-project/sherlock"
    assert first.language == "Python"
    assert first.stars > 100_000
    assert first.stars_this_week and first.stars_this_week > 0
    assert all(r.full_name.count("/") == 1 for r in repos)


def test_parse_trending_empty_page_raises():
    import pytest
    with pytest.raises(ValueError):
        parse_trending("<html><body>nothing</body></html>")


# --- weeks & history ---

def test_monday_run_labels_previous_week():
    assert week_of(date(2026, 11, 16)) == "2026-W46"   # Monday
    assert week_of(date(2026, 11, 14)) == "2026-W46"   # Saturday, same week
    assert week_range("2026-W46") == (date(2026, 11, 9), date(2026, 11, 15))


def test_previous_week_crosses_year():
    assert previous_week("2026-W01") == "2025-W52"


def test_streak_and_featured_before(tmp_path):
    h = History(tmp_path / "h.json")
    h.record(["a/a"], "2026-W44")
    h.record(["a/a", "b/b"], "2026-W45")
    assert h.streak("a/a", "2026-W46") == 3
    assert h.streak("b/b", "2026-W46") == 2
    assert h.streak("c/c", "2026-W46") == 1
    assert h.featured_before("b/b", "2026-W46")
    h.record(["c/c"], "2026-W46")
    assert not h.featured_before("c/c", "2026-W46")   # re-running the same week isn't "before"
    h.save()
    assert History(tmp_path / "h.json").repos == h.repos


# --- llm output hygiene ---

def test_clean_text_strips_links_html_and_newlines():
    dirty = 'Great <script>x</script> tool [click](http://evil.example) see https://x.y/z\nnext | `code`'
    assert clean_text(dirty) == "Great x tool click see next code"


def test_validate_selection_enforces_known_caps_and_uniqueness():
    pools = {"fe": [Repo("x/1"), Repo("x/2"), Repo("x/3")], "be": [Repo("y/1")]}
    extras = [Repo("z/1"), Repo("z/2")]
    out = _SelectionOut(
        categories=[
            _CategoryPicks(category_id="fe", picks=[_Pick(full_name=n, reason="r") for n in ["x/1", "x/2", "x/3", "made/up"]]),
            _CategoryPicks(category_id="be", picks=[_Pick(full_name="x/1", reason="dup"), _Pick(full_name="y/1", reason="ok")]),
            _CategoryPicks(category_id="nope", picks=[_Pick(full_name="z/1", reason="r")]),
        ],
        extras=[_Pick(full_name="y/1", reason="dup"), _Pick(full_name="z/2", reason="ok")],
    )
    chosen, ex = _validate_selection(out, [cat("fe"), cat("be")], pools, extras, category_max=2, extras_max=5)
    assert [n for n, _ in chosen["fe"]] == ["x/1", "x/2"]
    assert [n for n, _ in chosen["be"]] == ["y/1"]
    assert [n for n, _ in ex] == ["z/2"]


def test_fallback_select_never_repeats_a_repo():
    pools = {"fe": [Repo("a/a"), Repo("b/b")], "be": [Repo("a/a"), Repo("c/c")]}
    chosen, extras = FallbackSummarizer().select([cat("fe"), cat("be")], pools, [Repo("c/c"), Repo("d/d")], 5, 5)
    assert [n for n, _ in chosen["fe"]] == ["a/a", "b/b"]
    assert [n for n, _ in chosen["be"]] == ["c/c"]
    assert [n for n, _ in extras] == ["d/d"]


# --- rendering ---

def _entry(name, **kw):
    repo = Repo(name, description="d", language="Go", stars=1234, stars_this_week=56, topics=["cli"])
    return Entry(repo=repo, summary=Summary("무엇", "왜", "누구"), **kw)


def _report():
    return Report(
        week="2026-W46", start=date(2026, 11, 9), end=date(2026, 11, 15), generated_at="2026-11-16 09:00 KST",
        overview="총평", top=[_entry("a/a", rank=1), _entry("b/b", rank=2, streak=3)],
        categories=[(cat("fe"), [_entry("c/c")]), (cat("be"), [])],
        extras=[_entry("d/d", pick_reason="실용적")], warnings=["경고"],
    )


def test_render_report_sections():
    md = render_report(_report())
    assert md.startswith("# 🔥 GitHub 주간 트렌드 — 2026-W46")
    assert "> ⚠️ 경고" in md
    assert "### 1. [a/a](https://github.com/a/a)" in md
    assert "`Go` · ⭐ 1,234 (이번 주 +56) · `cli`" in md
    assert "- **무엇:** 무엇" in md
    assert "🔁 3주 연속" in md and "- 무엇\n" in md          # repeat => short form
    assert "## FE" in md and "## BE" in md and "_이번 주에는 소개할 만한 레포가 없었습니다._" in md
    assert "> 💡 선정 이유: 실용적" in md
    assert md.index("## FE") < md.index("## ➕ 추가 추천")


def test_render_index_lists_newest_first(tmp_path):
    for w in ["2026-W45", "2026-W46"]:
        (tmp_path / f"{w}.md").write_text("x")
    md = render_index(tmp_path)
    assert "최신 리포트: [2026-W46]" in md
    assert md.index("- [2026-W46]") < md.index("- [2026-W45]")


# --- slack ---

def test_slack_digest_escapes_and_links():
    latest = {
        "week": "2026-W46", "report_path": "weekly/2026-W46.md", "overview": "a <b> & c", "warnings": [],
        "top": [{"rank": 1, "full_name": "a/a", "url": "https://github.com/a/a", "what": "x"}],
        "categories": [{"title": "FE", "first": None}],
    }
    payload = build_digest(latest, "https://github.com/me/repo")
    text = str(payload)
    assert "a &lt;b&gt; &amp; c" in text
    assert "<https://github.com/a/a|a/a>" in text
    assert "<https://github.com/me/repo/blob/main/weekly/2026-W46.md|전체 리포트 보기>" in text


def test_repo_config_loads():
    cfg = load_config(ROOT / "config.yaml")
    assert [c.id for c in cfg.categories] == ["backend", "infra", "frontend", "design"]
    assert cfg.top_n == 10 and cfg.category_max == 5
