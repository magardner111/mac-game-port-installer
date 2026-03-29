#!/usr/bin/env python3
"""Zelda 3 configuration editor."""

import re
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QFileDialog, QFormLayout, QFrame, QGroupBox, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QMainWindow, QPushButton, QScrollArea,
    QSizePolicy, QSpinBox, QTabWidget, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

INI_PATH = Path(__file__).parent / "games/Zelda3/macOS/zelda3.ini"

SNES_BUTTONS = ["Up", "Down", "Left", "Right", "Select", "Start", "A", "B", "X", "Y", "L", "R"]

GAMEPAD_BUTTONS = [
    "", "DpadUp", "DpadDown", "DpadLeft", "DpadRight",
    "A", "B", "X", "Y", "Start", "Back",
    "Lb", "Rb", "L2", "R2", "L3", "R3",
]

# (label, widget_type, options_or_None)
SETTINGS_META = {
    "General": [
        ("Autosave",             "Autosave state on quit/start",              "bool",   None),
        ("DisplayPerfInTitle",   "Display FPS in title bar",                  "bool",   None),
        ("ExtendedAspectRatio",  "Aspect ratio",                              "choice", ["4:3", "16:9", "16:10", "18:9",
                                                                                         "extend_y, 4:3", "extend_y, 16:9",
                                                                                         "extend_y, 16:10"]),
        ("DisableFrameDelay",    "Disable frame delay (for 60 Hz displays)",  "bool",   None),
    ],
    "Graphics": [
        ("WindowSize",      "Window size",                             "str",    None),
        ("Fullscreen",      "Fullscreen mode",                         "choice", ["0", "1", "2"]),
        ("WindowScale",     "Window scale",                            "choice", ["1", "2", "3", "4", "5"]),
        ("NewRenderer",     "Optimized PPU renderer",                  "bool",   None),
        ("EnhancedMode7",   "Enhanced Mode 7 (hi-res world map)",      "bool",   None),
        ("IgnoreAspectRatio","Ignore aspect ratio",                    "bool",   None),
        ("NoSpriteLimits",  "Remove per-scanline sprite limits",       "bool",   None),
        ("LinkGraphics",    "Custom Link sprite (.zspr path)",         "file",   None),
        ("OutputMethod",    "Render output method",                    "choice", ["SDL", "SDL-Software", "OpenGL", "OpenGL ES"]),
        ("LinearFiltering", "Linear filtering (smoother pixels)",      "bool",   None),
        ("Shader",          "GLSL shader path (OpenGL only)",          "file",   None),
        ("DimFlashes",      "Dim flashing effects (Virtual Console)",  "bool",   None),
    ],
    "Sound": [
        ("EnableAudio",    "Enable audio",               "bool",   None),
        ("AudioFreq",      "Sample rate (Hz)",            "choice", ["44100", "48000", "32000", "22050", "11025"]),
        ("AudioChannels",  "Channels",                   "choice", ["1", "2"]),
        ("AudioSamples",   "Buffer size (samples)",       "choice", ["256", "512", "1024", "2048", "4096"]),
        ("EnableMSU",      "MSU-1 music replacement",    "choice", ["false", "true", "deluxe", "opuz", "deluxe-opuz"]),
        ("MSUPath",        "MSU files path",             "str",    None),
        ("ResumeMSU",      "Resume MSU on area re-entry","bool",   None),
        ("MSUVolume",      "MSU volume (0-100%)",        "str",    None),
    ],
    "Features": [
        ("ItemSwitchLR",           "Assign items to L/R buttons",          "bool", None),
        ("ItemSwitchLRLimit",      "Limit L/R cycling to first 4 items",   "bool", None),
        ("TurnWhileDashing",       "Turn while dashing",                   "bool", None),
        ("MirrorToDarkworld",      "Mirror warps to Dark World",           "bool", None),
        ("CollectItemsWithSword",  "Collect items with sword",             "bool", None),
        ("BreakPotsWithSword",     "Break pots with sword (lv2+)",         "bool", None),
        ("DisableLowHealthBeep",   "Disable low health beep",              "bool", None),
        ("SkipIntroOnKeypress",    "Skip intro on keypress",               "bool", None),
        ("ShowMaxItemsInYellow",   "Show max items in yellow",             "bool", None),
        ("MoreActiveBombs",        "4 active bombs instead of 2",          "bool", None),
        ("CarryMoreRupees",        "Carry up to 9999 rupees",              "bool", None),
        ("MiscBugFixes",           "Misc bug fixes",                       "bool", None),
        ("GameChangingBugFixes",   "Game-changing bug fixes",              "bool", None),
        ("CancelBirdTravel",       "Cancel bird travel with X key",        "bool", None),
    ],
}

OTHER_KEYMAP = [
    ("CheatLife",            "Cheat: Fill life"),
    ("CheatKeys",            "Cheat: Get keys"),
    ("CheatWalkThroughWalls","Cheat: Walk through walls"),
    ("ClearKeyLog",          "Clear key log"),
    ("StopReplay",           "Stop replay"),
    ("Fullscreen",           "Toggle fullscreen"),
    ("Reset",                "Reset game"),
    ("Pause",                "Pause (bright)"),
    ("PauseDimmed",          "Pause (dimmed)"),
    ("Turbo",                "Turbo"),
    ("ReplayTurbo",          "Replay turbo"),
    ("WindowBigger",         "Increase window size"),
    ("WindowSmaller",        "Decrease window size"),
    ("VolumeUp",             "Volume up"),
    ("VolumeDown",           "Volume down"),
]

SAVE_SLOTS_KEYMAP = [
    ("Load",   "Load state"),
    ("Save",   "Save state"),
    ("Replay", "Replay"),
]


# ── INI parser that preserves comments ───────────────────────────────────────

class IniFile:
    """Read/write a .ini file preserving all comments and blank lines."""

    def __init__(self, path: Path):
        self.path = path
        self._lines: list[dict] = []   # {"type": "raw"|"setting", ...}
        self._values: dict[tuple, str] = {}  # (section, key) -> value
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
                    key_stripped = key.strip()
                    val_stripped = val.strip()
                    self._lines.append({
                        "type": "setting",
                        "section": section,
                        "key": key_stripped,
                        "text": line,
                    })
                    self._values[(section, key_stripped)] = val_stripped
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


# ── Key capture widget ────────────────────────────────────────────────────────

def _qt_key_to_zelda(key: int, modifiers) -> str:
    """Convert a Qt key+modifiers combo to zelda3 key name format."""
    mod_parts = []
    if modifiers & Qt.ControlModifier:
        mod_parts.append("Ctrl")
    if modifiers & Qt.AltModifier:
        mod_parts.append("Alt")
    if modifiers & Qt.ShiftModifier:
        mod_parts.append("Shift")

    name_map = {
        Qt.Key_Return: "Return", Qt.Key_Enter: "Return",
        Qt.Key_Tab: "Tab", Qt.Key_Escape: "Escape",
        Qt.Key_Backspace: "Backspace", Qt.Key_Delete: "Delete",
        Qt.Key_Space: "Space",
        Qt.Key_Up: "Up", Qt.Key_Down: "Down",
        Qt.Key_Left: "Left", Qt.Key_Right: "Right",
        Qt.Key_Home: "Home", Qt.Key_End: "End",
        Qt.Key_PageUp: "PageUp", Qt.Key_PageDown: "PageDown",
        Qt.Key_Insert: "Insert",
        Qt.Key_Shift: "Shift", Qt.Key_Control: "Ctrl", Qt.Key_Alt: "Alt",
        Qt.Key_Equal: "=", Qt.Key_Minus: "-",
        Qt.Key_BracketLeft: "[", Qt.Key_BracketRight: "]",
        Qt.Key_Semicolon: ";", Qt.Key_Apostrophe: "'",
        Qt.Key_Comma: ",", Qt.Key_Period: ".", Qt.Key_Slash: "/",
        Qt.Key_Backslash: "\\", Qt.Key_Grave: "`",
    }
    for i in range(1, 13):
        name_map[getattr(Qt, f"Key_F{i}")] = f"F{i}"

    if key in name_map:
        key_name = name_map[key]
    elif Qt.Key_A <= key <= Qt.Key_Z:
        # Return lowercase unless Shift is the only modifier
        char = chr(key).lower()
        key_name = char
        if mod_parts == ["Shift"]:
            # Shift+x → just X in zelda notation? No — zelda uses "Shift+x".
            pass
    elif Qt.Key_0 <= key <= Qt.Key_9:
        key_name = chr(key)
    else:
        key_name = QKeySequence(key).toString().lower() or "?"

    # Skip bare modifier-only presses
    if key in (Qt.Key_Shift, Qt.Key_Control, Qt.Key_Alt, Qt.Key_Meta):
        return ""

    if mod_parts:
        return "+".join(mod_parts) + "+" + key_name
    return key_name


class KeyCaptureButton(QPushButton):
    def __init__(self, value: str, parent=None):
        super().__init__(parent)
        self._value = value
        self._capturing = False
        self._update_text()
        self.clicked.connect(self._start_capture)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def _update_text(self):
        self.setText(self._value or "(none)")

    def value(self) -> str:
        return self._value

    def set_value(self, v: str):
        self._value = v
        self._capturing = False
        self._update_text()
        self.setStyleSheet("")

    def _start_capture(self):
        self._capturing = True
        self.setText("Press a key…")
        self.setStyleSheet("background: #3a3a7a; color: white;")
        self.grabKeyboard()

    def keyPressEvent(self, event):
        if not self._capturing:
            return super().keyPressEvent(event)
        key = event.key()
        mods = event.modifiers()
        result = _qt_key_to_zelda(key, mods)
        if result:
            self._value = result
        self._capturing = False
        self._update_text()
        self.setStyleSheet("")
        self.releaseKeyboard()

    def focusOutEvent(self, event):
        if self._capturing:
            self._capturing = False
            self._update_text()
            self.setStyleSheet("")
            self.releaseKeyboard()
        super().focusOutEvent(event)


# ── Settings tab ─────────────────────────────────────────────────────────────

class SettingsTab(QScrollArea):
    def __init__(self, section: str, meta: list, ini: IniFile):
        super().__init__()
        self._section = section
        self._ini = ini
        self._widgets: dict[str, QWidget] = {}

        container = QWidget()
        form = QFormLayout(container)
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form.setSpacing(10)
        form.setContentsMargins(16, 16, 16, 16)

        for key, label, wtype, opts in meta:
            val = ini.get(section, key)
            w = self._make_widget(wtype, opts, val)
            self._widgets[key] = w
            form.addRow(label + ":", w)

        self.setWidget(container)
        self.setWidgetResizable(True)

    def _make_widget(self, wtype, opts, val):
        if wtype == "bool":
            w = QCheckBox()
            w.setChecked(val.strip() in ("1", "true", "yes"))
            return w
        if wtype == "choice":
            w = QComboBox()
            w.addItems(opts)
            if val in opts:
                w.setCurrentText(val)
            else:
                # Add current value if not in list
                w.addItem(val)
                w.setCurrentText(val)
            return w
        if wtype == "file":
            row = QWidget()
            hl = QHBoxLayout(row)
            hl.setContentsMargins(0, 0, 0, 0)
            le = QLineEdit(val)
            le.setObjectName("file_edit")
            btn = QPushButton("Browse…")
            btn.setFixedWidth(72)
            btn.clicked.connect(lambda: self._browse_file(le))
            hl.addWidget(le)
            hl.addWidget(btn)
            return row
        # str default
        w = QLineEdit(val)
        return w

    def _browse_file(self, edit: QLineEdit):
        path, _ = QFileDialog.getOpenFileName(self, "Select file")
        if path:
            edit.setText(path)

    def _get_value(self, key: str) -> str:
        w = self._widgets[key]
        if isinstance(w, QCheckBox):
            return "1" if w.isChecked() else "0"
        if isinstance(w, QComboBox):
            return w.currentText()
        if isinstance(w, QLineEdit):
            return w.text()
        # file row
        le = w.findChild(QLineEdit, "file_edit")
        return le.text() if le else ""

    def apply(self):
        for key, _, wtype, opts in self._get_meta():
            val = self._get_value(key)
            self._ini.set(self._section, key, val)

    def _get_meta(self):
        return SETTINGS_META.get(self._section, [])


# ── Keyboard tab ──────────────────────────────────────────────────────────────

class KeyboardTab(QScrollArea):
    def __init__(self, ini: IniFile):
        super().__init__()
        self._ini = ini
        self._button_captures: list[KeyCaptureButton] = []   # 12, one per SNES button
        self._hotkey_captures: dict[str, KeyCaptureButton] = {}

        container = QWidget()
        vbox = QVBoxLayout(container)
        vbox.setSpacing(16)
        vbox.setContentsMargins(16, 16, 16, 16)

        # ── SNES button → key
        group1 = QGroupBox("SNES Button Mapping")
        form1 = QFormLayout(group1)
        form1.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        controls_str = ini.get("KeyMap", "Controls",
                               "Up, Down, Left, Right, Right Shift, Return, x, z, s, a, c, v")
        controls = [c.strip() for c in controls_str.split(",")]
        while len(controls) < 12:
            controls.append("")

        for i, btn_name in enumerate(SNES_BUTTONS):
            cap = KeyCaptureButton(controls[i] if i < len(controls) else "")
            self._button_captures.append(cap)
            row = QHBoxLayout()
            row.addWidget(cap)
            w = QWidget()
            w.setLayout(row)
            form1.addRow(f"{btn_name}:", cap)

        vbox.addWidget(group1)

        # ── Hotkeys
        group2 = QGroupBox("Hotkeys")
        form2 = QFormLayout(group2)
        form2.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        for key, label in OTHER_KEYMAP:
            cap = KeyCaptureButton(ini.get("KeyMap", key))
            self._hotkey_captures[key] = cap
            form2.addRow(label + ":", cap)

        vbox.addWidget(group2)

        # ── Save/Load/Replay slots (10 slots each, compact table)
        group3 = QGroupBox("Save / Load / Replay slots  (F1–F10)")
        g3_layout = QVBoxLayout(group3)
        self._slot_table = QTableWidget(10, 3)
        self._slot_table.setHorizontalHeaderLabels(["Load", "Save", "Replay"])
        self._slot_table.verticalHeader().setVisible(True)
        self._slot_table.setVerticalHeaderLabels([f"Slot {i+1}" for i in range(10)])
        self._slot_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._slot_table.setFixedHeight(260)

        for col_i, (key, _) in enumerate(SAVE_SLOTS_KEYMAP):
            raw = ini.get("KeyMap", key)
            slots = [s.strip() for s in raw.split(",")]
            while len(slots) < 10:
                slots.append("")
            for row_i in range(10):
                self._slot_table.setItem(row_i, col_i, QTableWidgetItem(slots[row_i]))

        g3_layout.addWidget(self._slot_table)
        vbox.addWidget(group3)
        vbox.addStretch()

        self.setWidget(container)
        self.setWidgetResizable(True)

    def apply(self):
        # Controls line
        controls = [cap.value() for cap in self._button_captures]
        self._ini.set("KeyMap", "Controls", ", ".join(controls))
        # Hotkeys
        for key, cap in self._hotkey_captures.items():
            self._ini.set("KeyMap", key, cap.value())
        # Slot tables
        for col_i, (key, _) in enumerate(SAVE_SLOTS_KEYMAP):
            slots = []
            for row_i in range(10):
                item = self._slot_table.item(row_i, col_i)
                slots.append(item.text() if item else "")
            self._ini.set("KeyMap", key, ", ".join(slots))


# ── Gamepad tab ───────────────────────────────────────────────────────────────

class GamepadTab(QScrollArea):
    def __init__(self, ini: IniFile):
        super().__init__()
        self._ini = ini
        self._combos: list[QComboBox] = []

        container = QWidget()
        vbox = QVBoxLayout(container)
        vbox.setSpacing(12)
        vbox.setContentsMargins(16, 16, 16, 16)

        info = QLabel(
            "Map each SNES button to a gamepad button.\n"
            "Common values: DpadUp/Down/Left/Right, A, B, X, Y, Start, Back, Lb, Rb, L2, R2, L3, R3"
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: #aaa; font-size: 12px;")
        vbox.addWidget(info)

        group = QGroupBox("SNES Button → Gamepad Button")
        form = QFormLayout(group)
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

        controls_str = ini.get("GamepadMap", "Controls",
                               "DpadUp, DpadDown, DpadLeft, DpadRight, Back, Start, B, A, Y, X, Lb, Rb")
        controls = [c.strip() for c in controls_str.split(",")]
        while len(controls) < 12:
            controls.append("")

        for i, btn_name in enumerate(SNES_BUTTONS):
            combo = QComboBox()
            combo.setEditable(True)
            combo.addItems(GAMEPAD_BUTTONS)
            val = controls[i] if i < len(controls) else ""
            if val in GAMEPAD_BUTTONS:
                combo.setCurrentText(val)
            else:
                combo.setCurrentText(val)
            self._combos.append(combo)
            form.addRow(f"{btn_name}:", combo)

        vbox.addWidget(group)
        vbox.addStretch()

        self.setWidget(container)
        self.setWidgetResizable(True)

    def apply(self):
        vals = [c.currentText() for c in self._combos]
        self._ini.set("GamepadMap", "Controls", ", ".join(vals))


# ── Main window ───────────────────────────────────────────────────────────────

class ConfigWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Zelda 3 Configuration")
        self.setMinimumSize(640, 560)

        if not INI_PATH.exists():
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(None, "Error", f"Config file not found:\n{INI_PATH}")
            sys.exit(1)

        self._ini = IniFile(INI_PATH)

        tabs = QTabWidget()
        self._setting_tabs: list[SettingsTab] = []

        for section, meta in SETTINGS_META.items():
            tab = SettingsTab(section, meta, self._ini)
            self._setting_tabs.append(tab)
            tabs.addTab(tab, section)

        self._kb_tab = KeyboardTab(self._ini)
        tabs.addTab(self._kb_tab, "Keyboard")

        self._gp_tab = GamepadTab(self._ini)
        tabs.addTab(self._gp_tab, "Gamepad")

        # Bottom buttons
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
        for tab in self._setting_tabs:
            tab.apply()
        self._kb_tab.apply()
        self._gp_tab.apply()
        self._ini.save()
        self.statusBar().showMessage("Saved.", 3000)

    def _get_meta(self):
        # Helper so SettingsTab can reach its own meta
        pass


# ── Patch SettingsTab._get_meta to work correctly ────────────────────────────

def _patched_get_meta(self):
    return SETTINGS_META.get(self._section, [])

SettingsTab._get_meta = _patched_get_meta


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # Dark palette
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
