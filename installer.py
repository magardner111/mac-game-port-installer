"""
Core install / update / launch / uninstall logic.
Pure stdlib – no third-party packages required.

Release fetching and asset selection are delegated to the scrapers package
so new sources (itch.io, direct URLs, etc.) can be added without touching
this file.
"""

import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

from scrapers import get_scraper

# ── Paths ──────────────────────────────────────────────────────────────────────

def _default_games_dir() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "GamePortInstaller" / "games"
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", str(Path.home()))) / "GamePortInstaller" / "games"
    return Path.home() / ".local" / "share" / "GamePortInstaller" / "games"

GAMES_DIR = _default_games_dir()

OS_NAMES = ["macOS", "Linux", "Windows"]


# ── Scraper-delegating helpers ─────────────────────────────────────────────────

def fetch_latest_release(game: dict) -> dict | None:
    return get_scraper(game).fetch_latest_release(game)


def assets_for_os(release: dict, os_name: str, game: dict = {}) -> list[dict]:
    return get_scraper(game).assets_for_os(release, os_name, game)


def pick_asset(release: dict, os_name: str, game: dict = {}) -> dict | None:
    return get_scraper(game).pick_asset(release, os_name, game)


# ── Version tracking ──────────────────────────────────────────────────────────

def game_dir(game: dict, os_name: str = None) -> Path:
    base = GAMES_DIR / game["folder"]
    return base / os_name if os_name else base

def installed_version(game: dict, os_name: str = None) -> str | None:
    vfile = game_dir(game, os_name) / "version.txt"
    if vfile.exists():
        return vfile.read_text().strip() or None
    return None

def installed_oses(game: dict) -> dict[str, str]:
    """Return {os_name: version} for every OS that has a version.txt."""
    result = {}
    for os_name in OS_NAMES:
        v = installed_version(game, os_name)
        if v:
            result[os_name] = v
    return result

def is_installed(game: dict) -> bool:
    return bool(installed_oses(game))


# ── Download ───────────────────────────────────────────────────────────────────

def download_asset(asset: dict, progress_cb=None) -> Path:
    url  = asset.get("download_url") or asset.get("browser_download_url")
    name = asset["name"]
    fd, tmp_path = tempfile.mkstemp(suffix="_" + name)
    os.close(fd)
    tmp = Path(tmp_path)

    req = urllib.request.Request(url, headers={"User-Agent": "game-port-installer/1.0"})

    with urllib.request.urlopen(req, timeout=60) as resp:
        total      = int(resp.headers.get("Content-Length") or 0)
        downloaded = 0
        with open(tmp, "wb") as f:
            while True:
                buf = resp.read(65536)
                if not buf:
                    break
                f.write(buf)
                downloaded += len(buf)
                if progress_cb and total:
                    progress_cb(int(downloaded / total * 100))

    if progress_cb:
        progress_cb(100)
    return tmp


# ── Extraction ─────────────────────────────────────────────────────────────────

def _find_app_bundle(directory: Path) -> Path | None:
    for p in directory.rglob("*.app"):
        if p.is_dir():
            return p
    return None


def extract_asset(tmp_path: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    name = tmp_path.name.lower()

    if name.endswith(".dmg"):
        _install_dmg(tmp_path, dest)
        return
    if name.endswith(".zip"):
        _extract_zip(tmp_path, dest)
        return
    if name.endswith((".tar.gz", ".tgz", ".tar.xz", ".txz")):
        subprocess.run(["tar", "-xf", str(tmp_path), "-C", str(dest)], check=True)
        _flatten_if_needed(dest)
        return
    # Bare executable
    target = dest / tmp_path.name
    shutil.move(str(tmp_path), target)
    target.chmod(target.stat().st_mode | 0o755)


def _unzip(src: Path, target_dir: Path) -> None:
    """Extract a zip using the system unzip — preserves symlinks and permissions."""
    subprocess.run(["unzip", "-q", str(src), "-d", str(target_dir)], check=True)


def _extract_zip(tmp_path: Path, dest: Path) -> None:
    with tempfile.TemporaryDirectory() as staging:
        _unzip(tmp_path, Path(staging))
        _move_from_staging(Path(staging), dest)


def _move_from_staging(staging: Path, dest: Path) -> None:
    """Inspect staging and move the game content into dest, handling nested archives."""
    # .app bundle — move directly
    app = _find_app_bundle(staging)
    if app:
        target = dest / app.name
        if target.exists():
            shutil.rmtree(target)
        shutil.move(str(app), dest)
        return

    # Nested zip — unzip into a fresh staging dir and recurse
    inner_zips = [p for p in staging.rglob("*.zip") if p.is_file()]
    if inner_zips:
        with tempfile.TemporaryDirectory() as inner_staging:
            _unzip(inner_zips[0], Path(inner_staging))
            _move_from_staging(Path(inner_staging), dest)
        return

    # Nested tar
    inner_tars = list(staging.rglob("*.tar.gz")) + list(staging.rglob("*.tar.xz"))
    if inner_tars:
        mode = "r:gz" if inner_tars[0].name.endswith(".tar.gz") else "r:xz"
        with tarfile.open(inner_tars[0], mode) as tf:
            tf.extractall(dest)
        _flatten_if_needed(dest)
        return

    # Nested DMG
    inner_dmgs = list(staging.rglob("*.dmg"))
    if inner_dmgs:
        _install_dmg(inner_dmgs[0], dest)
        return

    # Generic fallback — move everything to dest
    for item in staging.iterdir():
        target = dest / item.name
        if target.exists():
            shutil.rmtree(target) if target.is_dir() else target.unlink()
        shutil.move(str(item), dest)
    _flatten_if_needed(dest)


def _install_dmg(dmg_path: Path, dest: Path) -> None:
    mount_point = Path(tempfile.mkdtemp())
    try:
        subprocess.run(
            ["hdiutil", "attach", str(dmg_path), "-mountpoint", str(mount_point),
             "-nobrowse", "-quiet"],
            check=True,
        )
        app = _find_app_bundle(mount_point)
        if not app:
            raise RuntimeError(f"No .app bundle found in {dmg_path.name}")
        target = dest / app.name
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(str(app), target)
    finally:
        subprocess.run(["hdiutil", "detach", str(mount_point), "-quiet"], check=False)
        shutil.rmtree(mount_point, ignore_errors=True)


def _flatten_if_needed(dest: Path) -> None:
    items = [i for i in dest.iterdir() if i.name != "version.txt"]
    if len(items) == 1 and items[0].is_dir():
        inner = items[0]
        with tempfile.TemporaryDirectory() as _tmp:
            staging = Path(_tmp) / "s"
            shutil.move(str(inner), staging)
            for item in staging.iterdir():
                shutil.move(str(item), dest)


# ── Build-from-source ─────────────────────────────────────────────────────────

def _find_makefile_dir(dest: Path) -> Path:
    """Return the directory containing the Makefile, searching recursively."""
    # Check dest itself first
    if (dest / "Makefile").exists():
        return dest
    # Search one level deep (common case: zelda3-v0.3/Makefile)
    for p in dest.rglob("Makefile"):
        return p.parent
    return dest  # fallback


def _build_game(game: dict, dest: Path, progress_cb=None) -> None:
    """
    Run the build steps defined in game["build"]:
        brew             (list[str])  — homebrew packages to install first
        pip_requirements (str)        — path to requirements.txt relative to build_dir
        make_target      (str)        — make target; defaults to the game folder name
        make_jobs        (bool)       — pass -j{cpu_count}; default True
        make_cflags      (str)        — extra CFLAGS passed to make
    """
    build = game.get("build", {})

    def _cb(pct):
        if progress_cb:
            progress_cb(pct)

    # Locate the directory that actually contains the Makefile
    build_dir = _find_makefile_dir(dest)

    # 1. brew deps
    brew_pkgs = build.get("brew", [])
    if brew_pkgs:
        if not shutil.which("brew"):
            raise RuntimeError(
                "Homebrew is required to install dependencies for this game.\n\n"
                "Install Homebrew from https://brew.sh and try again."
            )
        _cb(82)
        subprocess.run(["brew", "install"] + brew_pkgs, check=False)

    # 2. pip requirements (relative to build_dir)
    pip_req = build.get("pip_requirements")
    if pip_req:
        _cb(86)
        subprocess.run(
            ["pip3", "install", "--break-system-packages", "-r", pip_req],
            cwd=str(build_dir), check=False,
        )

    # 3. make clean (remove any stale compiled artifacts before rebuilding)
    _cb(88)
    subprocess.run(["make", "clean"], cwd=str(build_dir), check=False)

    # 4. make
    _cb(90)
    target      = build.get("make_target", "")
    jobs        = build.get("make_jobs", True)
    make_cflags = build.get("make_cflags")
    cmd         = ["make"]
    if jobs:
        cmd += [f"-j{os.cpu_count() or 1}"]
    if target:
        cmd.append(target)

    # Pass extra CFLAGS via environment so the Makefile can append its own flags
    # (e.g. sdl2-config --cflags). Command-line CFLAGS= would override the whole
    # Makefile CFLAGS variable and drop SDL2 include paths.
    env = os.environ.copy()
    if make_cflags:
        env["CFLAGS"] = make_cflags

    subprocess.run(cmd, cwd=str(build_dir), check=True, env=env)

    # 5. If build_dir is a subdirectory of dest, move the built binary up
    if build_dir != dest:
        binary_name = target or game.get("folder", "").lower()
        for candidate in [build_dir / binary_name, build_dir / f"{binary_name}.app"]:
            if candidate.exists():
                target_path = dest / candidate.name
                if target_path.exists():
                    shutil.rmtree(target_path) if target_path.is_dir() else target_path.unlink()
                shutil.move(str(candidate), dest)
                break

    _cb(99)


# ── High-level install ────────────────────────────────────────────────────────

def install_game(game: dict, release: dict, asset: dict, os_name: str,
                 progress_cb=None) -> str:
    tag          = release.get("tag_name", "unknown")
    has_build    = bool(game.get("build"))
    dl_scale     = 0.7 if has_build else 0.9   # leave headroom for compile step

    tmp = download_asset(
        asset,
        progress_cb=lambda p: progress_cb and progress_cb(int(p * dl_scale)),
    )
    try:
        dest = game_dir(game, os_name)
        extract_asset(tmp, dest)
    finally:
        tmp.unlink(missing_ok=True)

    if has_build:
        if progress_cb:
            progress_cb(80)
        _build_game(game, dest, progress_cb)

    (game_dir(game, os_name) / "version.txt").write_text(tag)
    if progress_cb:
        progress_cb(100)
    return tag


# ── Uninstall ──────────────────────────────────────────────────────────────────

def uninstall_game(game: dict, os_name: str) -> None:
    d = game_dir(game, os_name)
    if d.exists():
        shutil.rmtree(d)
    # Remove parent folder if now empty
    parent = game_dir(game)
    if parent.exists() and not any(parent.iterdir()):
        parent.rmdir()


# ── Launch ─────────────────────────────────────────────────────────────────────

_SKIP_LAUNCH_SUFFIXES = {
    ".dylib", ".so", ".a", ".o", ".plist", ".nib", ".lproj",
    ".png", ".jpg", ".jpeg", ".gif", ".icns", ".tiff",
    ".txt", ".md", ".rtf", ".html", ".css", ".js",
    ".json", ".xml", ".yaml", ".toml", ".cfg", ".ini",
    ".zip", ".tar", ".gz", ".xz", ".jar", ".class",
    ".cmake", ".metallib", ".h",
}

# Suffixes that identify architecture-specific binaries (no execute bit required)
_ARCH_BINARY_SUFFIXES = {".arm64", ".x86_64", ".amd64"}


def _find_launchable(d: Path):
    # Prefer .app bundles — search recursively, favour shallowest
    apps = sorted(
        (p for p in d.rglob("*.app") if p.is_dir()),
        key=lambda p: len(p.parts),
    )
    if apps:
        return ("app", apps[0])

    candidates = []
    for f in d.rglob("*"):
        if not f.is_file():
            continue
        rel_parts = f.parts[len(d.parts):-1]
        if any(p.endswith((".app", ".framework")) for p in rel_parts):
            continue
        suffix = f.suffix.lower()
        if suffix in _SKIP_LAUNCH_SUFFIXES:
            continue
        # Accept arch-suffixed binaries even without execute bit
        if suffix in _ARCH_BINARY_SUFFIXES or (f.stat().st_mode & 0o111):
            candidates.append(f)

    if not candidates:
        return (None, None)

    candidates.sort(key=lambda p: (len(p.parts), p.name))

    # Prefer known launch-script names
    for f in candidates:
        if "launch" in f.name.lower():
            f.chmod(f.stat().st_mode | 0o755)
            return ("bin", f)

    # Prefer arch-suffixed binary that matches the current machine
    machine = platform.machine().lower()
    for f in candidates:
        if f.suffix.lower() in _ARCH_BINARY_SUFFIXES and machine in f.name.lower():
            f.chmod(f.stat().st_mode | 0o755)
            return ("bin", f)

    # Fall back to first candidate
    best = candidates[0]
    best.chmod(best.stat().st_mode | 0o755)
    return ("bin", best)


def launch_game(game: dict, os_name: str) -> None:
    d = game_dir(game, os_name)
    kind, target = _find_launchable(d)
    if kind is None:
        raise FileNotFoundError(f"No launchable found in {d}")
    if kind == "app":
        subprocess.Popen(["open", str(target)])
    else:
        subprocess.Popen([str(target)], cwd=str(d))


# ── Finder ────────────────────────────────────────────────────────────────────

def reveal_in_finder(path: Path) -> None:
    """Select the item in Finder, or open its parent if it's a directory."""
    if path.is_dir():
        subprocess.run(["open", str(path)], check=False)
    else:
        subprocess.run(["open", "-R", str(path)], check=False)
