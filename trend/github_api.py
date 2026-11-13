"""GitHub REST API helpers (search, repo details, README)."""

import os
from datetime import date, timedelta

import httpx

from trend.models import Repo

API = "https://api.github.com"
README_MAX_CHARS = 30_000  # cap per README to keep LLM input (and cost) bounded


def make_client() -> httpx.Client:
    headers = {
        "User-Agent": "github-weekly-trend",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return httpx.Client(headers=headers, timeout=30, follow_redirects=True)


def search_new_repos(client: httpx.Client, today: date, limit: int = 30) -> list[Repo]:
    """Most-starred repos created in the last 7 days."""
    since = (today - timedelta(days=7)).isoformat()
    return _search(client, f"created:>{since}", limit)


def search_topic(client: httpx.Client, topic: str, today: date, within_days: int, limit: int = 15) -> list[Repo]:
    """Most-starred recently created repos tagged with `topic`."""
    since = (today - timedelta(days=within_days)).isoformat()
    return _search(client, f"topic:{topic} created:>{since}", limit)


def _search(client: httpx.Client, query: str, limit: int) -> list[Repo]:
    resp = client.get(
        f"{API}/search/repositories",
        params={"q": query, "sort": "stars", "order": "desc", "per_page": limit},
        headers={"Accept": "application/vnd.github+json"},
    )
    resp.raise_for_status()
    return [
        Repo(
            full_name=item["full_name"],
            description=item.get("description") or "",
            language=item.get("language"),
            stars=item.get("stargazers_count", 0),
            topics=item.get("topics") or [],
        )
        for item in resp.json().get("items", [])
        if not item.get("fork") and not item.get("archived")
    ]


def enrich(client: httpx.Client, repo: Repo) -> None:
    """Fill topics/description/stars from the API and attach the README. Best effort."""
    resp = client.get(f"{API}/repos/{repo.full_name}", headers={"Accept": "application/vnd.github+json"})
    if resp.status_code == 200:
        data = resp.json()
        repo.topics = data.get("topics") or repo.topics
        repo.description = data.get("description") or repo.description
        repo.language = data.get("language") or repo.language
        repo.stars = data.get("stargazers_count", repo.stars)
    resp = client.get(f"{API}/repos/{repo.full_name}/readme", headers={"Accept": "application/vnd.github.raw"})
    if resp.status_code == 200:
        repo.readme = resp.text[:README_MAX_CHARS]
