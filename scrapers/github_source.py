"""
GitHub Source Archive scraper.

For projects that have no pre-built macOS release assets and must be compiled
from source. Downloads the source ZIP from GitHub's archive endpoint rather
than from the release assets list.

The "version" is the latest release tag, or the default branch name if no
releases exist.
"""

from .base import BaseScraper, _gh_request


class GitHubSourceScraper(BaseScraper):
    """
    Returns the GitHub source archive (.zip) for a repo as its sole asset.

    Game config fields used:
        repo         (str)  — "owner/repo"
        source_ref   (str)  — branch/tag to download; defaults to repo default branch
                              e.g. "master", "main", "v0.3"
    """

    def fetch_latest_release(self, game: dict) -> dict | None:
        repo = game["repo"]

        # Try to find the latest release tag for a meaningful version string
        tag = None
        try:
            releases = _gh_request(f"https://api.github.com/repos/{repo}/releases")
            if isinstance(releases, list) and releases:
                tag = releases[0].get("tag_name")
        except Exception:
            pass

        # Fall back to latest commit SHA on the default branch
        if not tag:
            try:
                ref = game.get("source_ref", "master")
                data = _gh_request(f"https://api.github.com/repos/{repo}/commits/{ref}")
                tag = data["sha"][:7]   # short SHA as version
            except Exception:
                return None

        ref = game.get("source_ref") or tag
        project = repo.split("/")[-1]
        archive_url = f"https://github.com/{repo}/archive/refs/tags/{ref}.zip"

        return {
            "tag_name": tag,
            "assets": [{
                "name":         f"{project}-{ref}-source.zip",
                "download_url": archive_url,
                "size":         0,
            }],
        }

    def assets_for_os(self, release: dict, os_name: str, game: dict) -> list[dict]:
        # Source archive is platform-agnostic; surface it for any confirmed platform
        if os_name in game.get("platforms", []):
            return release.get("assets", [])
        return []

    def pick_asset(self, release: dict, os_name: str, game: dict) -> dict | None:
        candidates = self.assets_for_os(release, os_name, game)
        return candidates[0] if candidates else None
