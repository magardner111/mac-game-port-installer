"""
GitHub Releases scraper.

Fetches releases via the GitHub REST API and normalizes assets into the
BaseScraper format.  Respects the GITHUB_TOKEN environment variable for
higher rate limits.
"""

import platform
import re

from .base import BaseScraper, _gh_request

_SKIP_TOKENS = (
    "flatpak", "source", ".deb", ".rpm",
    ".sig", ".sha", ".md5", ".txt", ".json",
    "-lsp-",   # language server binaries (e.g. opengoal-lsp-macos-arm-*.bin)
)

_ARCHIVE_EXTS = (".zip", ".tar.gz", ".tar.xz", ".tgz", ".dmg")


def _classify_os(name: str) -> str:
    n = name.lower()
    if any(t in n for t in _SKIP_TOKENS):
        return "Other"
    if any(t in n for t in ("macos", "mac", "osx", "darwin", "apple", ".dmg")):
        return "macOS"
    if any(t in n for t in ("windows", "win64", "win32")) or (
        n.endswith(".exe") and "linux" not in n
    ):
        return "Windows"
    if any(t in n for t in ("linux", "appimage", "x86_64", "amd64")):
        return "Linux"
    return "Other"


def _normalize_asset(raw: dict) -> dict:
    """Convert a raw GitHub asset dict to the BaseScraper normalized format."""
    return {
        "name":         raw["name"],
        "download_url": raw["browser_download_url"],
        "size":         raw.get("size", 0),
        "_raw":         raw,   # preserve original for any edge-case access
    }


class GitHubScraper(BaseScraper):

    def fetch_latest_release(self, game: dict) -> dict | None:
        repo = game["repo"]
        url  = f"https://api.github.com/repos/{repo}/releases"
        try:
            releases = _gh_request(url)
            if not isinstance(releases, list) or not releases:
                return None
            raw = releases[0]
            # Normalize assets in-place so callers always get `download_url`
            raw["assets"] = [_normalize_asset(a) for a in raw.get("assets") or []]
            return raw
        except Exception:
            return None

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _list_assets(self, release: dict) -> list[dict]:
        return [
            a for a in (release.get("assets") or [])
            if not any(t in a["name"].lower() for t in _SKIP_TOKENS)
        ]

    def _has_os_specific(self, release: dict) -> bool:
        return any(_classify_os(a["name"]) != "Other" for a in self._list_assets(release))

    def _generic_assets(self, release: dict) -> list[dict]:
        return [a for a in self._list_assets(release) if _classify_os(a["name"]) == "Other"]

    # ── BaseScraper interface ─────────────────────────────────────────────────

    def assets_for_os(self, release: dict, os_name: str, game: dict) -> list[dict]:
        specific = [
            a for a in self._list_assets(release)
            if _classify_os(a["name"]) == os_name
        ]
        if specific:
            return specific
        # Single generic release: surface under every confirmed platform
        if not self._has_os_specific(release):
            generic = self._generic_assets(release)
            if generic:
                confirmed = game.get("platforms") or []
                if os_name in confirmed or not confirmed:
                    return generic
        return []

    def pick_asset(self, release: dict, os_name: str, game: dict) -> dict | None:
        candidates = self.assets_for_os(release, os_name, game)
        if not candidates:
            return None

        # Architecture-aware selection for macOS assets
        if os_name == "macOS":
            machine     = platform.machine().lower()
            arch_tokens = ["arm64", "aarch64", "arm", "apple", "silicon", "m-series"] if machine == "arm64" else ["intel", "x86_64", "x64"]
            for token in arch_tokens:
                for a in candidates:
                    n = a["name"].lower()
                    if token in n and n.endswith(_ARCHIVE_EXTS):
                        return a
            if machine == "arm64":
                for a in candidates:
                    n = a["name"].lower()
                    if re.search(r"m\d+", n) and n.endswith(_ARCHIVE_EXTS):
                        return a

        # Prefer archives over bare executables
        for a in candidates:
            if a["name"].lower().endswith(_ARCHIVE_EXTS):
                return a
        return candidates[0]
