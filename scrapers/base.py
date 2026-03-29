"""
Abstract base class for release scrapers.

To add a new source (itch.io, direct URL, etc.), subclass BaseScraper,
implement all abstract methods, then register it in scrapers/__init__.py.
"""

from abc import ABC, abstractmethod


class BaseScraper(ABC):

    @abstractmethod
    def fetch_latest_release(self, game: dict) -> dict | None:
        """
        Fetch the latest release for a game.
        Returns a normalized release dict, or None on failure.

        Required keys in the returned dict:
            tag_name  (str)   — version string, e.g. "v1.2.3"
            assets    (list)  — list of normalized asset dicts (see below)

        Each asset dict must contain:
            name          (str)   — filename, e.g. "MyGame-macOS.zip"
            download_url  (str)   — direct download URL
            size          (int)   — file size in bytes (0 if unknown)
        """
        ...

    @abstractmethod
    def assets_for_os(self, release: dict, os_name: str, game: dict) -> list[dict]:
        """Return assets from release that match os_name ("macOS", "Windows", "Linux")."""
        ...

    @abstractmethod
    def pick_asset(self, release: dict, os_name: str, game: dict) -> dict | None:
        """Pick the single best asset for os_name, or None if unavailable."""
        ...
