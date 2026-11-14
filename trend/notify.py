"""Slack Incoming Webhook notifications.

Usage:
  python -m trend.notify   # post the digest from data/latest.json
(Failure alerts are sent with curl directly from the workflow.)
Does nothing (exit 0) when SLACK_WEBHOOK_URL is unset.
"""

import argparse
import json
import os
import sys
from pathlib import Path

import httpx

SECTION_LIMIT = 2900  # Slack caps section text at 3000 chars


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _link(url: str, label: str) -> str:
    return f"<{url}|{_esc(label)}>"


def _section(text: str) -> dict:
    return {"type": "section", "text": {"type": "mrkdwn", "text": text[:SECTION_LIMIT]}}


def _repo_base() -> str:
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    return f"{server}/{os.environ.get('GITHUB_REPOSITORY', '')}"


def build_digest(latest: dict, repo_base: str) -> dict:
    report_url = f"{repo_base}/blob/main/{latest['report_path']}"
    blocks: list[dict] = [
        {"type": "header", "text": {"type": "plain_text", "text": f"🔥 GitHub 주간 트렌드 {latest['week']}"}},
    ]
    if latest.get("warnings"):
        blocks.append(_section("\n".join(f"⚠️ {_esc(w)}" for w in latest["warnings"])))
    blocks.append(_section(f"*📝 이번 주 총평*\n{_esc(latest['overview'])}"))
    top = "\n".join(f"{t['rank']}. {_link(t['url'], t['full_name'])} — {_esc(t['what'][:90])}" for t in latest["top"])
    blocks.append(_section(f"*🏆 종합 Top {len(latest['top'])}*\n{top}"))
    for c in latest["categories"]:
        lines = [f"• {_link(i['url'], i['full_name'])} — {_esc(i['what'][:80])}" for i in c["items"]] or ["_이번 주 없음_"]
        blocks.append(_section(f"*{_esc(c['title'])}*\n" + "\n".join(lines)))
    blocks.append(_section(f"👉 {_link(report_url, '전체 리포트 보기')}"))
    return {"text": f"GitHub 주간 트렌드 {latest['week']}", "blocks": blocks}


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
    payload = build_digest(json.loads(args.latest.read_text(encoding="utf-8")), _repo_base())
    post(webhook, payload)
    print("Slack notification sent")
    return 0


if __name__ == "__main__":
    sys.exit(main())
