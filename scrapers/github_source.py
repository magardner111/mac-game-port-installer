"""
GitHub Source Archive scraper.

For projects that have no pre-built macOS release assets and must be compiled
from source. Downloads the source ZIP from GitHub's archive endpoint rather
than from the release assets list.

The "version" is the latest release tag, or the default branch name if no
releases exist.

Optional game config field:
    source_ref_pr_fallback (dict) — Use a PR fork/branch until changes land on
        the main repo.  Fields:
            repo          (str)  — "fork_owner/repo"
            ref           (str)  — branch/tag on the fork
            check_url     (str)  — raw URL to a file in the *main* repo
            check_pattern (str)  — substring to look for in that file;
                                   if FOUND → main repo is ready, use it
                                   if ABSENT → fall back to the PR fork
"""

import urllib.request

from .base import BaseScraper, _gh_request


def _resolve_repo_and_ref(game: dict) -> tuple[str, str]:
    """
    Return (repo, ref) to use for downloading source.

    If ``source_ref_pr_fallback`` is configured, fetch the check URL from the
    main repo.  When the sentinel pattern is NOT yet present the PR fork/branch
    is used instead of the main repo; when it IS present the main repo is used.
    """
    fallback = game.get("source_ref_pr_fallback")
    if fallback:
        check_url     = fallback.get("check_url", "")
        check_pattern = fallback.get("check_pattern", "")
        if check_url and check_pattern:
            try:
                req = urllib.request.Request(
                    check_url,
                    headers={"User-Agent": "game-port-installer/1.0"},
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    content = resp.read().decode(errors="replace")
                if check_pattern in content:
                    # Main branch has the fix — use primary repo/ref
                    return game["repo"], game.get("source_ref", "main")
            except Exception:
                pass
            # Pattern absent or network error → use PR fork
            return fallback["repo"], fallback["ref"]

    return game["repo"], game.get("source_ref", "master")


class GitHubSourceScraper(BaseScraper):
    """
    Returns the GitHub source archive (.zip) for a repo as its sole asset.

    Game config fields used:
        repo                    (str)  — "owner/repo"
        source_ref              (str)  — branch/tag to download; defaults to "master"
        source_ref_pr_fallback  (dict) — optional PR fork override (see module docstring)
    """

    def fetch_latest_release(self, game: dict) -> dict | None:
        repo, ref = _resolve_repo_and_ref(game)

        # Try to find the latest release tag for a meaningful version string
        tag = None
        try:
            releases = _gh_request(f"https://api.github.com/repos/{repo}/releases")
            if isinstance(releases, list) and releases:
                tag = releases[0].get("tag_name")
        except Exception:
            pass

        # Fall back to latest commit SHA on the resolved ref
        if not tag:
            try:
                data = _gh_request(f"https://api.github.com/repos/{repo}/commits/{ref}")
                tag = data["sha"][:7]   # short SHA as version
            except Exception:
                pass

        # If all API calls failed but we have a pinned ref, use it directly.
        # The archive URL is deterministic so we don't need the API to install.
        if not tag:
            tag = ref
        if not tag:
            return None

        project = repo.split("/")[-1]
        # GitHub's /archive/{ref}.zip works for both branches and tags
        archive_url = f"https://github.com/{repo}/archive/{ref}.zip"

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
