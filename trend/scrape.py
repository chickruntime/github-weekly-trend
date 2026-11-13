"""Parse github.com/trending (no official API exists for it)."""

import re

import httpx
from selectolax.lexbor import LexborHTMLParser

from trend.models import Repo

TRENDING_URL = "https://github.com/trending{lang}?since=weekly"


def _to_int(text: str) -> int:
    digits = re.sub(r"[^\d]", "", text)
    return int(digits) if digits else 0


def parse_trending(html: str) -> list[Repo]:
    repos: list[Repo] = []
    for row in LexborHTMLParser(html).css("article.Box-row"):
        link = row.css_first("h2 a")
        if link is None:
            continue
        full_name = (link.attributes.get("href") or "").strip("/")
        if full_name.count("/") != 1:
            continue
        desc_node = row.css_first("p")
        lang_node = row.css_first('[itemprop="programmingLanguage"]')
        stars_node = row.css_first('a[href$="/stargazers"]')
        week_match = re.search(r"([\d,]+)\s+stars this week", row.text())
        repos.append(
            Repo(
                full_name=full_name,
                description=desc_node.text(strip=True) if desc_node else "",
                language=lang_node.text(strip=True) if lang_node else None,
                stars=_to_int(stars_node.text()) if stars_node else 0,
                stars_this_week=_to_int(week_match.group(1)) if week_match else None,
            )
        )
    if not repos:
        raise ValueError("Trending page parsed to zero repos; markup may have changed")
    return repos


def fetch_trending(client: httpx.Client, language: str | None = None) -> list[Repo]:
    url = TRENDING_URL.format(lang=f"/{language}" if language else "")
    resp = client.get(url, headers={"Accept": "text/html"})
    resp.raise_for_status()
    return parse_trending(resp.text)
