"""Markdown rendering for the weekly report and the README index."""

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from trend.config import Category
from trend.models import Entry


@dataclass
class Report:
    week: str
    start: date
    end: date
    generated_at: str
    overview: str
    top: list[Entry]
    categories: list[tuple[Category, list[Entry]]]
    extras: list[Entry]
    warnings: list[str] = field(default_factory=list)


def _meta(entry: Entry) -> str:
    r = entry.repo
    parts = [f"`{r.language}`"] if r.language else []
    stars = f"⭐ {r.stars:,}"
    if r.stars_this_week is not None:
        stars += f" (이번 주 +{r.stars_this_week:,})"
    parts.append(stars)
    if r.topics:
        parts.append(" ".join(f"`{t}`" for t in r.topics[:5]))
    return " · ".join(parts)


def _entry(entry: Entry, heading: str) -> str:
    badge = f" 🔁 {entry.streak}주 연속" if entry.streak > 1 else ""
    lines = [f"### {heading}[{entry.repo.full_name}]({entry.repo.url}){badge}", "", _meta(entry), ""]
    if entry.pick_reason:
        lines += [f"> 💡 선정 이유: {entry.pick_reason}", ""]
    s = entry.summary
    if entry.streak > 1 or not (s.why or s.who):
        lines.append(f"- {s.what}")
    else:
        lines += [f"- **무엇:** {s.what}", f"- **왜 주목:** {s.why}", f"- **누구에게:** {s.who}"]
    return "\n".join(lines) + "\n"


def render_report(rep: Report) -> str:
    out = [
        f"# 🔥 GitHub 주간 트렌드 — {rep.week}",
        "",
        f"> 기간: {rep.start.isoformat()} ~ {rep.end.isoformat()} · 생성: {rep.generated_at}",
        "",
    ]
    out += [f"> ⚠️ {w}" for w in rep.warnings]
    if rep.warnings:
        out.append("")
    out += ["## 📝 이번 주 총평", "", rep.overview, "", "## 🏆 종합 Top " + str(len(rep.top)), ""]
    out += [_entry(e, f"{e.rank}. ") for e in rep.top]
    for cat, entries in rep.categories:
        out += [f"## {cat.title}", ""]
        out += [_entry(e, "") for e in entries] if entries else ["_이번 주에는 소개할 만한 레포가 없었습니다._", ""]
    if rep.extras:
        out += ["## ➕ 추가 추천", ""]
        out += [_entry(e, "") for e in rep.extras]
    return "\n".join(out).rstrip() + "\n"


def render_index(weekly_dir: Path) -> str:
    weeks = sorted((p.stem for p in weekly_dir.glob("*-W*.md")), reverse=True)
    lines = [
        "# 📈 GitHub Weekly Trend",
        "",
        "매주 월요일 09:00 (KST)에 GitHub 주간 트렌딩 Top 10, 분야별(백엔드·인프라·프론트엔드·디자인/그래픽) 추천, "
        "추가 추천 레포를 한국어 요약과 함께 자동으로 정리합니다.",
        "",
        "설정·동작 방식: [docs/SETUP.md](docs/SETUP.md)",
        "",
    ]
    if weeks:
        lines += [f"**👉 최신 리포트: [{weeks[0]}](weekly/{weeks[0]}.md)**", "", "## 🗂️ 아카이브", ""]
        lines += [f"- [{w}](weekly/{w}.md)" for w in weeks]
    else:
        lines.append("_아직 생성된 리포트가 없습니다._")
    return "\n".join(lines) + "\n"

