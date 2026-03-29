#!/usr/bin/env python3
"""
macOS game port launcher — PySide6.
Double-click a game to install, update, or launch.
"""

import hashlib
import shutil
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

from PySide6.QtCore import Qt, QObject, QThread, Signal, QEvent
from PySide6.QtGui import QColor, QAction, QFont, QIcon
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QComboBox, QPushButton,
    QTreeWidget, QTreeWidgetItem, QHeaderView, QAbstractItemView,
    QDialog, QProgressBar, QFormLayout,
    QMessageBox, QSizePolicy, QMenu, QCheckBox, QFileDialog,
)

import installer
import settings as app_settings
from games import GAMES

# ── Constants ──────────────────────────────────────────────────────────────────

STATUS_NOT_INSTALLED = "—  Not Installed"

COLOR_INSTALLED = QColor("#1a7a1a")
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
        for game in GAMES:
            try:
                release = installer.fetch_latest_release(game)
            except Exception:
                release = None
            self.game_checked.emit(game["folder"], release)
        self.finished.emit()


# ── Game dialog ────────────────────────────────────────────────────────────────

class GameDialog(QDialog):
    status_changed = Signal(dict)

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
        self.setModal(True)
        self._build_ui()
        self._load_release()

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
        repo_label.setStyleSheet("color: #555;")
        root.addWidget(repo_label)

        line = QWidget(); line.setFixedHeight(1)
        line.setStyleSheet("background: #ccc;")
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
        self.progress_label.setStyleSheet("color: #555; font-size: 11px;")
        root.addWidget(self.progress_label)

        # Buttons  (order: Run · Configure? · Install · Browse Folder · Uninstall · Close)
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self.run_btn = QPushButton("Run")
        self.run_btn.setEnabled(False)
        self.run_btn.setStyleSheet("QPushButton { background: #2d7a2d; color: white; }"
                                   "QPushButton:hover { background: #3a9e3a; }"
                                   "QPushButton:disabled { background: #1e4a1e; color: #666; }")
        self.run_btn.clicked.connect(self._do_run)

        self.config_btn = QPushButton("Configure")
        self.config_btn.setVisible(bool(self.game.get("has_config")))
        self.config_btn.clicked.connect(self._do_configure)

        self.install_btn = QPushButton("Install")
        self.install_btn.setEnabled(False)
        self.install_btn.clicked.connect(self._do_install)

        self.folder_btn = QPushButton("Browse Folder")
        self.folder_btn.setEnabled(False)
        self.folder_btn.clicked.connect(self._do_browse)

        self.uninstall_btn = QPushButton("Uninstall")
        self.uninstall_btn.setEnabled(False)
        self.uninstall_btn.setStyleSheet("QPushButton { background: #7a2d2d; color: white; }"
                                         "QPushButton:hover { background: #9e3a3a; }"
                                         "QPushButton:disabled { background: #4a1e1e; color: #666; }")
        self.uninstall_btn.clicked.connect(self._do_uninstall)

        close_btn = QPushButton("Close")
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
        self.run_btn.setEnabled(iv is not None)
        self.uninstall_btn.setEnabled(iv is not None)
        self.folder_btn.setEnabled(installed)
        self.config_btn.setEnabled(iv is not None)

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
        self.run_btn.setEnabled(iv is not None)
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
        rom_name  = self.game.get("requires_rom")

        if rom_name:
            rom_dest      = game_path / rom_name
            expected_sha  = self.game.get("rom_checksum", "")
            assets_marker = self.game.get("assets_marker")   # file that proves extraction is done
            assets_done   = (game_path / assets_marker).exists() if assets_marker else False

            # ── 1. Make sure we have the correct ROM on disk ──────────────────
            def _sha256(p):
                h = hashlib.sha256()
                with open(p, "rb") as f:
                    for chunk in iter(lambda: f.read(1 << 20), b""):
                        h.update(chunk)
                return h.hexdigest()

            rom_ok = rom_dest.exists() and (
                not expected_sha or _sha256(rom_dest).lower() == expected_sha.lower()
            )

            if not rom_ok:
                # Try the file picker
                path, _ = QFileDialog.getOpenFileName(
                    self,
                    f"{self.game['name']} — Locate ROM ({rom_name})",
                    str(Path.home()),
                    "All files (*)",
                )
                if not path:
                    return

                # Validate checksum
                if expected_sha:
                    self.progress_label.setText("Verifying ROM…")
                    QApplication.processEvents()
                    actual = _sha256(path)
                    self.progress_label.setText("")
                    if actual.lower() != expected_sha.lower():
                        QMessageBox.critical(
                            self, "Wrong ROM",
                            f"Checksum mismatch — this doesn't appear to be the correct ROM.\n\n"
                            f"Expected: {expected_sha}\nGot:      {actual}",
                        )
                        return

                shutil.copy2(path, rom_dest)
                rom_ok = True
                assets_done = False   # force re-extraction with new ROM

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
            installer.launch_game(self.game, "macOS")
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
        from zelda3_config import ConfigWindow
        self._config_win = ConfigWindow()
        self._config_win.show()


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

        installer.GAMES_DIR.mkdir(parents=True, exist_ok=True)
        self._build_ui()
        self._build_menu()
        self._populate()
        self._start_release_scan()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(10, 10, 10, 6)
        layout.setSpacing(8)

        # Toolbar
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        toolbar.addWidget(QLabel("Filter:"))
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Search…")
        self.filter_edit.setFixedWidth(160)
        self.filter_edit.textChanged.connect(self._apply_filter)
        self.filter_edit.installEventFilter(self)
        toolbar.addWidget(self.filter_edit)

        toolbar.addSpacing(12)
        toolbar.addWidget(QLabel("Type:"))
        self.type_combo = QComboBox()
        self.type_combo.addItems(["All", "Recomp", "Decomp", "Reimpl", "Port", "Fan Game"])
        self.type_combo.setFixedWidth(100)
        self.type_combo.currentTextChanged.connect(self._apply_filter)
        toolbar.addWidget(self.type_combo)

        toolbar.addSpacing(12)
        self.auto_update_check = QCheckBox("Auto-update on launch")
        self.auto_update_check.setChecked(app_settings.get("auto_update"))
        self.auto_update_check.toggled.connect(lambda v: (
            app_settings.set_value("auto_update", v),
            self._auto_update_action.setChecked(v),
        ))
        toolbar.addWidget(self.auto_update_check)

        toolbar.addStretch()
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self._start_release_scan)
        toolbar.addWidget(refresh_btn)
        layout.addLayout(toolbar)

        # Tree
        self.tree = QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(["Port", "Type", "Version"])
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

        self.tree.itemDoubleClicked.connect(self._on_double_click)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_context_menu)

        layout.addWidget(self.tree)
        self.statusBar().showMessage("Double-click a port to install or launch")

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

    # ── Release scanning ───────────────────────────────────────────────────────

    def _start_release_scan(self):
        if self._scan_thread and self._scan_thread.isRunning():
            return
        self._scan_thread = None
        self._scan_worker = None
        self.statusBar().showMessage("Checking for latest versions…")
        thread = QThread(self)
        worker = AllReleasesWorker()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.game_checked.connect(self._on_release_fetched)
        worker.finished.connect(thread.quit)
        worker.finished.connect(lambda: self.statusBar().showMessage("Double-click a port to install or launch"))
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
        self.statusBar().showMessage(f"Auto-updating {game['name']}…")
        thread = QThread(self)
        worker = InstallWorker(game, release, asset)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(thread.quit)
        worker.finished.connect(lambda tag: self._on_release_fetched(game["folder"], release))
        worker.error.connect(thread.quit)
        thread.start()

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
        console_groups: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
        for game in sorted(GAMES, key=lambda g: g["name"]):
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
                    if type_filt != "All" and game.get("type") != type_filt:
                        continue
                    visible.append(game)

                if not visible:
                    continue

                # Lazily create console row on first match
                if console_item is None:
                    console_item = QTreeWidgetItem(self.tree)
                    console_item.setText(0, console)
                    console_item.setFont(0, bold_font)
                    console_item.setFlags(Qt.ItemIsEnabled)
                    console_item.setFirstColumnSpanned(True)
                    console_item.setExpanded(bool(query))

                # Game title row
                title_item = QTreeWidgetItem(console_item)
                title_item.setText(0, title)
                title_item.setFont(0, bold_sm)
                title_item.setFlags(Qt.ItemIsEnabled)
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
        dlg = GameDialog(self, game)
        dlg.status_changed.connect(self._update_game_row)
        dlg.exec()


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("macos")
    icon_path = Path(__file__).parent / "AppIcon.icns"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    win = MainWindow()
    win.show()
    sys.exit(app.exec())
