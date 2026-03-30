#!/usr/bin/env python3
"""Animal Crossing PC Port configuration editor."""

import re
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox,
    QFormLayout, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QMainWindow, QPushButton,
    QScrollArea, QTabWidget, QVBoxLayout, QWidget,
)

import installer

_GAME = {"folder": "AnimalCrossing", "console": "GameCube"}
_BIN_DIR = installer.game_dir(_GAME, "macOS") / "pc" / "build" / "bin"
SETTINGS_PATH    = _BIN_DIR / "settings.ini"
KEYBINDINGS_PATH = _BIN_DIR / "keybindings.ini"


# ── INI parser (preserves comments and blank lines) ───────────────────────────

class IniFile:
    def __init__(self, path: Path):
        self.path = path
        self._lines: list[dict] = []
        self._values: dict[tuple, str] = {}
        if path.exists():
            self._parse()

    def _parse(self):
        section = None
        with open(self.path) as f:
            for line in f:
                line = line.rstrip("\n")
                stripped = line.strip()
                m = re.match(r"^\[(.+)\]$", stripped)
                if m:
                    section = m.group(1)
                    self._lines.append({"type": "raw", "text": line})
                elif "=" in stripped and not stripped.startswith("#"):
                    key, _, val = line.partition("=")
                    key_s = key.strip()
                    val_s = val.strip()
                    self._lines.append({
                        "type": "setting",
                        "section": section,
                        "key": key_s,
                        "text": line,
                    })
                    self._values[(section, key_s)] = val_s
                else:
                    self._lines.append({"type": "raw", "text": line})

    def get(self, section: str, key: str, default: str = "") -> str:
        return self._values.get((section, key), default)

    def set(self, section: str, key: str, value: str):
        self._values[(section, key)] = value

    def save(self):
        out = []
        for item in self._lines:
            if item["type"] == "raw":
                out.append(item["text"])
            else:
                s, k = item["section"], item["key"]
                val = self._values.get((s, k), "")
                out.append(f"{k} = {val}")
        with open(self.path, "w") as f:
            f.write("\n".join(out))


# ── Config window ─────────────────────────────────────────────────────────────

class ConfigWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Animal Crossing — Configuration")
        self.setMinimumWidth(480)

        self._settings    = IniFile(SETTINGS_PATH)
        self._keybindings = IniFile(KEYBINDINGS_PATH)

        tabs = QTabWidget()
        tabs.addTab(self._make_graphics_tab(),   "Graphics")
        tabs.addTab(self._make_keybindings_tab(), "Keybindings")

        save_btn = QPushButton("Save")
        save_btn.clicked.connect(self._save)

        root = QWidget()
        vbox = QVBoxLayout(root)
        vbox.addWidget(tabs)
        vbox.addWidget(save_btn)
        self.setCentralWidget(root)

    # ── Graphics tab ──────────────────────────────────────────────────────────

    def _make_graphics_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        vbox  = QVBoxLayout(inner)

        # Graphics group
        gfx = QGroupBox("Graphics")
        form = QFormLayout(gfx)

        self._width  = QLineEdit(self._settings.get("Graphics", "window_width",  "640"))
        self._height = QLineEdit(self._settings.get("Graphics", "window_height", "480"))
        form.addRow("Window width",  self._width)
        form.addRow("Window height", self._height)

        self._fullscreen = QComboBox()
        self._fullscreen.addItems(["Windowed", "Fullscreen", "Borderless fullscreen"])
        self._fullscreen.setCurrentIndex(
            int(self._settings.get("Graphics", "fullscreen", "0"))
        )
        form.addRow("Fullscreen", self._fullscreen)

        self._vsync = QCheckBox()
        self._vsync.setChecked(self._settings.get("Graphics", "vsync", "0") == "1")
        form.addRow("VSync", self._vsync)

        self._msaa = QComboBox()
        self._msaa.addItems(["Off (0)", "2×", "4×", "8×"])
        msaa_map = {"0": 0, "2": 1, "4": 2, "8": 3}
        self._msaa.setCurrentIndex(
            msaa_map.get(self._settings.get("Graphics", "msaa", "4"), 2)
        )
        form.addRow("Anti-aliasing (MSAA)", self._msaa)

        # Enhancements group
        enh = QGroupBox("Enhancements")
        eform = QFormLayout(enh)

        self._preload = QComboBox()
        self._preload.addItems([
            "Off — load on demand (0)",
            "Preload at startup (1)",
            "Preload + cache file — fastest (2)",
        ])
        self._preload.setCurrentIndex(
            int(self._settings.get("Enhancements", "preload_textures", "0"))
        )
        eform.addRow("Texture preloading", self._preload)

        vbox.addWidget(gfx)
        vbox.addWidget(enh)
        vbox.addStretch()
        scroll.setWidget(inner)
        return scroll

    # ── Keybindings tab ───────────────────────────────────────────────────────

    # GCN button → (label, default key)
    _BINDS = [
        ("A",           "A Button",      "Space"),
        ("B",           "B Button",      "Left Shift"),
        ("X",           "X Button",      "X"),
        ("Y",           "Y Button",      "Y"),
        ("Start",       "Start",         "Return"),
        ("Z",           "Z Trigger",     "Z"),
        ("L",           "L Trigger",     "Q"),
        ("R",           "R Trigger",     "E"),
        ("Stick_Up",    "Stick Up",      "W"),
        ("Stick_Down",  "Stick Down",    "S"),
        ("Stick_Left",  "Stick Left",    "A"),
        ("Stick_Right", "Stick Right",   "D"),
        ("CStick_Up",   "C-Stick Up",    "Up"),
        ("CStick_Down", "C-Stick Down",  "Down"),
        ("CStick_Left", "C-Stick Left",  "Left"),
        ("CStick_Right","C-Stick Right", "Right"),
        ("DPad_Up",     "D-Pad Up",      "I"),
        ("DPad_Down",   "D-Pad Down",    "K"),
        ("DPad_Left",   "D-Pad Left",    "J"),
        ("DPad_Right",  "D-Pad Right",   "L"),
    ]

    def _make_keybindings_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        form  = QFormLayout(inner)
        form.setLabelAlignment(Qt.AlignRight)

        note = QLabel(
            "Key names use SDL2 scancode names: A–Z, 0–9, F1–F12,\n"
            "Space, Return, Escape, Tab, Up, Down, Left, Right,\n"
            "Left Shift, Right Shift, Left Ctrl, Left Alt, etc.\n"
            "Mouse buttons: Mouse1 (left), Mouse2 (right), Mouse3 (middle)"
        )
        note.setStyleSheet("color: gray; font-size: 11px;")
        form.addRow(note)

        self._bind_widgets: dict[str, QLineEdit] = {}
        for key, label, default in self._BINDS:
            val = self._keybindings.get("Keyboard", key, default)
            edit = QLineEdit(val)
            self._bind_widgets[key] = edit
            form.addRow(label, edit)

        scroll.setWidget(inner)
        return scroll

    # ── Save ──────────────────────────────────────────────────────────────────

    def _save(self):
        # Graphics
        self._settings.set("Graphics", "window_width",  self._width.text().strip())
        self._settings.set("Graphics", "window_height", self._height.text().strip())
        self._settings.set("Graphics", "fullscreen",    str(self._fullscreen.currentIndex()))
        self._settings.set("Graphics", "vsync",         "1" if self._vsync.isChecked() else "0")
        msaa_vals = ["0", "2", "4", "8"]
        self._settings.set("Graphics", "msaa",          msaa_vals[self._msaa.currentIndex()])
        self._settings.set("Enhancements", "preload_textures", str(self._preload.currentIndex()))
        self._settings.save()

        # Keybindings
        for key, edit in self._bind_widgets.items():
            self._keybindings.set("Keyboard", key, edit.text().strip())
        self._keybindings.save()

        self.setWindowTitle("Animal Crossing — Configuration  ✓")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = ConfigWindow()
    win.show()
    sys.exit(app.exec())
