"""Slack Incoming Webhook notifications.

Usage:
  python -m trend.notify   # post this week's report (weekly/<week>.md) to Slack as-is
(Failure alerts are sent with curl directly from the workflow.)
Does nothing (exit 0) when SLACK_WEBHOOK_URL is unset.

The Markdown file is sent verbatim via Slack's `markdown` block, which renders standard
Markdown. Slack caps markdown blocks at 12,000 chars per message, so longer reports are
split at heading boundaries into several consecutive messages.
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

import httpx

MESSAGE_LIMIT = 11_500  # Slack: 12,000 chars of markdown-block text per payload (leave headroom)
_SECTION_SPLIT = re.compile(r"(?m)^(?=## )")   # prefer breaking between ## sections
_ITEM_SPLIT = re.compile(r"(?m)^(?=### )")     # fall back to ### items inside an oversized section


def _repo_base() -> str:
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    return f"{server}/{os.environ.get('GITHUB_REPOSITORY', '')}"


def _units(md: str, limit: int) -> list[str]:
    out: list[str] = []
    for section in (u for u in _SECTION_SPLIT.split(md) if u.strip()):
        for unit in [section] if len(section) <= limit else _ITEM_SPLIT.split(section):
            while len(unit) > limit:  # still oversized: hard-cut at a line break
                cut = unit.rfind("\n", 0, limit) + 1 or limit
                out.append(unit[:cut])
                unit = unit[cut:]
            if unit.strip():
                out.append(unit)
    return out


def split_markdown(md: str, limit: int = MESSAGE_LIMIT) -> list[str]:
    """Pack heading-delimited units into chunks of at most `limit` chars."""
    units = _units(md, limit)
    chunks: list[str] = []
    for unit in units:
        if chunks and len(chunks[-1]) + len(unit) <= limit:
            chunks[-1] += unit
        else:
            chunks.append(unit)
    return [c.strip() for c in chunks]


def build_messages(markdown: str, week: str, report_url: str) -> list[dict]:
    footer = f"\n\n👉 [GitHub에서 보기]({report_url})"
    chunks = split_markdown(markdown, MESSAGE_LIMIT - len(footer))
    chunks[-1] += footer
    n = len(chunks)
    return [
        {
            "text": f"GitHub 주간 트렌드 {week}" + (f" ({i}/{n})" if n > 1 else ""),
            "blocks": [{"type": "markdown", "text": chunk}],
        }
        for i, chunk in enumerate(chunks, 1)
    ]


def post(webhook: str, payload: dict) -> None:
    resp = httpx.post(webhook, json=payload, timeout=30)
    resp.raise_for_status()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--latest", type=Path, default=Path("data/latest.json"))
    args = ap.parse_args()

    webhook = os.environ.get("SLACK_WEBHOOK_URL")
    if not webhook:
        print("SLACK_WEBHOOK_URL not set; skipping Slack notification")
        return 0
    latest = json.loads(args.latest.read_text(encoding="utf-8"))
    report_path = latest["report_path"]
    markdown = (args.latest.parent.parent / report_path).read_text(encoding="utf-8")
    messages = build_messages(markdown, latest["week"], f"{_repo_base()}/blob/main/{report_path}")
    for payload in messages:  # sequential so the parts arrive in order
        post(webhook, payload)
    print(f"Slack notification sent ({len(messages)} message(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
