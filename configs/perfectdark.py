#!/usr/bin/env python3
"""Perfect Dark configuration editor."""

import re
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox,
    QFormLayout, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QMainWindow, QPushButton, QScrollArea,
    QSizePolicy, QTabWidget, QVBoxLayout, QWidget,
)

import installer

INI_PATH = installer.game_dir({"folder": "PerfectDark", "console": "Nintendo 64"}, "macOS") / "pd.ini"

# ── Settings metadata ─────────────────────────────────────────────────────────

VIDEO_META = [
    ("DefaultFullscreen",  "Start fullscreen",                          "bool",   None),
    ("DefaultMaximize",    "Start maximized",                           "bool",   None),
    ("DefaultWidth",       "Window width (px)",                         "str",    None),
    ("DefaultHeight",      "Window height (px)",                        "str",    None),
    ("ExclusiveFullscreen","Exclusive fullscreen",                       "bool",   None),
    ("CenterWindow",       "Center window on screen",                   "bool",   None),
    ("AllowHiDpi",         "Allow HiDPI / Retina",                      "bool",   None),
    ("VSync",              "VSync  (−1 adaptive, 0 off, 1 on)",         "choice", ["-1", "0", "1"]),
    ("FramerateLimit",     "Framerate limit  (0 = unlimited)",          "str",    None),
    ("DisplayFPS",         "Display FPS counter",                       "bool",   None),
    ("DisplayFPSInterval", "FPS counter update interval (s)",           "str",    None),
    ("FramebufferEffects", "Framebuffer effects",                       "bool",   None),
    ("MSAA",               "MSAA samples",                              "choice", ["1", "2", "4", "8", "16"]),
    ("TextureFilter",      "Texture filter  (0 nearest, 1 linear, 2 aniso)", "choice", ["0", "1", "2"]),
    ("TextureFilter2D",    "2D texture filter  (0 nearest, 1 linear)", "choice", ["0", "1"]),
    ("MipmapFilter",       "Mipmap filter  (0 off, 1 nearest, 2 linear)", "choice", ["0", "1", "2"]),
    ("AnisotropicFilter",  "Anisotropic filter level",                  "choice", ["0", "2", "4", "8", "16"]),
    ("DetailTextures",     "Detail textures",                           "bool",   None),
]

AUDIO_META = [
    ("BufferSize",  "Audio buffer size (samples)", "str", None),
    ("QueueLimit",  "Audio queue limit (samples)", "str", None),
]

GAME_META = [
    ("MemorySize",           "Memory size (MB)",                       "choice", ["4", "8", "16", "32", "64", "128", "256"]),
    ("CenterHUD",            "Center HUD  (0 off, 1 always, 2 wide)",  "choice", ["0", "1", "2"]),
    ("MenuMouseControl",     "Mouse control in menus",                 "bool",   None),
    ("ScreenShakeIntensity", "Screen shake intensity  (0–10)",         "str",    None),
    ("TickRateDivisor",      "Tick rate divisor  (1 = normal)",        "choice", ["0", "1", "2", "3", "4", "5"]),
    ("ExtraSleep",           "Extra sleep between frames",             "bool",   None),
    ("SkipIntro",            "Skip intro on startup",                  "bool",   None),
    ("DisableMpDeathMusic",  "Disable multiplayer death music",        "bool",   None),
    ("GEMuzzleFlashes",      "GoldenEye-style muzzle flashes",         "bool",   None),
    ("MaxExplosions",        "Max simultaneous explosions",            "choice", ["6", "12", "24", "48", "96"]),
]

INPUT_META = [
    ("MouseEnabled",    "Enable mouse",                                 "bool",   None),
    ("MouseLockMode",   "Mouse lock  (0 off, 1 on, 2 auto)",           "choice", ["0", "1", "2"]),
    ("MouseSpeedX",     "Mouse speed X",                               "str",    None),
    ("MouseSpeedY",     "Mouse speed Y",                               "str",    None),
    ("FakeGamepads",    "Virtual gamepads  (0–4)",                     "choice", ["0", "1", "2", "3", "4"]),
    ("FirstGamepadNum", "First gamepad device index",                  "choice", ["0", "1", "2", "3"]),
    ("UseHIDAPI",       "Use HIDAPI for gamepad input",                "bool",   None),
    ("UseRawInput",     "Use raw input (Windows only)",                "bool",   None),
]

PLAYER_GAME_META = [
    ("FovY",                  "Field of view Y (degrees)",             "str",    None),
    ("FovAffectsZoom",        "FOV affects zoom",                      "bool",   None),
    ("MouseAimMode",          "Mouse aim mode",                        "choice", ["0", "1", "2", "3"]),
    ("MouseAimSpeedX",        "Mouse aim speed X",                     "str",    None),
    ("MouseAimSpeedY",        "Mouse aim speed Y",                     "str",    None),
    ("RadialMenuSpeed",       "Radial menu speed",                     "str",    None),
    ("CrosshairSway",         "Crosshair sway  (0–10)",                "str",    None),
    ("CrosshairEdgeBoundary", "Crosshair edge boundary  (0–1)",        "str",    None),
    ("CrosshairSize",         "Crosshair size",                        "choice", ["0", "1", "2", "3", "4"]),
    ("CrosshairHealth",       "Crosshair health indicator",            "choice", ["0", "1", "2"]),
    ("CrosshairColour",       "Crosshair colour (decimal ARGB)",       "str",    None),
    ("CrouchMode",            "Crouch mode  (0 tap, 1 hold, 2 toggle, 3 analog)", "choice", ["0", "1", "2", "3"]),
    ("ExtendedControls",      "Extended controls",                     "bool",   None),
    ("UseKeyReloads",         "Key reload (instead of hold)",          "bool",   None),
]

PLAYER_INPUT_META = [
    ("RumbleScale",       "Rumble intensity  (0–1)",  "str",    None),
    ("LStickDeadzoneX",   "L-stick deadzone X",       "str",    None),
    ("LStickDeadzoneY",   "L-stick deadzone Y",       "str",    None),
    ("LStickScaleX",      "L-stick scale X",          "str",    None),
    ("LStickScaleY",      "L-stick scale Y",          "str",    None),
    ("RStickDeadzoneX",   "R-stick deadzone X",       "str",    None),
    ("RStickDeadzoneY",   "R-stick deadzone Y",       "str",    None),
    ("RStickScaleX",      "R-stick scale X",          "str",    None),
    ("RStickScaleY",      "R-stick scale Y",          "str",    None),
    ("StickCButtons",     "Stick C-buttons",          "bool",   None),
    ("CancelCButtons",    "Cancel C-button mapping",  "bool",   None),
    ("SwapSticks",        "Swap analog sticks",       "bool",   None),
    ("ControllerIndex",   "Controller device index  (−1 = any)", "str", None),
]

# N64 button → human label
BIND_LABELS = [
    ("Z_TRIG",        "Z Trigger  (Fire)"),
    ("R_TRIG",        "R Trigger  (Aim)"),
    ("L_TRIG",        "L Trigger  (Reload / Action)"),
    ("A_BUTTON",      "A Button"),
    ("B_BUTTON",      "B Button"),
    ("X_BUTTON",      "X Button"),
    ("Y_BUTTON",      "Y Button"),
    ("START_BUTTON",  "Start / Pause"),
    ("U_CBUTTONS",    "C-Up"),
    ("D_CBUTTONS",    "C-Down"),
    ("L_CBUTTONS",    "C-Left"),
    ("R_CBUTTONS",    "C-Right"),
    ("U_JPAD",        "D-Pad Up"),
    ("D_JPAD",        "D-Pad Down"),
    ("L_JPAD",        "D-Pad Left"),
    ("R_JPAD",        "D-Pad Right"),
    ("STICK_YPOS",    "Stick Forward"),
    ("STICK_YNEG",    "Stick Back"),
    ("STICK_XNEG",    "Stick Left"),
    ("STICK_XPOS",    "Stick Right"),
    ("ACCEPT_BUTTON", "Accept (Menus)"),
    ("CANCEL_BUTTON", "Cancel (Menus)"),
    ("CK_0040",       "Custom Key 1"),
    ("CK_0080",       "Custom Key 2"),
    ("CK_0100",       "Custom Key 3"),
    ("CK_0200",       "Custom Key 4"),
    ("CK_0400",       "Custom Key 5"),
    ("CK_0800",       "Custom Key 6"),
    ("CK_1000",       "Custom Key 7"),
    ("CK_2000",       "Custom Key 8  (default: Crouch)"),
    ("CK_4000",       "Custom Key 9  (default: Sidestep)"),
    ("CK_8000",       "Custom Key 10"),
]


# ── INI parser (preserves comments, writes without spaces around =) ───────────

class IniFile:
    def __init__(self, path):
        self.path = path
        self._lines: list[dict] = []
        self._values: dict[tuple, str] = {}
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
                elif "=" in stripped and not stripped.startswith(("#", ";")):
                    key, _, val = line.partition("=")
                    key_stripped = key.strip()
                    self._lines.append({
                        "type": "setting",
                        "section": section,
                        "key": key_stripped,
                        "text": line,
                    })
                    self._values[(section, key_stripped)] = val.strip()
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
                out.append(f"{k}={self._values.get((s, k), '')}")
        with open(self.path, "w") as f:
            f.write("\n".join(out))


# ── Reusable settings tab (scroll area of form widgets) ───────────────────────

class SettingsTab(QScrollArea):
    def __init__(self, section: str, meta: list, ini: IniFile):
        super().__init__()
        self._section = section
        self._meta    = meta
        self._ini     = ini
        self._widgets: dict[str, QWidget] = {}

        container = QWidget()
        form = QFormLayout(container)
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form.setSpacing(10)
        form.setContentsMargins(16, 16, 16, 16)

        for key, label, wtype, opts in meta:
            val = ini.get(section, key)
            w   = self._make_widget(wtype, opts, val)
            self._widgets[key] = w
            form.addRow(label + ":", w)

        self.setWidget(container)
        self.setWidgetResizable(True)

    def _make_widget(self, wtype, opts, val):
        if wtype == "bool":
            w = QCheckBox()
            w.setChecked(val.strip() in ("1", "true", "yes", "on"))
            return w
        if wtype == "choice":
            w = QComboBox()
            w.addItems(opts)
            if val in opts:
                w.setCurrentText(val)
            else:
                w.addItem(val)
                w.setCurrentText(val)
            return w
        return QLineEdit(val)

    def _get_value(self, key: str) -> str:
        w = self._widgets[key]
        if isinstance(w, QCheckBox):
            return "1" if w.isChecked() else "0"
        if isinstance(w, QComboBox):
            return w.currentText()
        if isinstance(w, QLineEdit):
            return w.text()
        return ""

    def apply(self):
        for key, _, _, _ in self._meta:
            self._ini.set(self._section, key, self._get_value(key))


# ── Per-player tab: game settings + controller settings + key binds ───────────

class PlayerTab(QScrollArea):
    def __init__(self, player_num: int, ini: IniFile):
        super().__init__()
        self._ini   = ini
        self._n     = player_num
        self._gsec  = f"Game.Player{player_num}"
        self._isec  = f"Input.Player{player_num}"
        self._bsec  = f"Input.Player{player_num}.Binds"
        self._gwidgets: dict[str, QWidget] = {}
        self._iwidgets: dict[str, QWidget] = {}
        self._bwidgets: dict[str, QLineEdit] = {}

        container = QWidget()
        vbox = QVBoxLayout(container)
        vbox.setSpacing(16)
        vbox.setContentsMargins(16, 16, 16, 16)

        # ── Game / aiming settings ────────────────────────────────────────────
        g_group = QGroupBox("Game & Aiming")
        g_form  = QFormLayout(g_group)
        g_form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        g_form.setSpacing(8)
        for key, label, wtype, opts in PLAYER_GAME_META:
            val = ini.get(self._gsec, key)
            w   = self._make_widget(wtype, opts, val)
            self._gwidgets[key] = w
            g_form.addRow(label + ":", w)
        vbox.addWidget(g_group)

        # ── Controller / deadzone settings ────────────────────────────────────
        i_group = QGroupBox("Controller")
        i_form  = QFormLayout(i_group)
        i_form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        i_form.setSpacing(8)
        for key, label, wtype, opts in PLAYER_INPUT_META:
            val = ini.get(self._isec, key)
            w   = self._make_widget(wtype, opts, val)
            self._iwidgets[key] = w
            i_form.addRow(label + ":", w)
        vbox.addWidget(i_group)

        # ── Key / button binds ────────────────────────────────────────────────
        b_group = QGroupBox("Binds  (comma-separated key names, e.g. MOUSE_LEFT, SPACE, JOY1_RTRIGGER)")
        b_form  = QFormLayout(b_group)
        b_form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        b_form.setSpacing(6)
        hint = QLabel("Enter one or more key names separated by commas. Use NONE for unbound.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #999; font-size: 11px;")
        b_form.addRow(hint)
        for key, label in BIND_LABELS:
            val = ini.get(self._bsec, key, "NONE")
            le  = QLineEdit(val)
            le.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            self._bwidgets[key] = le
            b_form.addRow(label + ":", le)
        vbox.addWidget(b_group)
        vbox.addStretch()

        self.setWidget(container)
        self.setWidgetResizable(True)

    def _make_widget(self, wtype, opts, val):
        if wtype == "bool":
            w = QCheckBox()
            w.setChecked(val.strip() in ("1", "true", "yes", "on"))
            return w
        if wtype == "choice":
            w = QComboBox()
            w.addItems(opts)
            if val in opts:
                w.setCurrentText(val)
            else:
                w.addItem(val)
                w.setCurrentText(val)
            return w
        return QLineEdit(val)

    def _get_val(self, w: QWidget) -> str:
        if isinstance(w, QCheckBox):
            return "1" if w.isChecked() else "0"
        if isinstance(w, QComboBox):
            return w.currentText()
        if isinstance(w, QLineEdit):
            return w.text()
        return ""

    def apply(self):
        for key in self._gwidgets:
            self._ini.set(self._gsec, key, self._get_val(self._gwidgets[key]))
        for key in self._iwidgets:
            self._ini.set(self._isec, key, self._get_val(self._iwidgets[key]))
        for key, le in self._bwidgets.items():
            self._ini.set(self._bsec, key, le.text())


# ── Main window ───────────────────────────────────────────────────────────────

class ConfigWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Perfect Dark Configuration")
        self.setMinimumSize(680, 600)

        if not INI_PATH.exists():
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(
                None, "Config not found",
                f"No config file found at:\n{INI_PATH}\n\n"
                "Run Perfect Dark at least once to generate it.",
            )
            return

        self._ini = IniFile(INI_PATH)

        tabs = QTabWidget()

        self._video_tab = SettingsTab("Video",  VIDEO_META,  self._ini)
        self._audio_tab = SettingsTab("Audio",  AUDIO_META,  self._ini)
        self._game_tab  = SettingsTab("Game",   GAME_META,   self._ini)
        self._input_tab = SettingsTab("Input",  INPUT_META,  self._ini)
        tabs.addTab(self._video_tab, "Video")
        tabs.addTab(self._audio_tab, "Audio")
        tabs.addTab(self._game_tab,  "Game")
        tabs.addTab(self._input_tab, "Mouse / Input")

        self._player_tabs: list[PlayerTab] = []
        for i in range(1, 5):
            pt = PlayerTab(i, self._ini)
            self._player_tabs.append(pt)
            tabs.addTab(pt, f"Player {i}")

        btn_save   = QPushButton("Save")
        btn_cancel = QPushButton("Cancel")
        btn_save.setDefault(True)
        btn_save.clicked.connect(self._save)
        btn_cancel.clicked.connect(self.close)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(btn_save)

        root = QVBoxLayout()
        root.addWidget(tabs)
        root.addLayout(btn_row)

        central = QWidget()
        central.setLayout(root)
        self.setCentralWidget(central)

    def _save(self):
        self._video_tab.apply()
        self._audio_tab.apply()
        self._game_tab.apply()
        self._input_tab.apply()
        for pt in self._player_tabs:
            pt.apply()
        self._ini.save()
        self.statusBar().showMessage("Saved.", 3000)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    from PySide6.QtGui import QPalette, QColor
    pal = QPalette()
    pal.setColor(QPalette.Window,          QColor(45,  45,  45))
    pal.setColor(QPalette.WindowText,      QColor(220, 220, 220))
    pal.setColor(QPalette.Base,            QColor(30,  30,  30))
    pal.setColor(QPalette.AlternateBase,   QColor(50,  50,  50))
    pal.setColor(QPalette.ToolTipBase,     QColor(220, 220, 220))
    pal.setColor(QPalette.ToolTipText,     QColor(220, 220, 220))
    pal.setColor(QPalette.Text,            QColor(220, 220, 220))
    pal.setColor(QPalette.Button,          QColor(60,  60,  60))
    pal.setColor(QPalette.ButtonText,      QColor(220, 220, 220))
    pal.setColor(QPalette.BrightText,      Qt.red)
    pal.setColor(QPalette.Highlight,       QColor(65,  105, 225))
    pal.setColor(QPalette.HighlightedText, Qt.white)
    app.setPalette(pal)

    win = ConfigWindow()
    win.show()
    sys.exit(app.exec())
