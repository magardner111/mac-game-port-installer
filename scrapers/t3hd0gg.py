"""
Scraper for t3hd0gg.com project pages (e.g. Project R).

These pages list downloads as plain <a href> links on a release page.
No API — we parse the HTML directly.

URL pattern:  /<project>/<version>/<project>-<version>-<os>.<ext>
"""

import re
import urllib.request
from html.parser import HTMLParser

from .base import BaseScraper

_BASE = "https://t3hd0gg.com"

_DOWNLOAD_EXTS = (".dmg", ".zip", ".tar.gz", ".tgz", ".exe", ".appimage")

_OS_TOKENS = {
    "macOS":   ("macos", "mac", "osx", "darwin"),
    "Windows": ("windows", "win"),
    "Linux":   ("linux", "appimage"),
}


def _classify_os(name: str) -> str:
    n = name.lower()
    for os_name, tokens in _OS_TOKENS.items():
        if any(t in n for t in tokens):
            return os_name
    return "Other"


class _LinkParser(HTMLParser):
    """Collect all href values from <a> tags."""
    def __init__(self):
        super().__init__()
        self.hrefs: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            for key, val in attrs:
                if key == "href" and val:
                    self.hrefs.append(val)


def _fetch_html(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "game-port-installer/1.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read().decode("utf-8", errors="replace")


class T3hd0ggScraper(BaseScraper):

    def fetch_latest_release(self, game: dict) -> dict | None:
        page_url = game.get("scraper_url")
        if not page_url:
            return None
        try:
            html = _fetch_html(page_url)
        except Exception:
            return None

        parser = _LinkParser()
        parser.feed(html)

        # Collect download links and extract the highest version seen
        assets:   list[dict] = []
        versions: list[str]  = []

        for href in parser.hrefs:
            lower = href.lower()
            if not any(lower.endswith(ext) for ext in _DOWNLOAD_EXTS):
                continue

            # Resolve relative URLs
            if href.startswith("/"):
                full_url = _BASE + href
            elif href.startswith("http"):
                full_url = href
            else:
                # relative to the page
                base = page_url.rstrip("/")
                full_url = base + "/" + href

            filename = full_url.rsplit("/", 1)[-1]

            # Extract version from URL path segment (e.g. .../0.7.1/...)
            m = re.search(r"/(\d+\.\d+[\d.]*)/" , full_url)
            version = m.group(1) if m else "unknown"
            if version != "unknown":
                versions.append(version)

            assets.append({
                "name":         filename,
                "download_url": full_url,
                "size":         0,
                "_version":     version,
            })

        if not assets:
            return None

        # Use the most recent (highest) version seen across all links
        def _ver_key(v: str):
            try:
                return tuple(int(x) for x in v.split("."))
            except ValueError:
                return (0,)

        latest = max(set(versions), key=_ver_key) if versions else "unknown"

        # Keep only assets that match the latest version
        assets = [a for a in assets if a["_version"] == latest]

        return {
            "tag_name": f"v{latest}",
            "assets":   assets,
        }

    def assets_for_os(self, release: dict, os_name: str, game: dict) -> list[dict]:
        return [
            a for a in (release.get("assets") or [])
            if _classify_os(a["name"]) == os_name
        ]

    def pick_asset(self, release: dict, os_name: str, game: dict) -> dict | None:
        candidates = self.assets_for_os(release, os_name, game)
        if not candidates:
            return None
        # Prefer DMG on macOS, otherwise first match
        for a in candidates:
            if a["name"].lower().endswith(".dmg"):
                return a
        return candidates[0]
