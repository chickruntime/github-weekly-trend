from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass
class Category:
    id: str
    title: str
    description: str
    languages: list[str]
    topics: list[str]


@dataclass
class Config:
    model: str
    top_n: int
    category_max: int
    extras_max: int
    topic_created_within_days: int
    categories: list[Category]


def load_config(path: Path) -> Config:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return Config(
        model=raw["model"],
        top_n=raw["top_n"],
        category_max=raw["category_max"],
        extras_max=raw["extras_max"],
        topic_created_within_days=raw["topic_created_within_days"],
        categories=[Category(**c) for c in raw["categories"]],
    )
