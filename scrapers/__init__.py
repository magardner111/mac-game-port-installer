"""
Scraper registry.

Usage:
    from scrapers import get_scraper
    scraper = get_scraper(game)
    release = scraper.fetch_latest_release(game)

To add a new scraper:
    1. Subclass BaseScraper in a new module under scrapers/
    2. Call register("my_source", MySourceScraper()) here
    3. Set "scraper": "my_source" in the game's entry in games.py
       (defaults to "github" if omitted)
"""

from .base import BaseScraper
from .github import GitHubScraper
from .github_source import GitHubSourceScraper
from .t3hd0gg import T3hd0ggScraper

_REGISTRY: dict[str, BaseScraper] = {
    "github":        GitHubScraper(),
    "github_source": GitHubSourceScraper(),
    "t3hd0gg":       T3hd0ggScraper(),
}


def get_scraper(game: dict) -> BaseScraper:
    key = game.get("scraper", "github")
    if key not in _REGISTRY:
        raise KeyError(f"Unknown scraper {key!r} for game {game.get('name')!r}")
    return _REGISTRY[key]


def register(name: str, scraper: BaseScraper) -> None:
    """Register a new scraper at runtime."""
    _REGISTRY[name] = scraper
