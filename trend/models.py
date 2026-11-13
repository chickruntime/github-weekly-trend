from dataclasses import dataclass, field


@dataclass
class Repo:
    full_name: str  # "owner/name"
    description: str = ""
    language: str | None = None
    stars: int = 0
    stars_this_week: int | None = None  # only known when scraped from Trending
    topics: list[str] = field(default_factory=list)
    readme: str = ""

    @property
    def url(self) -> str:
        return f"https://github.com/{self.full_name}"


@dataclass
class Summary:
    what: str
    why: str
    who: str


@dataclass
class Entry:
    repo: Repo
    summary: Summary
    rank: int | None = None  # None for extra picks
    streak: int = 1  # consecutive weeks featured, including this one
    pick_reason: str | None = None
