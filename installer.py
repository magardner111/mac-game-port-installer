"""
Core install / update / launch / uninstall logic.
Pure stdlib – no third-party packages required.

Release fetching and asset selection are delegated to the scrapers package
so new sources (itch.io, direct URLs, etc.) can be added without touching
this file.
"""

import json
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

GAMES_DIR = Path(__file__).parent / "games"

OS_NAMES = ["macOS", "Linux", "Windows"]


def _migrate_to_console_dirs() -> None:
    """Move flat games/{folder} installs into games/{console}/{folder}."""
    if not GAMES_DIR.is_dir():
        return
    from games import GAMES
    folder_to_console = {g["folder"]: g.get("console", "Other") for g in GAMES}
    for item in list(GAMES_DIR.iterdir()):
        if not item.is_dir() or item.name.startswith("."):
            continue
        # Already nested under a console dir — skip
        if item.name in folder_to_console.values():
            continue
        console = folder_to_console.get(item.name)
        if not console:
            continue
        dest = GAMES_DIR / console / item.name
        if not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(item), dest)

_migrate_to_console_dirs()


# ── Release cache ──────────────────────────────────────────────────────────────

def _cache_path() -> Path:
    return GAMES_DIR.parent / "release_cache.json"  # project root

def _load_cache() -> dict:
    p = _cache_path()
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:
            pass
    return {}

def _save_cache(updates: dict) -> None:
    """Merge `updates` (folder → release) into the on-disk cache."""
    try:
        cache = _load_cache()
        cache.update(updates)
        _cache_path().parent.mkdir(parents=True, exist_ok=True)
        _cache_path().write_text(json.dumps(cache))
    except Exception:
        pass


# ── Scraper-delegating helpers ─────────────────────────────────────────────────

def fetch_latest_release(game: dict) -> dict | None:
    try:
        release = get_scraper(game).fetch_latest_release(game)
        if release:
            _save_cache({game["folder"]: release})
            return release
    except Exception:
        pass
    # Fall back to cached data when the network/API is unavailable
    return _load_cache().get(game["folder"])


def assets_for_os(release: dict, os_name: str, game: dict = {}) -> list[dict]:
    return get_scraper(game).assets_for_os(release, os_name, game)


def pick_asset(release: dict, os_name: str, game: dict = {}) -> dict | None:
    return get_scraper(game).pick_asset(release, os_name, game)


# ── Version tracking ──────────────────────────────────────────────────────────

def game_dir(game: dict, os_name: str = None) -> Path:
    console = game.get("console", "Other")
    base = GAMES_DIR / console / game["folder"]
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
        result = subprocess.run(
            ["hdiutil", "attach", str(dmg_path), "-mountpoint", str(mount_point),
             "-nobrowse", "-noverify"],
            input=b"y\n",   # auto-accept any software license agreement
            capture_output=True,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"hdiutil attach failed (exit {result.returncode}):\n"
                + result.stderr.decode(errors="replace").strip()
            )
        app = _find_app_bundle(mount_point)
        if not app:
            raise RuntimeError(f"No .app bundle found in {dmg_path.name}")
        target = dest / app.name
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(str(app), target, symlinks=True)
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


def _find_homebrew_gcc(build_env: dict) -> tuple[str | None, str | None]:
    """Return (gcc_path, g++_path) for the highest-versioned Homebrew GCC, or (None, None)."""
    hb_bin = Path("/opt/homebrew/bin")
    gccs = sorted(hb_bin.glob("gcc-[0-9]*"), reverse=True)
    for gcc in gccs:
        if gcc.stat().st_mode & 0o111:
            gxx = hb_bin / gcc.name.replace("gcc-", "g++-")
            return str(gcc), str(gxx) if gxx.exists() else str(gcc)
    return None, None


def _find_gcc_compatible_sysroot() -> str | None:
    """
    Return the path to the newest macOS SDK that Homebrew GCC can parse.

    The macOS 26 SDK introduced xnu_static_assert_struct_size* macros in
    mach/message.h that Homebrew GCC cannot handle.  Fall back to the
    newest available SDK whose major version is ≤ 15.
    """
    sdks_dir = Path("/Library/Developer/CommandLineTools/SDKs")
    if not sdks_dir.is_dir():
        return None

    compatible = []
    for sdk in sdks_dir.glob("MacOSX*.sdk"):
        name = sdk.name  # e.g. "MacOSX15.4.sdk"
        ver_str = name.removeprefix("MacOSX").removesuffix(".sdk")
        try:
            major = int(ver_str.split(".")[0])
        except ValueError:
            continue
        if major <= 15:
            compatible.append((major, ver_str, sdk))

    if not compatible:
        return None

    # Pick the highest version that is still ≤ 15
    compatible.sort(key=lambda t: [int(x) for x in t[1].split(".")], reverse=True)
    return str(compatible[0][2])


def _build_cmake(game: dict, build: dict, dest: Path, build_env: dict, _cb) -> None:
    """Run a cmake configure + build inside dest."""
    cmake_source_subdir = build.get("cmake_source_subdir", ".")

    # Locate the cmake source dir — it may be nested after extraction/flattening
    if cmake_source_subdir == ".":
        cmake_src = dest
    else:
        cmake_src = dest / cmake_source_subdir
        if not cmake_src.exists():
            # Search recursively for the subdir
            for candidate in dest.rglob(cmake_source_subdir):
                if candidate.is_dir():
                    cmake_src = candidate
                    break

    if not (cmake_src / "CMakeLists.txt").exists():
        raise RuntimeError(
            f"CMakeLists.txt not found in {cmake_src}\n"
            "Cannot build this game from source."
        )

    # Use GCC instead of Apple Clang if requested
    sysroot: str | None = None
    if build.get("cmake_use_gcc"):
        gcc, gxx = _find_homebrew_gcc(build_env)
        if not gcc:
            raise RuntimeError(
                "Homebrew GCC is required to build this game.\n\n"
                "Install it with:  brew install gcc"
            )
        build_env["CC"]  = gcc
        build_env["CXX"] = gxx

        # macOS 26 SDK introduced xnu_static_assert_struct_size* macros that
        # Homebrew GCC cannot parse.  Use the newest SDK whose major ≤ 15.
        sysroot = _find_gcc_compatible_sysroot()
        if sysroot:
            build_env.setdefault("CFLAGS",   "")
            build_env.setdefault("CXXFLAGS", "")
            build_env["CFLAGS"]   = build_env["CFLAGS"].strip() + f" -isysroot {sysroot}"
            build_env["CXXFLAGS"] = build_env["CXXFLAGS"].strip() + f" -isysroot {sysroot}"

    # Wipe stale cmake cache so a fresh configure always starts clean
    cmake_build_dir = cmake_src / "build"
    if cmake_build_dir.exists():
        shutil.rmtree(cmake_build_dir)
    cmake_build_dir.mkdir()

    # Configure
    _cb(88)
    cmake_args = build.get("cmake_args", [])
    sysroot_cmake_args = ([f"-DCMAKE_OSX_SYSROOT={sysroot}"] if sysroot else [])
    configure_cmd = ["cmake", str(cmake_src)] + sysroot_cmake_args + cmake_args
    result = subprocess.run(
        configure_cmd, cwd=str(cmake_build_dir), env=build_env,
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        output = (result.stdout + result.stderr).strip()
        raise RuntimeError(f"CMake configure failed:\n\n{output[-3000:]}")

    # Build
    _cb(90)
    jobs = build.get("make_jobs", True)
    build_cmd = ["cmake", "--build", "."]
    if jobs:
        build_cmd += ["--parallel", str(os.cpu_count() or 1)]
    result = subprocess.run(
        build_cmd, cwd=str(cmake_build_dir), env=build_env,
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        output = (result.stdout + result.stderr).strip()
        raise RuntimeError(f"CMake build failed:\n\n{output[-3000:]}")

    # If the game specifies a launch_subdir the binary stays where cmake put it
    # (the launch dir is already correct relative to its resources).
    # Otherwise move the binary up to dest so launch_game can find it.
    if not game.get("launch_subdir"):
        binary_name = build.get("cmake_binary", game.get("folder", "").lower())
        moved = False
        for candidate in [
            cmake_build_dir / binary_name,
            cmake_build_dir / f"{binary_name}.app",
            cmake_build_dir / "Release" / binary_name,
            cmake_build_dir / "Release" / f"{binary_name}.app",
            cmake_build_dir / "bin" / binary_name,
            cmake_build_dir / "bin" / f"{binary_name}.app",
        ]:
            if candidate.exists():
                target_path = dest / candidate.name
                if target_path.exists():
                    shutil.rmtree(target_path) if target_path.is_dir() else target_path.unlink()
                shutil.move(str(candidate), dest)
                moved = True
                break
        if not moved:
            # Fallback: search for any executable in the build dir
            for f in cmake_build_dir.rglob("*"):
                if f.is_file() and (f.stat().st_mode & 0o111) and f.suffix not in {".cmake", ".h", ".cpp", ".c"}:
                    target_path = dest / f.name
                    if not target_path.exists():
                        shutil.move(str(f), dest)
                    break


def _build_game(game: dict, dest: Path, progress_cb=None) -> None:
    """
    Run the build steps defined in game["build"]:
        brew                (list[str])  — homebrew packages to install first
        pip_requirements    (str)        — path to requirements.txt relative to build_dir
        cmake               (bool)       — use cmake instead of make
        cmake_source_subdir (str)        — subdir containing CMakeLists.txt (default ".")
        cmake_use_gcc       (bool)       — configure cmake to use Homebrew GCC
        cmake_args          (list[str])  — extra args for cmake configure step
        cmake_binary        (str)        — name of produced binary to move to dest
        make_target         (str)        — make target; defaults to the game folder name
        make_jobs           (bool)       — pass -j{cpu_count}; default True
        make_cflags         (str)        — extra CFLAGS passed to make
    """
    build = game.get("build", {})

    def _cb(pct):
        if progress_cb:
            progress_cb(pct)

    # Build a PATH that includes Homebrew regardless of how the app was launched
    # (.app bundles don't always inherit the user's shell PATH).
    homebrew_bin = "/opt/homebrew/bin"
    base_path    = os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin")
    build_env    = os.environ.copy()
    if homebrew_bin not in base_path:
        build_env["PATH"] = homebrew_bin + ":" + base_path

    # 1. brew deps
    brew_pkgs = build.get("brew", [])
    if brew_pkgs:
        if not shutil.which("brew", path=build_env["PATH"]):
            raise RuntimeError(
                "Homebrew is required to install dependencies for this game.\n\n"
                "Install Homebrew from https://brew.sh and try again."
            )
        _cb(82)
        subprocess.run(["brew", "install"] + brew_pkgs, check=False, env=build_env)

    # ── cmake path ──────────────────────────────────────────────────────────────
    if build.get("cmake"):
        # pip requirements (relative to dest) if any
        pip_req = build.get("pip_requirements")
        if pip_req:
            _cb(86)
            subprocess.run(
                ["pip3", "install", "--break-system-packages", "-r", pip_req],
                cwd=str(dest), check=False, env=build_env,
            )
        _build_cmake(game, build, dest, build_env, _cb)
        _cb(99)
        return

    # ── make path ───────────────────────────────────────────────────────────────

    # Locate the directory that actually contains the Makefile
    build_dir = _find_makefile_dir(dest)

    # 2. pip requirements (relative to build_dir)
    pip_req = build.get("pip_requirements")
    if pip_req:
        _cb(86)
        subprocess.run(
            ["pip3", "install", "--break-system-packages", "-r", pip_req],
            cwd=str(build_dir), check=False, env=build_env,
        )

    # 3. make clean (remove any stale compiled artifacts before rebuilding)
    _cb(88)
    subprocess.run(["make", "clean"], cwd=str(build_dir), check=False, env=build_env)

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
    if make_cflags:
        build_env["CFLAGS"] = make_cflags

    result = subprocess.run(cmd, cwd=str(build_dir), env=build_env,
                            capture_output=True, text=True)

    if result.returncode != 0:
        output = (result.stdout + result.stderr).strip()
        raise RuntimeError(
            f"Build failed (exit {result.returncode}):\n\n{output[-3000:]}"
        )

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

    _cleanup_build_artifacts(game, dest)
    _cb(99)


def _cleanup_build_artifacts(game: dict, dest: Path) -> None:
    """
    Remove source files from dest after a successful build.

    For games with ``launch_subdir``: only that subdirectory is kept —
    everything else (source tree, intermediate object files, etc.) is deleted.

    For plain make builds: subdirectories that look like source trees
    (contain a Makefile, CMakeLists.txt, src/, or .git/) are removed.
    """
    launch_subdir = game.get("launch_subdir")
    if launch_subdir:
        run_dir = dest / launch_subdir
        if not run_dir.exists():
            return
        # Stash the run dir next to dest (same filesystem — no copy needed),
        # wipe dest, then restore the run dir at its original relative path.
        hold = dest.parent / f".gpi_keep_{dest.name}"
        try:
            shutil.move(str(run_dir), str(hold))
            for item in list(dest.iterdir()):
                shutil.rmtree(item) if item.is_dir() else item.unlink()
            run_dir.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(hold), str(run_dir))
        finally:
            if hold.exists():
                shutil.rmtree(hold, ignore_errors=True)
    else:
        # Make builds: remove subdirs that contain obvious source markers.
        _SOURCE_MARKERS = {"Makefile", "CMakeLists.txt", "src", "include", ".git"}
        for item in list(dest.iterdir()):
            if item.is_dir() and any((item / m).exists() for m in _SOURCE_MARKERS):
                shutil.rmtree(item)


# ── GB Recompiled pipeline ────────────────────────────────────────────────────

def _gb_env() -> dict:
    """Build environment with Homebrew in PATH."""
    homebrew_bin = "/opt/homebrew/bin"
    base = os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin")
    env = os.environ.copy()
    if homebrew_bin not in base:
        env["PATH"] = homebrew_bin + ":" + base
    return env


def _gb_get_source(work_dir: Path) -> Path:
    """
    Clone (or update) the gb-recompiled repo into work_dir/gbrecomp_src.
    Returns the repo root path — needed for the runtime source files that
    the generated CMakeLists.txt references with hardcoded absolute paths.
    """
    src = work_dir / "gbrecomp_src"
    env = _gb_env()
    if src.exists():
        subprocess.run(
            ["git", "-C", str(src), "pull", "--depth=1"],
            env=env, capture_output=True,
        )
    else:
        subprocess.run(
            ["git", "clone", "--depth=1",
             "https://github.com/arcanite24/gb-recompiled.git", str(src)],
            env=env, capture_output=True, check=True,
        )
    return src.resolve()


def _gb_patch_cmake(recomp_out: Path, gbrecomp_src: Path) -> None:
    """
    Fix hardcoded paths in the generated CMakeLists.txt.

    gb-recompiled embeds its build-time absolute paths for the runtime sources.
    We scan every token that looks like an absolute path, check whether it
    exists on this machine, and if not search for the same filename inside our
    local gb-recompiled clone to find the correct location.
    """
    import re as _re
    cmake_path = recomp_out / "CMakeLists.txt"
    if not cmake_path.exists():
        return

    content    = cmake_path.read_text()
    repo_root  = gbrecomp_src.resolve()
    changed    = False

    def _fix(m: "re.Match") -> str:
        nonlocal changed
        token = m.group(0)
        # Strip surrounding quotes/parens that may have been swept in
        inner = token.strip("\"'()")
        if Path(inner).exists():
            return token          # already valid — leave alone
        candidates = list(repo_root.rglob(Path(inner).name))
        if candidates:
            changed = True
            # Preserve any leading/trailing quote characters
            prefix = token[: len(token) - len(token.lstrip("\"'()"))]
            suffix = token[len(token.rstrip("\"'()")):]
            return prefix + str(candidates[0]) + suffix
        return token              # couldn't fix — leave alone

    # Match tokens that look like absolute paths (start with /)
    patched = _re.sub(r'["\']?/[^\s"\'()]+["\']?', _fix, content)
    if changed:
        cmake_path.write_text(patched)


def _gb_get_recompiler(work_dir: Path) -> Path:
    """Return path to the gb-recompiled binary, downloading from GitHub if absent."""
    bin_path = work_dir / "gb-recompiled"
    if bin_path.exists():
        return bin_path

    import platform as _platform
    arch = _platform.machine().lower()  # "arm64" or "x86_64"

    req = urllib.request.Request(
        "https://api.github.com/repos/arcanite24/gb-recompiled/releases/latest",
        headers={"User-Agent": "game-port-installer/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            release = json.loads(resp.read())
    except Exception as exc:
        raise RuntimeError(f"Could not fetch gb-recompiled release info: {exc}")

    def _score(name: str) -> int:
        n = name.lower()
        s = 0
        if "mac" in n or "darwin" in n:
            s += 10
        if arch in n:
            s += 5
        if "universal" in n or "arm" in n:
            s += 3
        return s

    assets = release.get("assets", [])
    best = max(assets, key=lambda a: _score(a["name"]), default=None)
    if not best or _score(best["name"]) < 5:
        raise RuntimeError(
            "No macOS gb-recompiled binary found in the latest release.\n"
            "Check https://github.com/arcanite24/gb-recompiled/releases"
        )

    tmp_suffix = Path(best["name"]).suffix or ".bin"
    with tempfile.NamedTemporaryFile(delete=False, suffix=tmp_suffix) as fh:
        tmp_path = Path(fh.name)
    try:
        urllib.request.urlretrieve(best["browser_download_url"], tmp_path)
        name_lower = best["name"].lower()
        if name_lower.endswith(".zip"):
            with zipfile.ZipFile(tmp_path) as zf:
                for member in zf.namelist():
                    if "gb-recompiled" in member.lower() and not member.endswith("/"):
                        bin_path.write_bytes(zf.read(member))
                        break
        elif ".tar" in name_lower or name_lower.endswith((".gz", ".xz")):
            with tarfile.open(tmp_path) as tf:
                for member in tf.getmembers():
                    if "gb-recompiled" in member.name.lower() and member.isfile():
                        fobj = tf.extractfile(member)
                        if fobj:
                            bin_path.write_bytes(fobj.read())
                        break
        else:
            shutil.copy2(tmp_path, bin_path)
    finally:
        tmp_path.unlink(missing_ok=True)

    if not bin_path.exists():
        raise RuntimeError("Failed to extract gb-recompiled binary from download.")
    os.chmod(bin_path, 0o755)
    return bin_path


def gb_step_status(game: dict, os_name: str = "macOS") -> dict[int, str]:
    """
    Return current status of each step: "done" | "pending".
    Steps: 1=Fetch, 2=Assemble, 3=Recompile, 4=Build.
    """
    dest     = game_dir(game, os_name)
    work_dir = dest / "_work"
    variant  = game.get("gb_variant", "red")
    rom_name = "pokered.gbc" if variant == "red" else "pokeblue.gbc"

    statuses = {}
    statuses[1] = (
        "done" if (work_dir / "_step_1_fetched").exists()
                  and (work_dir / "pokered_src").exists()
        else "pending"
    )
    statuses[2] = (
        "done" if (work_dir / "_step_2_assembled").exists()
                  and (work_dir / rom_name).exists()
        else "pending"
    )
    statuses[3] = (
        "done" if (work_dir / "_step_3_recompiled").exists()
                  and (work_dir / "recomp_out").exists()
        else "pending"
    )
    statuses[4] = (
        "done" if (work_dir / "_step_4_built").exists()
                  and (dest / "version.txt").exists()
        else "pending"
    )
    return statuses


def gb_rerun_from(game: dict, from_step: int, os_name: str = "macOS") -> None:
    """Clear step markers from `from_step` onward so the pipeline re-runs them."""
    work_dir = game_dir(game, os_name) / "_work"
    work_dir.mkdir(parents=True, exist_ok=True)
    # Also wipe outputs that belong to the cleared steps so they truly re-run
    variant  = game.get("gb_variant", "red")
    rom_name = "pokered.gbc" if variant == "red" else "pokeblue.gbc"
    for step in range(from_step, 5):
        (work_dir / f"_step_{step}_fetched"   ).unlink(missing_ok=True)
        (work_dir / f"_step_{step}_assembled" ).unlink(missing_ok=True)
        (work_dir / f"_step_{step}_recompiled").unlink(missing_ok=True)
        (work_dir / f"_step_{step}_built"     ).unlink(missing_ok=True)
    # Remove outputs so prerequisite checks don't falsely skip
    if from_step <= 1:
        shutil.rmtree(work_dir / "pokered_src", ignore_errors=True)
    if from_step <= 2:
        (work_dir / rom_name).unlink(missing_ok=True)
    if from_step <= 3:
        shutil.rmtree(work_dir / "recomp_out", ignore_errors=True)


def build_gb_recomp(game: dict, dest: Path,
                    progress_cb=None, step_cb=None) -> None:
    """
    4-step GB Recompiled build pipeline.

    step_cb(step: int, status: str)
        step   = 1..4
        status = "running" | "done" | "error" | "skip"

    Folder cleanup policy
        Step 2 done → delete pokered_src/ (keep assembled ROM)
        Step 4 done → delete recomp_out/ (keep native binary)
    """

    def _cb(pct: int):
        if progress_cb:
            progress_cb(pct)

    def _sc(step: int, status: str):
        if step_cb:
            step_cb(step, status)

    env      = _gb_env()
    work_dir = dest / "_work"
    work_dir.mkdir(parents=True, exist_ok=True)

    variant  = game.get("gb_variant", "red")
    rom_name = "pokered.gbc" if variant == "red" else "pokeblue.gbc"

    # ── Step 1: Fetch source ──────────────────────────────────────────────────
    step1_marker = work_dir / "_step_1_fetched"
    src_dir      = work_dir / "pokered_src"
    if step1_marker.exists() and src_dir.exists():
        _sc(1, "skip")
    else:
        step1_marker.unlink(missing_ok=True)
        _sc(1, "running")
        _cb(5)
        try:
            if src_dir.exists():
                result = subprocess.run(
                    ["git", "-C", str(src_dir), "pull", "--depth=1"],
                    env=env, capture_output=True, text=True,
                )
            else:
                result = subprocess.run(
                    ["git", "clone", "--depth=1",
                     "https://github.com/pret/pokered.git", str(src_dir)],
                    env=env, capture_output=True, text=True,
                )
            if result.returncode != 0:
                raise RuntimeError(
                    f"git failed (exit {result.returncode}):\n"
                    + result.stderr[-2000:]
                )
            hash_r = subprocess.run(
                ["git", "-C", str(src_dir), "rev-parse", "--short", "HEAD"],
                env=env, capture_output=True, text=True,
            )
            commit = hash_r.stdout.strip() or "unknown"
            step1_marker.write_text(commit)
            _sc(1, "done")
            _cb(20)
        except Exception:
            _sc(1, "error")
            raise

    # ── Step 2: Assemble ROM ──────────────────────────────────────────────────
    step2_marker = work_dir / "_step_2_assembled"
    rom_dest     = work_dir / rom_name
    if step2_marker.exists() and rom_dest.exists():
        _sc(2, "skip")
    else:
        step2_marker.unlink(missing_ok=True)
        _sc(2, "running")
        _cb(25)
        try:
            if not src_dir.exists():
                raise RuntimeError("pokered source not found — re-run Step 1.")
            # Ensure RGBDS assembler is available
            if not shutil.which("rgbasm", path=env["PATH"]):
                _cb(27)
                r = subprocess.run(
                    ["brew", "install", "rgbds"],
                    env=env, capture_output=True, text=True,
                )
                if r.returncode != 0 or not shutil.which("rgbasm", path=env["PATH"]):
                    raise RuntimeError(
                        "RGBDS assembler not found.\n"
                        "Install it with:  brew install rgbds"
                    )
            _cb(30)
            result = subprocess.run(
                ["make", f"-j{os.cpu_count() or 1}"],
                cwd=str(src_dir), env=env, capture_output=True, text=True,
            )
            if result.returncode != 0:
                raise RuntimeError(
                    f"make failed (exit {result.returncode}):\n"
                    + (result.stdout + result.stderr)[-3000:]
                )
            rom_src = src_dir / rom_name
            if not rom_src.exists():
                raise RuntimeError(
                    f"Expected ROM '{rom_name}' not produced by make.\n"
                    + (result.stdout + result.stderr)[-1000:]
                )
            shutil.copy2(rom_src, rom_dest)
            _cb(45)
            # ── Cleanup: delete entire source tree (ROM is safely copied out) ──
            shutil.rmtree(src_dir)
            step2_marker.write_text(rom_name)
            _sc(2, "done")
            _cb(50)
        except Exception:
            _sc(2, "error")
            raise

    # ── Step 3: Recompile via GB Recompiled ───────────────────────────────────
    step3_marker = work_dir / "_step_3_recompiled"
    recomp_out   = work_dir / "recomp_out"
    if step3_marker.exists() and recomp_out.exists():
        _sc(3, "skip")
    else:
        step3_marker.unlink(missing_ok=True)
        _sc(3, "running")
        _cb(55)
        try:
            if not rom_dest.exists():
                raise RuntimeError(f"ROM not found: {rom_name} — re-run Step 2.")
            # Download binary + clone source (for runtime files)
            recomp_bin   = _gb_get_recompiler(work_dir)
            gbrecomp_src = _gb_get_source(work_dir)
            _cb(62)
            if recomp_out.exists():
                shutil.rmtree(recomp_out)
            recomp_out.mkdir()
            # Try positional arg first, then --output flag
            for cmd in [
                [str(recomp_bin), str(rom_dest), str(recomp_out)],
                [str(recomp_bin), str(rom_dest), "--output", str(recomp_out)],
            ]:
                result = subprocess.run(
                    cmd, env=env, capture_output=True, text=True,
                )
                if result.returncode == 0:
                    break
            if result.returncode != 0:
                raise RuntimeError(
                    f"gb-recompiled failed (exit {result.returncode}):\n"
                    + (result.stdout + result.stderr)[-3000:]
                )
            if not (recomp_out / "CMakeLists.txt").exists():
                raise RuntimeError(
                    "gb-recompiled produced no CMakeLists.txt.\n"
                    "Output:\n" + (result.stdout + result.stderr)[-1000:]
                )
            # Fix hardcoded absolute runtime paths embedded by the tool
            _gb_patch_cmake(recomp_out, gbrecomp_src)
            step3_marker.write_text("ok")
            _sc(3, "done")
            _cb(75)
        except Exception:
            _sc(3, "error")
            raise

    # ── Step 4: Build native binary ───────────────────────────────────────────
    step4_marker = work_dir / "_step_4_built"
    if step4_marker.exists() and (dest / "version.txt").exists():
        _sc(4, "skip")
    else:
        step4_marker.unlink(missing_ok=True)
        _sc(4, "running")
        _cb(80)
        try:
            if not recomp_out.exists():
                raise RuntimeError("Recompiled C project not found — re-run Step 3.")
            # Ensure cmake + SDL2 available
            subprocess.run(
                ["brew", "install", "cmake", "sdl2"],
                env=env, check=False, capture_output=True,
            )
            cmake_build = recomp_out / "_cmake_build"
            if cmake_build.exists():
                shutil.rmtree(cmake_build)
            cmake_build.mkdir()
            _cb(84)
            result = subprocess.run(
                ["cmake", str(recomp_out), "-DCMAKE_BUILD_TYPE=Release"],
                cwd=str(cmake_build), env=env, capture_output=True, text=True,
            )
            if result.returncode != 0:
                raise RuntimeError(
                    f"cmake configure failed:\n"
                    + (result.stdout + result.stderr)[-3000:]
                )
            _cb(90)
            result = subprocess.run(
                ["cmake", "--build", ".", "--parallel", str(os.cpu_count() or 1)],
                cwd=str(cmake_build), env=env, capture_output=True, text=True,
            )
            if result.returncode != 0:
                raise RuntimeError(
                    f"cmake build failed:\n"
                    + (result.stdout + result.stderr)[-3000:]
                )
            # Move the binary to dest
            moved = False
            for candidate in sorted(cmake_build.rglob("*")):
                if (candidate.is_file()
                        and candidate.stat().st_mode & 0o111
                        and candidate.suffix not in
                            {".cmake", ".h", ".cpp", ".c", ".so", ".dylib", ".a"}
                        and not candidate.name.startswith(".")):
                    target = dest / candidate.name
                    if target.exists():
                        target.unlink()
                    shutil.copy2(candidate, dest)
                    os.chmod(dest / candidate.name, 0o755)
                    moved = True
                    break
            if not moved:
                raise RuntimeError("No executable found in cmake build output.")
            _cb(97)
            # ── Cleanup: delete generated C source + cmake build dir ─────────
            shutil.rmtree(recomp_out)
            # Write version from pokered commit hash
            commit = step1_marker.read_text().strip() if step1_marker.exists() else "1.0"
            (dest / "version.txt").write_text(commit)
            step4_marker.write_text("ok")
            _sc(4, "done")
            _cb(100)
        except Exception:
            _sc(4, "error")
            raise


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


def launch_game(game: dict, os_name: str) -> subprocess.Popen:
    """Launch the game and return the Popen object for process tracking.

    For .app bundles we use plain `open` (not -W) because macOS apps often
    remain running in the dock after their window closes, which would cause
    `open -W` to block indefinitely and make the Run button stay disabled.
    For bare binaries we spawn directly so we can track the process properly.
    """
    d = game_dir(game, os_name)
    launch_subdir = game.get("launch_subdir")
    run_dir = d / launch_subdir if launch_subdir else d
    kind, target = _find_launchable(run_dir)
    if kind is None:
        raise FileNotFoundError(f"No launchable found in {run_dir}")
    extra_args = game.get("launch_args", [])
    if kind == "app":
        return subprocess.Popen(["open", str(target)] + extra_args)
    else:
        return subprocess.Popen([str(target)] + extra_args, cwd=str(run_dir))


# ── Finder ────────────────────────────────────────────────────────────────────

def reveal_in_finder(path: Path) -> None:
    """Select the item in Finder, or open its parent if it's a directory."""
    if path.is_dir():
        subprocess.run(["open", str(path)], check=False)
    else:
        subprocess.run(["open", "-R", str(path)], check=False)
