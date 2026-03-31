#!/usr/bin/env python3
"""
macOS game port launcher — PySide6.
Double-click a game to install, update, or launch.
"""

import hashlib
import shutil
import subprocess
import sys
import tempfile
import zipfile
from collections import defaultdict
from pathlib import Path

from PySide6.QtCore import Qt, QObject, QThread, QTimer, Signal, QEvent, QUrl
from PySide6.QtGui import QColor, QAction, QFont, QIcon, QPainter, QPixmap, QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QComboBox, QPushButton,
    QTreeWidget, QTreeWidgetItem, QHeaderView, QAbstractItemView,
    QDialog, QProgressBar, QFormLayout, QGridLayout,
    QMessageBox, QSizePolicy, QMenu, QCheckBox, QFileDialog,
)

import installer
import settings as app_settings
from games import GAMES

try:
    import zsnes_theme as zsnes_theme
except ImportError:
    zsnes_theme = None

# ── Constants ──────────────────────────────────────────────────────────────────

STATUS_NOT_INSTALLED = "—  Not Installed"

COLOR_INSTALLED = QColor("#00e676")
COLOR_UPDATE    = QColor("#b87000")
COLOR_NONE      = QColor("#888888")


# ── Background workers ─────────────────────────────────────────────────────────

class InstallWorker(QObject):
    progress = Signal(int)
    finished = Signal(str)
    error    = Signal(str)

    def __init__(self, game, release, asset):
        super().__init__()
        self.game    = game
        self.release = release
        self.asset   = asset

    def run(self):
        try:
            tag = installer.install_game(
                self.game, self.release, self.asset, "macOS",
                progress_cb=self.progress.emit,
            )
            self.finished.emit(tag)
        except Exception as e:
            self.error.emit(str(e))


class ReleaseWorker(QObject):
    finished = Signal(object)

    def __init__(self, game):
        super().__init__()
        self.game = game

    def run(self):
        self.finished.emit(installer.fetch_latest_release(self.game))


class AllReleasesWorker(QObject):
    """Fetches latest releases for every game sequentially, emitting per-game."""
    game_checked = Signal(str, object)   # folder, release (or None)
    finished     = Signal()

    def run(self):
        disk_cache = installer._load_cache()
        cache_updates = {}
        for game in GAMES:
            if game.get("build_type") == "gb_recomp":
                continue
            try:
                release = installer.get_scraper(game).fetch_latest_release(game)
            except Exception:
                release = None
            if release:
                cache_updates[game["folder"]] = release
            else:
                release = disk_cache.get(game["folder"])
            self.game_checked.emit(game["folder"], release)
        if cache_updates:
            installer._save_cache(cache_updates)
        self.finished.emit()


class GBRecompWorker(QObject):
    """Runs installer.build_gb_recomp() in a background thread."""
    progress = Signal(int)
    step     = Signal(int, str)   # step_num, status
    finished = Signal()
    error    = Signal(str)

    def __init__(self, game, from_step: int = 1):
        super().__init__()
        self.game      = game
        self.from_step = from_step

    def run(self):
        try:
            dest = installer.game_dir(self.game, "macOS")
            dest.mkdir(parents=True, exist_ok=True)
            if self.from_step > 1:
                installer.gb_rerun_from(self.game, self.from_step)
            installer.build_gb_recomp(
                self.game, dest,
                progress_cb=self.progress.emit,
                step_cb=self.step.emit,
            )
            self.finished.emit()
        except Exception as exc:
            self.error.emit(str(exc))


# ── Archive / ROM helpers ──────────────────────────────────────────────────────

_ARCHIVE_EXTS = {".zip", ".7z", ".rar"}
_COMMON_ROM_EXTS = {".z64", ".n64", ".v64", ".sfc", ".smc", ".gba", ".gb", ".gbc", ".nes",
                    ".iso", ".bin", ".rom", ".nds", ".gbs"}


def _extract_archive_to_dir(archive_path: str) -> Path:
    """Extract *archive_path* to a fresh temp directory and return its Path.

    Caller is responsible for deleting the directory when finished.
    Raises RuntimeError with a user-readable message on failure.
    """
    suffix = Path(archive_path).suffix.lower()
    tmp    = Path(tempfile.mkdtemp(prefix="gpi_arc_"))
    try:
        if suffix == ".zip":
            with zipfile.ZipFile(archive_path) as z:
                z.extractall(tmp)

        elif suffix == ".7z":
            try:
                import py7zr  # noqa: PLC0415
            except ImportError:
                raise RuntimeError(
                    "py7zr is required to open .7z archives.\n"
                    "Install it with:  pip install py7zr"
                )
            with py7zr.SevenZipFile(archive_path, mode="r") as z:
                z.extractall(tmp)

        elif suffix == ".rar":
            rar_tool = shutil.which("unar") or shutil.which("unrar")
            if not rar_tool:
                raise RuntimeError(
                    "No RAR extraction tool found.\n"
                    "Install one with:  brew install unar"
                )
            if Path(rar_tool).name == "unar":
                cmd = [rar_tool, archive_path, "-o", str(tmp), "-force-overwrite"]
            else:
                cmd = [rar_tool, "x", "-o+", archive_path, str(tmp) + "/"]
            result = subprocess.run(cmd, capture_output=True)
            if result.returncode != 0:
                raise RuntimeError(
                    f"RAR extraction failed:\n{result.stderr.decode(errors='replace')}"
                )

        else:
            raise RuntimeError(f"Unsupported archive format: {suffix}")

    except RuntimeError:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    except Exception as exc:
        shutil.rmtree(tmp, ignore_errors=True)
        raise RuntimeError(f"Could not extract archive:\n{exc}") from exc

    return tmp


def _extract_rom_from_archive(archive_path: str, expected_rom_name: str) -> tuple[str, str]:
    """Extract *archive_path* and return (best_rom_path, tmp_dir).

    Searches the extracted contents for a file whose extension matches
    *expected_rom_name*.  Falls back to any known ROM extension, then picks
    the largest file among multiple candidates.  Caller is responsible for
    deleting *tmp_dir* when finished.

    Raises RuntimeError with a user-readable message on failure.
    """
    tmp = _extract_archive_to_dir(archive_path)

    expected_ext = Path(expected_rom_name).suffix.lower()
    candidates: list[Path] = list(tmp.rglob(f"*{expected_ext}"))
    if not candidates:
        for ext in _COMMON_ROM_EXTS - {expected_ext}:
            candidates.extend(tmp.rglob(f"*{ext}"))

    if not candidates:
        shutil.rmtree(tmp, ignore_errors=True)
        raise RuntimeError(
            f"No ROM file found inside the archive.\n"
            f"Expected a {expected_ext.lstrip('.')} file."
        )

    # Pick the largest file — ROMs are almost always the biggest entry in an archive
    return str(max(candidates, key=lambda p: p.stat().st_size)), str(tmp)


# ── Game dialog ────────────────────────────────────────────────────────────────

class GameDialog(QDialog):
    status_changed = Signal(dict)
    _running: "dict[str, subprocess.Popen]" = {}   # folder → Popen

    def __init__(self, parent, game: dict):
        super().__init__(parent)
        self.game    = game
        self.release = None
        self.selected_asset = None
        self._asset_map     = {}
        self._thread        = None
        self._worker        = None

        self.setWindowTitle(game["name"])
        self.setMinimumWidth(540)
        self._build_ui()
        self._load_release()

        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(500)
        self._poll_timer.timeout.connect(self._poll_running)
        self._poll_timer.start()
        self.finished.connect(self._poll_timer.stop)

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(8)
        root.setContentsMargins(20, 16, 20, 16)

        # Title + repo
        title = QLabel(self.game["name"])
        f = title.font(); f.setPointSize(15); f.setBold(True); title.setFont(f)
        title.setWordWrap(True)
        root.addWidget(title)

        repo = self.game.get("repo")
        repo_label = QLabel(f"github.com/{repo}" if repo else self.game.get("scraper_url", ""))
        repo_label.setStyleSheet("color: #a0a0c0;")
        root.addWidget(repo_label)

        line = QWidget(); line.setFixedHeight(1)
        line.setStyleSheet("background: #4040b0;")
        root.addWidget(line)

        # Info form
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.DontWrapRows)
        form.setLabelAlignment(Qt.AlignRight)
        form.setSpacing(4)
        self.game_title_label = QLabel(self.game.get("game_title", "—"))
        self.type_label       = QLabel(self.game.get("type", "—"))
        self.status_label     = QLabel("Loading…")
        self.installed_label  = QLabel("—")
        self.latest_label     = QLabel("—")
        form.addRow("Game:",      self.game_title_label)
        form.addRow("Type:",      self.type_label)
        form.addRow("Status:",    self.status_label)
        form.addRow("Installed:", self.installed_label)
        form.addRow("Latest:",    self.latest_label)
        root.addLayout(form)

        # Asset picker (shown only when multiple assets)
        self.asset_row = QWidget()
        asset_layout   = QHBoxLayout(self.asset_row)
        asset_layout.setContentsMargins(0, 0, 0, 0)
        asset_layout.addWidget(QLabel("Asset:"))
        self.asset_combo = QComboBox()
        self.asset_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.asset_combo.currentTextChanged.connect(self._on_asset_changed)
        asset_layout.addWidget(self.asset_combo)
        self.asset_row.hide()
        root.addWidget(self.asset_row)

        # Progress
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        root.addWidget(self.progress_bar)

        self.progress_label = QLabel("")
        self.progress_label.setStyleSheet("color: #a0a0c0;")
        root.addWidget(self.progress_label)

        # Buttons  (order: Run · Configure? · Install · Browse Folder · Uninstall · Close)
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self.run_btn = QPushButton("RUN")
        self.run_btn.setEnabled(False)
        self.run_btn.setProperty("class", "primary")
        self.run_btn.clicked.connect(self._do_run)

        self.config_btn = QPushButton("CONFIGURE")
        self.config_btn.setVisible(bool(self.game.get("has_config")))
        self.config_btn.clicked.connect(self._do_configure)

        self.install_btn = QPushButton("INSTALL")
        self.install_btn.setEnabled(False)
        self.install_btn.clicked.connect(self._do_install)

        self.folder_btn = QPushButton("BROWSE FOLDER")
        self.folder_btn.setEnabled(False)
        self.folder_btn.clicked.connect(self._do_browse)

        self.uninstall_btn = QPushButton("UNINSTALL")
        self.uninstall_btn.setEnabled(False)
        self.uninstall_btn.setProperty("class", "danger")
        self.uninstall_btn.clicked.connect(self._do_uninstall)

        close_btn = QPushButton("CLOSE")
        close_btn.clicked.connect(self.accept)

        btn_row.addWidget(self.run_btn)
        btn_row.addWidget(self.config_btn)
        btn_row.addWidget(self.install_btn)
        btn_row.addWidget(self.folder_btn)
        btn_row.addWidget(self.uninstall_btn)
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        root.addLayout(btn_row)

        self.adjustSize()

    # ── Data loading ───────────────────────────────────────────────────────────

    def _load_release(self):
        # Apply installed state immediately — don't wait for network
        self._refresh_installed_buttons()
        self.status_label.setText("Fetching release info…")
        self._rel_thread = QThread(self)
        self._rel_worker = ReleaseWorker(self.game)
        self._rel_worker.moveToThread(self._rel_thread)
        self._rel_thread.started.connect(self._rel_worker.run)
        self._rel_worker.finished.connect(self._apply_release)
        self._rel_worker.finished.connect(self._rel_thread.quit)
        self._rel_thread.start()

    def _refresh_installed_buttons(self):
        """Enable Run/Uninstall/Browse/Configure based solely on local install state."""
        iv        = installer.installed_version(self.game, "macOS")
        installed = installer.game_dir(self.game, "macOS").exists()
        self.installed_label.setText(iv or "—")
        running   = self._is_running()
        self.run_btn.setEnabled(iv is not None and not running)
        self.uninstall_btn.setEnabled(iv is not None)
        self.folder_btn.setEnabled(installed)
        self.config_btn.setEnabled(iv is not None)

    def _is_running(self) -> bool:
        """Return True if this game's process is currently alive."""
        folder = self.game["folder"]
        proc = GameDialog._running.get(folder)
        if proc is None:
            return False
        if proc.poll() is not None:
            del GameDialog._running[folder]
            return False
        return True

    def _poll_running(self):
        """Called every 500 ms — re-enable Run once the game process exits."""
        if self.run_btn.isEnabled():
            return
        if not self._is_running():
            iv = installer.installed_version(self.game, "macOS")
            self.run_btn.setEnabled(iv is not None)

    def _apply_release(self, release):
        iv = installer.installed_version(self.game, "macOS")

        if release is None:
            self.status_label.setText(STATUS_NOT_INSTALLED if iv is None else f"✓  {iv} (offline)")
            return

        self.release = release
        tag = release.get("tag_name", "?")
        self.latest_label.setText(tag)

        assets = installer.assets_for_os(release, "macOS", self.game)
        if not assets:
            self.status_label.setText("No macOS assets found")
            return

        self._asset_map     = {a["name"]: a for a in assets}
        self.selected_asset = installer.pick_asset(release, "macOS", self.game)

        if len(assets) > 1:
            self.asset_combo.blockSignals(True)
            self.asset_combo.clear()
            self.asset_combo.addItems([a["name"] for a in assets])
            if self.selected_asset:
                self.asset_combo.setCurrentText(self.selected_asset["name"])
            self.asset_combo.blockSignals(False)
            self.asset_row.show()
            self.adjustSize()

        self.installed_label.setText(iv or "—")

        if iv is None:
            self.status_label.setText(STATUS_NOT_INSTALLED)
            self.install_btn.setText("Install")
        elif iv == tag:
            self.status_label.setText("✓  Up to date")
            self.install_btn.setText("Reinstall")
        else:
            self.status_label.setText(f"↑  Update available  ({iv} → {tag})")
            self.install_btn.setText("Update")

        installed = installer.game_dir(self.game, "macOS").exists()
        self.install_btn.setEnabled(True)
        self.run_btn.setEnabled(iv is not None and not self._is_running())
        self.uninstall_btn.setEnabled(iv is not None)
        self.folder_btn.setEnabled(installed)
        self.config_btn.setEnabled(iv is not None)

    def _on_asset_changed(self, name: str):
        self.selected_asset = self._asset_map.get(name)

    # ── Actions ────────────────────────────────────────────────────────────────

    def _do_install(self):
        if not self.selected_asset:
            QMessageBox.warning(self, "No asset", "No asset selected.")
            return

        self.install_btn.setEnabled(False)
        self.run_btn.setEnabled(False)
        self.uninstall_btn.setEnabled(False)
        self.progress_bar.setValue(0)
        self.progress_label.setText("Starting download…")

        self._thread = QThread(self)
        self._worker = InstallWorker(self.game, self.release, self.selected_asset)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._update_progress)
        self._worker.finished.connect(self._install_done)
        self._worker.finished.connect(self._thread.quit)
        self._worker.error.connect(self._install_error)
        self._worker.error.connect(self._thread.quit)
        self._thread.start()

    def _update_progress(self, pct: int):
        self.progress_bar.setValue(pct)
        if pct < 70:
            self.progress_label.setText(f"Downloading… {pct}%")
        elif pct < 80:
            self.progress_label.setText("Extracting…")
        elif pct < 90:
            self.progress_label.setText("Installing dependencies…")
        elif pct < 100:
            self.progress_label.setText("Compiling…")
        else:
            self.progress_label.setText("Done.")

    def _install_done(self, tag: str):
        iv = installer.installed_version(self.game, "macOS")
        self.installed_label.setText(iv or tag)
        self.status_label.setText("✓  Up to date")
        self.install_btn.setText("Reinstall")
        self.install_btn.setEnabled(True)
        self.run_btn.setEnabled(True)
        self.uninstall_btn.setEnabled(True)
        self.folder_btn.setEnabled(True)
        self.progress_label.setText("Installed successfully.")
        self.status_changed.emit(self.game)

    def _install_error(self, msg: str):
        self.progress_bar.setValue(0)
        self.progress_label.setText("Error.")
        self.install_btn.setEnabled(True)
        QMessageBox.critical(self, "Install failed", msg)

    def _do_run(self):
        game_path = installer.game_dir(self.game, "macOS")

        # Drop portable.txt before anything else so the game stores config/ROM
        # in the game folder rather than ~/Library/Application Support
        portable_file = self.game.get("portable_file")
        if portable_file:
            pf = game_path / portable_file
            if not pf.exists():
                pf.touch()

        # ── Multi-disc games (e.g. PS1 titles) ───────────────────────────────
        requires_discs = self.game.get("requires_discs", 0)
        if requires_discs:
            disc_subdir = self.game.get("disc_dest_subdir", "isos")
            disc_dir    = game_path / disc_subdir
            disc_dir.mkdir(parents=True, exist_ok=True)
            _DISC_EXTS  = {".iso", ".bin", ".img"}

            def _count_discs():
                return sum(1 for f in disc_dir.iterdir() if f.suffix.lower() in _DISC_EXTS)

            if _count_discs() < requires_discs:
                found = _count_discs()
                QMessageBox.information(
                    self, "Disc Images Required",
                    f"{self.game['name']} requires {requires_discs} disc images "
                    f"({'ISO or BIN' }).\n"
                    + (f"Found {found} already in the isos/ folder.\n\n" if found else "\n")
                    + "Select all disc image files (or archives containing them) "
                    "in the next dialog — you can pick multiple files at once.\n\n"
                    "The game auto-detects which disc is which.",
                )

                while _count_discs() < requires_discs:
                    paths, _ = QFileDialog.getOpenFileNames(
                        self,
                        f"{self.game['name']} — Select Disc Images "
                        f"({_count_discs()}/{requires_discs} found)",
                        str(Path.home()),
                        "Disc Images & Archives (*.iso *.bin *.img *.zip *.7z *.rar);;"
                        "All files (*)",
                    )
                    if not paths:
                        return

                    tmp_dirs: list[str] = []
                    try:
                        self.progress_label.setText("Copying disc images…")
                        QApplication.processEvents()

                        for path in paths:
                            if Path(path).suffix.lower() in _ARCHIVE_EXTS:
                                self.progress_label.setText("Extracting archive…")
                                QApplication.processEvents()
                                tmp = _extract_archive_to_dir(path)
                                tmp_dirs.append(str(tmp))
                                for disc_file in tmp.rglob("*"):
                                    if disc_file.is_file() and disc_file.suffix.lower() in _DISC_EXTS:
                                        shutil.copy2(disc_file, disc_dir / disc_file.name)
                            else:
                                shutil.copy2(path, disc_dir / Path(path).name)

                    except Exception as exc:
                        import traceback
                        self.progress_label.setText("")
                        QMessageBox.critical(self, "Disc Copy Error",
                                             f"{exc}\n\n{traceback.format_exc()}")
                        continue
                    finally:
                        for td in tmp_dirs:
                            shutil.rmtree(td, ignore_errors=True)
                        self.progress_label.setText("")

                    if _count_discs() < requires_discs:
                        btn = QMessageBox.warning(
                            self, "Not Enough Discs",
                            f"Only {_count_discs()} of {requires_discs} disc images found.\n\n"
                            "Would you like to select more files?",
                            QMessageBox.Yes | QMessageBox.No,
                        )
                        if btn != QMessageBox.Yes:
                            return

        rom_name  = self.game.get("requires_rom")

        if rom_name:
            rom_subdir    = self.game.get("rom_dest_subdir")
            rom_dest      = game_path / rom_subdir / rom_name if rom_subdir else game_path / rom_name
            # Support single checksum (rom_checksum) or multiple (rom_checksums)
            _ck_type      = self.game.get("rom_checksum_type", "sha256").lower()
            _single       = self.game.get("rom_checksum", "")
            valid_hashes  = [h.lower() for h in self.game.get("rom_checksums", [_single] if _single else [])]
            assets_marker = self.game.get("assets_marker")   # file that proves extraction is done
            assets_done   = (game_path / assets_marker).exists() if assets_marker else False

            # ── 1. Make sure we have the correct ROM on disk ──────────────────
            def _digest(p):
                if _ck_type == "xxh3_64":
                    try:
                        import xxhash  # noqa: PLC0415
                    except ImportError:
                        raise RuntimeError(
                            "xxhash is required to verify this ROM.\n"
                            "Install it with:  pip install xxhash"
                        )
                    h = xxhash.xxh3_64()
                else:
                    h = hashlib.new(_ck_type)
                with open(p, "rb") as f:
                    for chunk in iter(lambda: f.read(1 << 20), b""):
                        h.update(chunk)
                return h.hexdigest()

            rom_ok = rom_dest.exists() and (
                not valid_hashes or _digest(rom_dest).lower() in valid_hashes
            )

            if not rom_ok:
                requires_extraction = self.game.get("requires_asset_extraction")
                msg = (
                    f"{self.game['name']} requires an original ROM to extract game assets.\n\n"
                    f"Please locate your copy of {rom_name} in the next dialog."
                    if requires_extraction else
                    f"{self.game['name']} requires an original ROM file ({rom_name}) to run.\n\n"
                    f"Please locate your copy in the next dialog."
                )
                QMessageBox.information(self, "ROM Required", msg)
                rom_ext   = Path(rom_name).suffix          # e.g. ".z64"
                file_filter = (
                    f"ROM & Archives (*{rom_ext} *.zip *.7z *.rar);;"
                    f"All files (*)"
                )
                while True:
                    path, _ = QFileDialog.getOpenFileName(
                        self,
                        f"{self.game['name']} — Locate ROM ({rom_name})",
                        str(Path.home()),
                        file_filter,
                    )
                    if not path:
                        return

                    tmp_dir = None
                    try:
                        # ── Decompress archive if needed ──────────────────────
                        if Path(path).suffix.lower() in _ARCHIVE_EXTS:
                            self.progress_label.setText("Extracting archive…")
                            QApplication.processEvents()
                            path, tmp_dir = _extract_rom_from_archive(path, rom_name)

                        # ── Validate magic bytes ──────────────────────────────
                        magic_spec = self.game.get("rom_validation_magic")
                        if magic_spec:
                            offset   = magic_spec.get("offset", 0)
                            expected = bytes.fromhex(magic_spec["hex"])
                            with open(path, "rb") as _f:
                                _f.seek(offset)
                                actual_bytes = _f.read(len(expected))
                            if actual_bytes != expected:
                                if tmp_dir:
                                    shutil.rmtree(tmp_dir, ignore_errors=True)
                                    tmp_dir = None
                                desc = self.game.get("rom_description", rom_name)
                                btn = QMessageBox.warning(
                                    self, "Wrong File",
                                    f"This doesn't look like the right disc image.\n\n"
                                    f"Expected:  {desc}\n\n"
                                    f"Would you like to select a different file?",
                                    QMessageBox.Yes | QMessageBox.No,
                                )
                                if btn == QMessageBox.Yes:
                                    continue
                                return

                        # ── Validate checksum ─────────────────────────────────
                        if valid_hashes:
                            self.progress_label.setText("Verifying ROM…")
                            QApplication.processEvents()
                            actual = _digest(path)
                            self.progress_label.setText("")
                            if actual.lower() not in valid_hashes:
                                if tmp_dir:
                                    shutil.rmtree(tmp_dir, ignore_errors=True)
                                    tmp_dir = None
                                expected_str = "\n".join(valid_hashes)
                                btn = QMessageBox.warning(
                                    self, "Wrong ROM",
                                    f"This doesn't appear to be a supported version of the ROM.\n\n"
                                    f"Accepted {_ck_type.upper()} checksum(s):\n{expected_str}\n\n"
                                    f"Got:\n{actual}\n\n"
                                    f"Would you like to select a different file?",
                                    QMessageBox.Yes | QMessageBox.No,
                                )
                                if btn == QMessageBox.Yes:
                                    continue
                                return

                        # ── Copy ROM to destination ───────────────────────────
                        rom_dest.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(path, rom_dest)
                        rom_ok = True
                        assets_done = False   # force re-extraction with new ROM

                    except Exception as exc:
                        import traceback
                        self.progress_label.setText("")
                        QMessageBox.critical(
                            self, "ROM Error",
                            f"{exc}\n\n{traceback.format_exc()}",
                        )
                        continue
                    finally:
                        if tmp_dir:
                            shutil.rmtree(tmp_dir, ignore_errors=True)
                        self.progress_label.setText("")

                    break

            # ── 2. Run asset extraction if needed ─────────────────────────────
            if rom_ok and not assets_done and self.game.get("requires_asset_extraction"):
                self.progress_label.setText("Extracting assets…")
                self.progress_bar.setValue(50)
                QApplication.processEvents()
                try:
                    subprocess.run(
                        ["python3", "assets/restool.py", "--extract-from-rom"],
                        cwd=str(game_path), check=True,
                    )
                    self.progress_bar.setValue(100)
                    self.progress_label.setText("Assets extracted.")
                    QApplication.processEvents()
                except subprocess.CalledProcessError as e:
                    self.progress_bar.setValue(0)
                    self.progress_label.setText("")
                    QMessageBox.critical(self, "Asset extraction failed", str(e))
                    return

        # ── 3. Launch ─────────────────────────────────────────────────────────
        self.progress_bar.setValue(0)
        self.progress_label.setText("")
        try:
            proc = installer.launch_game(self.game, "macOS")
            GameDialog._running[self.game["folder"]] = proc
            self.run_btn.setEnabled(False)
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Launch failed", str(e))


    def _do_uninstall(self):
        if QMessageBox.question(
            self, "Uninstall",
            f"Remove {self.game['name']}?",
            QMessageBox.Yes | QMessageBox.No,
        ) != QMessageBox.Yes:
            return
        try:
            installer.uninstall_game(self.game, "macOS")
        except Exception as e:
            QMessageBox.critical(self, "Uninstall failed", str(e))
            return
        self.installed_label.setText("—")
        self.status_label.setText(STATUS_NOT_INSTALLED)
        self.install_btn.setText("Install")
        self.run_btn.setEnabled(False)
        self.uninstall_btn.setEnabled(False)
        self.folder_btn.setEnabled(False)
        self.progress_bar.setValue(0)
        self.progress_label.setText("")
        self.status_changed.emit(self.game)

    def _do_browse(self):
        installer.reveal_in_finder(installer.game_dir(self.game, "macOS"))

    def _do_configure(self):
        import importlib, traceback
        try:
            folder = self.game["folder"].lower()
            mod = importlib.import_module(f"configs.{folder}")
            self._config_win = mod.ConfigWindow()
            self._config_win.show()
            self._config_win.raise_()
            self._config_win.activateWindow()
        except Exception as exc:
            QMessageBox.critical(self, "Config Error",
                                 f"{exc}\n\n{traceback.format_exc()}")


# ── Background image filter ────────────────────────────────────────────────────

class _BgFilter(QObject):
    """Paints a pixmap cover-scaled and centred on a viewport."""
    def __init__(self, path: Path, tree):
        super().__init__()
        self._px   = QPixmap(str(path))
        self._tree = tree

    def _items_bottom(self) -> int:
        """Return the y-coordinate of the bottom edge of the last visible item."""
        root   = self._tree.invisibleRootItem()
        bottom = 0

        def walk(item):
            nonlocal bottom
            r = self._tree.visualItemRect(item)
            if r.isValid():
                bottom = max(bottom, r.bottom())
            if item.isExpanded():
                for i in range(item.childCount()):
                    walk(item.child(i))

        for i in range(root.childCount()):
            walk(root.child(i))
        return bottom

    def eventFilter(self, vp, event):
        if event.type() == QEvent.Type.Paint and not self._px.isNull():
            p = QPainter(vp)
            scaled = self._px.scaled(vp.width(), vp.height(),
                                     Qt.KeepAspectRatioByExpanding,
                                     Qt.SmoothTransformation)
            x = (vp.width()  - scaled.width())  // 2
            y = (vp.height() - scaled.height()) // 2
            p.drawPixmap(x, y, scaled)
            # Cover the entire viewport with a near-opaque navy tint so the
            # image reads as a very subtle atmospheric backdrop rather than
            # dominating the list (ZSNES theme: dark navy over full height).
            p.fillRect(0, 0, vp.width(), vp.height(), QColor(20, 20, 90, 225))
            p.end()
        return False  # let Qt paint items on top


# ── GB Recompiled dialog ───────────────────────────────────────────────────────

_GB_STEP_NAMES = {
    1: "Fetch Source",
    2: "Assemble ROM",
    3: "Recompile",
    4: "Build Native",
}
_GB_STEP_ICONS = {"pending": "⏳", "running": "🔄", "done": "✔",
                  "skip": "✔", "error": "✖"}

_RED_BTN_ON  = ("background:#8b0000; color:#ffffff; border:2px solid #ff4444;"
                "border-radius:4px; padding:6px 18px; font-weight:bold;")
_RED_BTN_OFF = ("background:#3a1010; color:#aa6666; border:2px solid #5a2020;"
                "border-radius:4px; padding:6px 18px;")
_BLU_BTN_ON  = ("background:#003080; color:#ffffff; border:2px solid #4488ff;"
                "border-radius:4px; padding:6px 18px; font-weight:bold;")
_BLU_BTN_OFF = ("background:#101a3a; color:#6677aa; border:2px solid #1a2a5a;"
                "border-radius:4px; padding:6px 18px;")


class GBRecompDialog(QDialog):
    status_changed = Signal(dict)
    _running: "dict[str, subprocess.Popen]" = {}

    def __init__(self, parent, game: dict):
        super().__init__(parent)
        self.game    = game
        self._thread = None
        self._worker = None
        # Load saved variant (default red)
        self._variant = app_settings.get("pokemon_variant") or "red"

        self.setWindowTitle(game["name"])
        self.setMinimumWidth(520)
        self._build_ui()
        self._apply_variant_style()
        self._refresh_steps()

        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(500)
        self._poll_timer.timeout.connect(self._poll_running)
        self._poll_timer.start()
        self.finished.connect(self._poll_timer.stop)

    # ── UI ─────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.setContentsMargins(20, 16, 20, 16)

        # Title
        title = QLabel("Pokemon Red / Blue")
        f = title.font(); f.setPointSize(15); f.setBold(True); title.setFont(f)
        root.addWidget(title)

        sub = QLabel("pret/pokered  \u203a  GB Recompiled  \u203a  native binary")
        sub.setStyleSheet("color:#a0a0c0;")
        root.addWidget(sub)

        sep = QWidget(); sep.setFixedHeight(1)
        sep.setStyleSheet("background:#4040b0;")
        root.addWidget(sep)

        # ── Variant toggle ────────────────────────────────────────────────────
        var_row = QHBoxLayout()
        var_row.setSpacing(10)
        self._red_btn = QPushButton("RED VERSION")
        self._blu_btn = QPushButton("BLUE VERSION")
        self._red_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._blu_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._red_btn.clicked.connect(lambda: self._select_variant("red"))
        self._blu_btn.clicked.connect(lambda: self._select_variant("blue"))
        var_row.addWidget(self._red_btn)
        var_row.addWidget(self._blu_btn)
        var_row.addStretch()
        root.addLayout(var_row)

        sep2 = QWidget(); sep2.setFixedHeight(1)
        sep2.setStyleSheet("background:#333360;")
        root.addWidget(sep2)

        # ── Step rows ─────────────────────────────────────────────────────────
        self._step_icons:  dict[int, QLabel]       = {}
        self._step_labels: dict[int, QLabel]       = {}
        self._step_btns:   dict[int, QPushButton]  = {}

        grid = QGridLayout()
        grid.setSpacing(5)
        grid.setColumnMinimumWidth(0, 26)
        grid.setColumnStretch(1, 1)

        for step, name in _GB_STEP_NAMES.items():
            icon  = QLabel("⏳"); icon.setFixedWidth(22)
            label = QLabel(f"  {step}.  {name}")
            label.setStyleSheet("color:#cccccc;")
            btn   = QPushButton("↺"); btn.setFixedWidth(30)
            btn.setToolTip(f"Re-run from step {step}")
            btn.clicked.connect(lambda _=False, s=step: self._run_from(s))
            grid.addWidget(icon,  step - 1, 0)
            grid.addWidget(label, step - 1, 1)
            grid.addWidget(btn,   step - 1, 2)
            self._step_icons[step]  = icon
            self._step_labels[step] = label
            self._step_btns[step]   = btn

        root.addLayout(grid)

        # Progress
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        root.addWidget(self.progress_bar)

        self.progress_label = QLabel("")
        self.progress_label.setStyleSheet("color:#a0a0c0;")
        root.addWidget(self.progress_label)

        # ── Bottom buttons ────────────────────────────────────────────────────
        btn_row = QHBoxLayout(); btn_row.setSpacing(8)

        self.run_btn = QPushButton("▶  RUN")
        self.run_btn.setEnabled(False)
        self.run_btn.setProperty("class", "primary")
        self.run_btn.clicked.connect(self._do_run)

        self.build_btn = QPushButton("⚙  BUILD && COMPILE")
        self.build_btn.setProperty("class", "primary")
        self.build_btn.clicked.connect(lambda: self._run_from(1))

        self.folder_btn = QPushButton("BROWSE FOLDER")
        self.folder_btn.setEnabled(False)
        self.folder_btn.clicked.connect(self._do_browse)

        self.uninstall_btn = QPushButton("UNINSTALL")
        self.uninstall_btn.setEnabled(False)
        self.uninstall_btn.setProperty("class", "danger")
        self.uninstall_btn.clicked.connect(self._do_uninstall)

        close_btn = QPushButton("CLOSE")
        close_btn.clicked.connect(self.accept)

        btn_row.addWidget(self.run_btn)
        btn_row.addWidget(self.build_btn)
        btn_row.addWidget(self.folder_btn)
        btn_row.addWidget(self.uninstall_btn)
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        root.addLayout(btn_row)
        self.adjustSize()

    # ── Variant selection ──────────────────────────────────────────────────────

    def _select_variant(self, variant: str):
        if variant == self._variant:
            return
        self._variant = variant
        app_settings.set_value("pokemon_variant", variant)
        self._apply_variant_style()
        label = "Red Version" if variant == "red" else "Blue Version"
        self.progress_label.setText(f"Selected {label} — press RUN to play.")

    def _apply_variant_style(self):
        if self._variant == "red":
            self._red_btn.setStyleSheet(_RED_BTN_ON)
            self._blu_btn.setStyleSheet(_BLU_BTN_OFF)
        else:
            self._red_btn.setStyleSheet(_RED_BTN_OFF)
            self._blu_btn.setStyleSheet(_BLU_BTN_ON)

    def _game_with_variant(self) -> dict:
        """Return game dict with variant and the correct launch_binary set."""
        stem = "pokered" if self._variant == "red" else "pokeblue"
        return {**self.game, "gb_variant": self._variant, "launch_binary": stem}

    # ── Step display ───────────────────────────────────────────────────────────

    def _refresh_steps(self):
        statuses = installer.gb_step_status(self._game_with_variant())
        for step, status in statuses.items():
            self._set_step_icon(step, status)
        iv        = installer.installed_version(self.game, "macOS")
        installed = installer.game_dir(self.game, "macOS").exists()
        self.run_btn.setEnabled(iv is not None and not self._is_running())
        self.uninstall_btn.setEnabled(iv is not None)
        self.folder_btn.setEnabled(installed)
        self.status_changed.emit(self.game)

    def _set_step_icon(self, step: int, status: str):
        self._step_icons[step].setText(_GB_STEP_ICONS.get(status, "⏳"))
        col = {"done": "#00e676", "skip": "#00e676",
               "error": "#ff5555", "running": "#f4c542"}.get(status, "#cccccc")
        self._step_labels[step].setStyleSheet(f"color:{col};")

    # ── Build worker ───────────────────────────────────────────────────────────

    def _run_from(self, from_step: int):
        if self._thread and self._thread.isRunning():
            return
        self.build_btn.setEnabled(False)
        for b in self._step_btns.values():
            b.setEnabled(False)
        self.progress_bar.setValue(0)
        self.progress_label.setText(f"Starting step {from_step}…")

        self._thread = QThread(self)
        self._worker = GBRecompWorker(self._game_with_variant(), from_step)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self.progress_bar.setValue)
        self._worker.step.connect(self._on_step)
        self._worker.finished.connect(self._on_done)
        self._worker.error.connect(self._on_error)
        self._worker.finished.connect(self._thread.quit)
        self._worker.error.connect(self._thread.quit)
        self._thread.start()

    def _on_step(self, step: int, status: str):
        self._set_step_icon(step, status)
        self.progress_label.setText(
            f"Step {step}: {_GB_STEP_NAMES.get(step, '')}  —  {status}"
        )

    def _on_done(self):
        self.progress_label.setText("Build complete ✔")
        self._refresh_steps()
        self.build_btn.setEnabled(True)
        for b in self._step_btns.values():
            b.setEnabled(True)

    def _on_error(self, msg: str):
        self.progress_label.setText("Build failed ✖")
        self._refresh_steps()
        self.build_btn.setEnabled(True)
        for b in self._step_btns.values():
            b.setEnabled(True)
        QMessageBox.critical(self, "Build Error", msg)

    # ── Launch / browse / uninstall ───────────────────────────────────────────

    def _is_running(self) -> bool:
        folder = self.game["folder"]
        proc = GBRecompDialog._running.get(folder)
        if proc is None:
            return False
        if proc.poll() is not None:
            del GBRecompDialog._running[folder]
            return False
        return True

    def _poll_running(self):
        if self.run_btn.isEnabled():
            return
        if not self._is_running():
            iv = installer.installed_version(self.game, "macOS")
            self.run_btn.setEnabled(iv is not None)

    def _do_run(self):
        try:
            proc = installer.launch_game(self._game_with_variant(), "macOS")
            GBRecompDialog._running[self.game["folder"]] = proc
            self.run_btn.setEnabled(False)
        except Exception as exc:
            QMessageBox.critical(self, "Launch Error", str(exc))

    def _do_browse(self):
        installer.reveal_in_finder(installer.game_dir(self.game, "macOS"))

    def _do_uninstall(self):
        reply = QMessageBox.question(
            self, "Uninstall",
            f"Remove all files for {self.game['name']}?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            installer.uninstall_game(self.game, "macOS")
            self._refresh_steps()
            self.progress_bar.setValue(0)
            self.progress_label.setText("")


# ── Main window ────────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Game Port Installer")
        self.resize(780, 560)
        self.setMinimumSize(560, 350)

        self._release_cache: dict[str, dict] = {}   # folder → release
        self._scan_thread = None
        self._scan_worker = None
        self._auto_update_threads: list[QThread] = []
        self._snow:         object = None
        self._fire:         object = None
        self._waterfall:    object = None
        self._blood:        object = None
        self._cursor_anim:  object = None

        installer.GAMES_DIR.mkdir(parents=True, exist_ok=True)
        self._build_ui()
        self._build_menu()
        self._populate()
        self._start_release_scan()

        # Restore effect preferences
        if zsnes_theme and app_settings.get("snow_effect"):
            self._toggle_snow(True)
        if zsnes_theme and app_settings.get("fire_effect"):
            self._toggle_fire(True)
        if zsnes_theme and app_settings.get("waterfall_effect"):
            self._toggle_waterfall(True)
        if zsnes_theme and app_settings.get("nesticle_cursor"):
            self._toggle_nesticle(True)
            if app_settings.get("blood_trail"):
                self._toggle_blood(True)
        # Catch double-clicks on any child widget for the blood gush
        QApplication.instance().installEventFilter(self)
        # Pause/resume all effects when the app loses/gains focus
        QApplication.instance().applicationStateChanged.connect(
            self._on_app_state_changed
        )

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(10, 10, 10, 6)
        layout.setSpacing(8)

        # Toolbar
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        toolbar.addWidget(QLabel("FILTER:"))
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("SEARCH...")
        self.filter_edit.setFixedWidth(160)
        self.filter_edit.textChanged.connect(self._apply_filter)
        self.filter_edit.installEventFilter(self)
        toolbar.addWidget(self.filter_edit)

        toolbar.addSpacing(12)
        toolbar.addWidget(QLabel("TYPE:"))
        self.type_combo = QComboBox()
        self.type_combo.addItems(["ALL", "RECOMP", "DECOMP", "REIMPL", "PORT"])
        self.type_combo.setFixedWidth(100)
        self.type_combo.currentTextChanged.connect(self._apply_filter)
        toolbar.addWidget(self.type_combo)

        toolbar.addSpacing(12)
        self.auto_update_check = QCheckBox("AUTO-UPDATE ON LAUNCH")
        self.auto_update_check.setChecked(app_settings.get("auto_update"))
        self.auto_update_check.toggled.connect(lambda v: (
            app_settings.set_value("auto_update", v),
            self._auto_update_action.setChecked(v),
        ))
        toolbar.addWidget(self.auto_update_check)

        toolbar.addStretch()
        refresh_btn = QPushButton("REFRESH")
        refresh_btn.clicked.connect(self._start_release_scan)
        toolbar.addWidget(refresh_btn)
        layout.addLayout(toolbar)

        # Tree
        self.tree = QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(["PORT", "TYPE", "VERSION"])
        self.tree.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tree.setAlternatingRowColors(False)
        self.tree.setRootIsDecorated(True)
        self.tree.setIndentation(20)
        self.tree.setUniformRowHeights(True)

        hh = self.tree.header()
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.Fixed); self.tree.setColumnWidth(1, 80)
        hh.setSectionResizeMode(2, QHeaderView.Fixed); self.tree.setColumnWidth(2, 130)

        _bg = Path(__file__).parent / "assets" / "mgp-bg.png"
        if _bg.exists():
            self._bg_filter = _BgFilter(_bg, self.tree)
            self.tree.viewport().installEventFilter(self._bg_filter)

        if zsnes_theme:
            self.tree.setItemDelegate(zsnes_theme.UpperCaseDelegate(self.tree))
        self.tree.itemDoubleClicked.connect(self._on_double_click)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_context_menu)

        layout.addWidget(self.tree)
        self.statusBar().showMessage("DOUBLE-CLICK A PORT TO INSTALL OR LAUNCH")

    def _build_menu(self):
        menubar = self.menuBar()
        smenu = menubar.addMenu("Settings")

        self._auto_update_action = QAction("Auto-update installed games", self)
        self._auto_update_action.setCheckable(True)
        self._auto_update_action.setChecked(app_settings.get("auto_update"))
        self._auto_update_action.toggled.connect(lambda v: (
            app_settings.set_value("auto_update", v),
            self.auto_update_check.setChecked(v),
        ))

        smenu.addAction(self._auto_update_action)

        smenu.addSeparator()

        if zsnes_theme:
            self._snow_action = QAction("Snow Effect", self)
            self._snow_action.setCheckable(True)
            self._snow_action.setChecked(app_settings.get("snow_effect"))
            self._snow_action.toggled.connect(self._toggle_snow)
            smenu.addAction(self._snow_action)

            self._fire_action = QAction("Fire Effect", self)
            self._fire_action.setCheckable(True)
            self._fire_action.setChecked(app_settings.get("fire_effect"))
            self._fire_action.toggled.connect(self._toggle_fire)
            smenu.addAction(self._fire_action)

            self._waterfall_action = QAction("Waterfall Effect", self)
            self._waterfall_action.setCheckable(True)
            self._waterfall_action.setChecked(app_settings.get("waterfall_effect"))
            self._waterfall_action.toggled.connect(self._toggle_waterfall)
            smenu.addAction(self._waterfall_action)

            self._nesticle_action = QAction("Nesticle Cursor", self)
            self._nesticle_action.setCheckable(True)
            self._nesticle_action.setChecked(app_settings.get("nesticle_cursor"))
            self._nesticle_action.toggled.connect(self._toggle_nesticle)
            smenu.addAction(self._nesticle_action)

            # Blood Trail — hidden unless Nesticle Cursor is on
            self._blood_action = QAction("    Blood Trail", self)
            self._blood_action.setCheckable(True)
            self._blood_action.setChecked(app_settings.get("blood_trail"))
            self._blood_action.toggled.connect(self._toggle_blood)
            self._blood_action.setVisible(app_settings.get("nesticle_cursor"))
            smenu.addAction(self._blood_action)
            smenu.addSeparator()

        token_action = QAction("Add GitHub Token…", self)
        token_action.triggered.connect(self._show_token_dialog)
        smenu.addAction(token_action)

    def _on_app_state_changed(self, state):
        from PySide6.QtCore import Qt as _Qt
        active = (state == _Qt.ApplicationState.ApplicationActive)
        effects = [self._snow, self._fire, self._waterfall, self._blood]
        for obj in effects:
            if obj is not None and obj.is_running():
                if active:
                    obj.resume()
                else:
                    obj.pause()
        if self._cursor_anim is not None and self._cursor_anim.is_running():
            if active:
                self._cursor_anim.resume()
            else:
                self._cursor_anim.pause()

    def _toggle_snow(self, enabled: bool):
        app_settings.set_value("snow_effect", enabled)
        if not zsnes_theme:
            return
        if enabled:
            if self._snow is None:
                self._snow = zsnes_theme.SnowOverlay(self.centralWidget())
            self._snow.resize(self.centralWidget().size())
            self._snow.start()
        else:
            if self._snow is not None:
                self._snow.stop()

    def _toggle_fire(self, enabled: bool):
        app_settings.set_value("fire_effect", enabled)
        if not zsnes_theme:
            return
        if enabled:
            if self._fire is None:
                self._fire = zsnes_theme.FireOverlay(self.centralWidget())
            self._fire.resize(self.centralWidget().size())
            self._fire.start()
        else:
            if self._fire is not None:
                self._fire.stop()

    def _toggle_waterfall(self, enabled: bool):
        app_settings.set_value("waterfall_effect", enabled)
        if not zsnes_theme:
            return
        if enabled:
            if self._waterfall is None:
                self._waterfall = zsnes_theme.WaterfallOverlay(self.centralWidget())
            self._waterfall.resize(self.centralWidget().size())
            self._waterfall.start()
        else:
            if self._waterfall is not None:
                self._waterfall.stop()

    def _toggle_nesticle(self, enabled: bool):
        app_settings.set_value("nesticle_cursor", enabled)
        if not zsnes_theme:
            return
        if enabled:
            if self._cursor_anim is None:
                _cursor_dir = Path(__file__).parent / "assets" / "cursor_frames"
                if _cursor_dir.exists():
                    self._cursor_anim = zsnes_theme.CursorAnimator(
                        _cursor_dir, parent=QApplication.instance()
                    )
            if self._cursor_anim:
                self._cursor_anim.start()
        else:
            if self._cursor_anim:
                self._cursor_anim.stop()
            # Also disable blood trail when cursor is disabled
            if self._blood is not None:
                self._blood.stop()
            app_settings.set_value("blood_trail", False)
            self._blood_action.setChecked(False)
        # Show / hide the Blood Trail sub-option
        self._blood_action.setVisible(enabled)

    def _toggle_blood(self, enabled: bool):
        app_settings.set_value("blood_trail", enabled)
        if not zsnes_theme:
            return
        if enabled:
            if self._blood is None:
                self._blood = zsnes_theme.BloodRippleOverlay(self.centralWidget())
            self._blood.resize(self.centralWidget().size())
            self._blood.start()
        else:
            if self._blood is not None:
                self._blood.stop()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        cw = self.centralWidget()
        if self._snow  is not None and self._snow.is_running():
            self._snow.resize(cw.size())
        if self._fire       is not None and self._fire.is_running():
            self._fire.resize(cw.size())
        if self._waterfall  is not None and self._waterfall.is_running():
            self._waterfall.resize(cw.size())
        if self._blood      is not None and self._blood.is_running():
            self._blood.resize(cw.size())

    def _show_token_dialog(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("GitHub Token")
        dlg.setMinimumWidth(400)
        dlg.setModal(True)

        layout = QVBoxLayout(dlg)
        layout.setSpacing(10)
        layout.setContentsMargins(20, 16, 20, 16)

        layout.addWidget(QLabel("Enter a GitHub personal access token to avoid API rate limits."))

        token_edit = QLineEdit()
        token_edit.setPlaceholderText("ghp_…")
        token_edit.setEchoMode(QLineEdit.Password)
        token_edit.setText(app_settings.get("github_token") or "")
        layout.addWidget(token_edit)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        save_btn = QPushButton("SAVE")
        cancel_btn = QPushButton("CANCEL")
        save_btn.setDefault(True)
        save_btn.clicked.connect(lambda: (
            app_settings.set_value("github_token", token_edit.text().strip()),
            dlg.accept(),
        ))
        cancel_btn.clicked.connect(dlg.reject)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(save_btn)
        layout.addLayout(btn_row)

        dlg.exec()

    # ── Release scanning ───────────────────────────────────────────────────────

    def _start_release_scan(self):
        if self._scan_thread and self._scan_thread.isRunning():
            return
        self._scan_thread = None
        self._scan_worker = None
        self.statusBar().showMessage("CHECKING FOR LATEST VERSIONS...")
        thread = QThread(self)
        worker = AllReleasesWorker()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.game_checked.connect(self._on_release_fetched)
        worker.finished.connect(thread.quit)
        worker.finished.connect(lambda: self.statusBar().showMessage("DOUBLE-CLICK A PORT TO INSTALL OR LAUNCH"))
        worker.finished.connect(lambda: setattr(self, '_scan_thread', None))
        self._scan_thread = thread
        self._scan_worker = worker
        thread.start()

    def _on_release_fetched(self, folder: str, release):
        if not release:
            return
        self._release_cache[folder] = release
        # Refresh the row in the tree
        for child in self._iter_port_items():
            if child.data(0, Qt.UserRole) == folder:
                game = next((g for g in GAMES if g["folder"] == folder), None)
                if game:
                    status_str, color = self._game_status(game)
                    child.setText(2, status_str)
                    child.setForeground(2, color)
                break
        # Auto-update if the game is installed and behind
        if app_settings.get("auto_update"):
            game = next((g for g in GAMES if g["folder"] == folder), None)
            if game:
                iv  = installer.installed_version(game, "macOS")
                tag = release.get("tag_name", "")
                if iv and iv != tag:
                    self._auto_update(game, release)

    def _auto_update(self, game: dict, release: dict):
        asset = installer.pick_asset(release, "macOS", game)
        if not asset:
            return
        self.statusBar().showMessage(f"AUTO-UPDATING {game['name'].upper()}...")
        thread = QThread(self)
        worker = InstallWorker(game, release, asset)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(thread.quit)
        worker.finished.connect(lambda tag: self._on_release_fetched(game["folder"], release))
        worker.finished.connect(lambda: self._auto_update_threads.remove(thread)
                                if thread in self._auto_update_threads else None)
        worker.error.connect(thread.quit)
        self._auto_update_threads.append(thread)
        thread.start()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.tree.collapseAll()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        # Stop the background release scan
        if self._scan_thread and self._scan_thread.isRunning():
            self._scan_thread.quit()
            self._scan_thread.wait(3000)
        # Stop any in-progress auto-update installs
        for thread in list(self._auto_update_threads):
            if thread.isRunning():
                thread.quit()
                thread.wait(3000)
        event.accept()

    # ── Populate ───────────────────────────────────────────────────────────────

    def _game_status(self, game: dict) -> tuple[str, QColor]:
        iv      = installer.installed_version(game, "macOS")
        release = self._release_cache.get(game["folder"])
        tag     = release.get("tag_name") if release else None

        if iv:
            if tag and iv != tag:
                return f"↑  {tag}", COLOR_UPDATE
            return f"✓  {iv}", COLOR_INSTALLED
        if tag:
            return f"—  {tag} available", COLOR_NONE
        return STATUS_NOT_INSTALLED, COLOR_NONE

    def _populate(self):
        self.tree.clear()
        query     = self.filter_edit.text().lower()
        type_filt = self.type_combo.currentText()

        # Build console → game_title → [games] hierarchy
        # Only show games with a macOS binary or a build-from-source config
        mac_games = [
            g for g in GAMES
            if "macOS" in g.get("platforms", []) or g.get("build")
        ]
        console_groups: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
        for game in sorted(mac_games, key=lambda g: g["name"]):
            console = game.get("console", "Other")
            title   = game.get("game_title", "Unknown")
            console_groups[console][title].append(game)

        bold_font = QFont()
        bold_font.setBold(True)
        bold_sm = QFont()
        bold_sm.setBold(True)
        bold_sm.setPointSize(bold_sm.pointSize() - 1)

        for console in sorted(console_groups.keys()):
            title_groups = console_groups[console]

            # Check if anything passes filters under this console
            console_item = None

            for title in sorted(title_groups.keys()):
                ports = title_groups[title]

                visible = []
                for game in ports:
                    if query and query not in game["name"].lower() \
                              and query not in title.lower() \
                              and query not in console.lower():
                        continue
                    if type_filt != "ALL" and game.get("type", "").upper() != type_filt:
                        continue
                    visible.append(game)

                if not visible:
                    continue

                # Lazily create console row on first match
                if console_item is None:
                    console_item = QTreeWidgetItem(self.tree)
                    console_item.setText(0, console)
                    console_item.setFont(0, bold_font)
                    console_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                    console_item.setFirstColumnSpanned(True)
                    console_item.setExpanded(bool(query))

                # Game title row
                title_item = QTreeWidgetItem(console_item)
                title_item.setText(0, title)
                title_item.setFont(0, bold_sm)
                title_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                title_item.setFirstColumnSpanned(True)
                title_item.setExpanded(bool(query))

                # Port rows
                for game in visible:
                    status_str, color = self._game_status(game)
                    child = QTreeWidgetItem(title_item)
                    child.setText(0, game["name"])
                    child.setText(1, game.get("type", "—"))
                    child.setText(2, status_str)
                    child.setForeground(2, color)
                    child.setData(0, Qt.UserRole, game["folder"])

    def _apply_filter(self):
        self._populate()

    def _iter_port_items(self):
        """Yield every leaf (port) QTreeWidgetItem across the three-level tree."""
        for i in range(self.tree.topLevelItemCount()):
            console_item = self.tree.topLevelItem(i)
            for j in range(console_item.childCount()):
                title_item = console_item.child(j)
                for k in range(title_item.childCount()):
                    yield title_item.child(k)

    def _update_game_row(self, game: dict):
        for child in self._iter_port_items():
            if child.data(0, Qt.UserRole) == game["folder"]:
                status_str, color = self._game_status(game)
                child.setText(2, status_str)
                child.setForeground(2, color)
                return

    def _game_for_item(self, item: QTreeWidgetItem) -> dict | None:
        # Port items are at depth 2 (have a parent and a grandparent)
        if item is None or item.parent() is None or item.parent().parent() is None:
            return None  # console or game-title header
        folder = item.data(0, Qt.UserRole)
        return next((g for g in GAMES if g["folder"] == folder), None)

    # ── Interaction ────────────────────────────────────────────────────────────

    def eventFilter(self, obj, event):
        if obj is self.filter_edit and event.type() == QEvent.KeyPress:
            if event.key() == Qt.Key_Escape:
                self.filter_edit.clear()
                return True
        # Double-click anywhere → blood gush if effect is active
        if (event.type() == QEvent.Type.MouseButtonDblClick
                and self._blood is not None
                and self._blood.is_running()):
            self._blood.gush(event.globalPosition().toPoint())
        return super().eventFilter(obj, event)

    def _on_double_click(self, item: QTreeWidgetItem, column: int):
        game = self._game_for_item(item)
        if game:
            self._open_dialog(game)

    def _on_context_menu(self, pos):
        item = self.tree.itemAt(pos)
        game = self._game_for_item(item)
        if not game:
            return

        menu = QMenu(self)

        open_action = QAction("Install / Launch…", self)
        open_action.triggered.connect(lambda: self._open_dialog(game))
        menu.addAction(open_action)

        menu.addSeparator()

        reveal_action = QAction("Reveal in Finder", self)
        game_path = installer.game_dir(game, "macOS")
        reveal_action.setEnabled(game_path.exists())
        reveal_action.triggered.connect(lambda: installer.reveal_in_finder(game_path))
        menu.addAction(reveal_action)

        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _open_dialog(self, game: dict):
        # Close any existing game dialog before opening a new one
        if hasattr(self, "_game_dlg") and self._game_dlg:
            self._game_dlg.close()
        try:
            if game.get("build_type") == "gb_recomp":
                dlg = GBRecompDialog(self, game)
            else:
                dlg = GameDialog(self, game)
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"Could not open dialog:\n{exc}")
            return
        dlg.status_changed.connect(self._update_game_row)
        self._game_dlg = dlg
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()


# ── Entry point ────────────────────────────────────────────────────────────────

def _check_brew():
    """Warn once if Homebrew is not installed."""
    if shutil.which("brew"):
        return
    if app_settings.get("brew_warning_shown"):
        return
    app_settings.set_value("brew_warning_shown", True)
    dlg = QMessageBox()
    dlg.setWindowTitle("Homebrew Required")
    dlg.setIcon(QMessageBox.Warning)
    dlg.setText(
        "Homebrew is not installed.\n\n"
        "Some games require Homebrew to install dependencies or compile from source. "
        "Without it, those games may fail to install.\n\n"
        "Visit brew.sh to install Homebrew."
    )
    dlg.addButton("Get Homebrew", QMessageBox.AcceptRole)
    dlg.addButton("Dismiss", QMessageBox.RejectRole)
    if dlg.exec() == 0:
        QDesktopServices.openUrl(QUrl("https://brew.sh"))


if __name__ == "__main__":
    app = QApplication(sys.argv)
    if zsnes_theme:
        zsnes_theme.load_pixel_font()
        app.setStyle(zsnes_theme.UpperCaseStyle("Fusion"))
        app.setFont(zsnes_theme.pixel_font(7))
        app.setStyleSheet(zsnes_theme.stylesheet())
        zsnes_theme.install_uppercase_filter(app)
        pass  # cursor now managed by MainWindow via Nesticle Cursor setting
    icon_path = Path(__file__).parent / "assets" / "mgp-icon.png"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    win = MainWindow()
    win.show()
    _check_brew()
    sys.exit(app.exec())
