"""
Abstract base class for release scrapers.

To add a new source (itch.io, direct URL, etc.), subclass BaseScraper,
implement all abstract methods, then register it in scrapers/__init__.py.
"""

import json
import os
import urllib.request
from abc import ABC, abstractmethod


def _get_token() -> str:
    """Return a GitHub token from settings or environment (checked at call time)."""
    try:
        import settings as _s
        tok = _s.get("github_token") or ""
        if tok:
            return tok
    except Exception:
        pass
    return os.environ.get("GITHUB_TOKEN", "")


def _gh_request(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "game-port-installer/1.0"})
    token = _get_token()
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


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
