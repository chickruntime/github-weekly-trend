"""Week labels and the record of which repos were featured in which weeks."""

import json
from datetime import date, timedelta
from pathlib import Path


def week_of(run_date: date) -> str:
    """Label for the week a report covers. Runs on Monday cover the week that just ended."""
    y, w, _ = (run_date - timedelta(days=1)).isocalendar()
    return f"{y}-W{w:02d}"


def week_range(week: str) -> tuple[date, date]:
    y, w = week.split("-W")
    monday = date.fromisocalendar(int(y), int(w), 1)
    return monday, monday + timedelta(days=6)


def previous_week(week: str) -> str:
    monday, _ = week_range(week)
    y, w, _ = (monday - timedelta(days=7)).isocalendar()
    return f"{y}-W{w:02d}"


class History:
    def __init__(self, path: Path):
        self.path = path
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        self.repos: dict[str, list[str]] = data.get("repos", {})

    def featured_before(self, full_name: str, week: str) -> bool:
        return any(w != week for w in self.repos.get(full_name, []))

    def streak(self, full_name: str, week: str) -> int:
        """Consecutive weeks featured, counting `week` itself."""
        weeks = set(self.repos.get(full_name, []))
        count, cur = 1, previous_week(week)
        while cur in weeks:
            count += 1
            cur = previous_week(cur)
        return count

    def record(self, full_names: list[str], week: str) -> None:
        for name in full_names:
            weeks = self.repos.setdefault(name, [])
            if week not in weeks:
                weeks.append(week)
                weeks.sort()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"repos": dict(sorted(self.repos.items()))}
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
