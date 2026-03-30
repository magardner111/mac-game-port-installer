"""
ZSNES-style visual theme for the game port installer.

Colour palette, QSS stylesheet, helper widgets, and font loading are all
defined here so main.py stays focused on behaviour.
"""

import random
from pathlib import Path

try:
    import numpy as _np
    _HAS_NUMPY = True
except ImportError:
    _HAS_NUMPY = False

from collections import deque

from PySide6.QtCore import Qt, QEvent, QObject, QPoint, QRect, QSize, QTimer, QUrl

try:
    from PySide6.QtMultimedia import QSoundEffect as _QSoundEffect
    _HAS_SOUND = True
except ImportError:
    _HAS_SOUND = False
from PySide6.QtGui import (
    QColor, QFont, QFontDatabase, QFontMetrics,
    QPainter, QPen, QPixmap,
)
from PySide6.QtGui import QCursor, QPalette
from PySide6.QtWidgets import (
    QAbstractButton, QApplication, QLabel, QPushButton,
    QProxyStyle, QSizePolicy, QStyle,
    QStyleOptionButton, QStyleOptionViewItem,
    QStyledItemDelegate, QWidget,
)

# ── Palette ────────────────────────────────────────────────────────────────────

BG          = "#14145a"   # main window background — dark navy (readable)
BG_PANEL    = "#1a1a70"   # sidebar / tree panel bg
BG_ROW_ALT  = "#101060"   # alternating row tint

BG_DIALOG   = "#2020a0"   # dialog / options window background (medium blue)
BG_TITLE    = "#4848c0"   # dialog title bar (lighter strip)
BG_TAB      = "#4040b0"   # tab bar strip

BEVEL_HI    = "#7070d0"   # top-left bevel highlight
BEVEL_LO    = "#000018"   # bottom-right bevel shadow
BEVEL_MID   = "#2a2a90"   # inner face of a raised element on dialog bg

CYAN        = "#00e8ff"   # item labels / headings
YELLOW      = "#ffff00"   # section headers (SYSTEM:, ROM:, etc.)
GREEN       = "#00ff00"   # installed / success / directory items
RED         = "#ff3030"   # error / not installed / checkbox tick colour
WHITE       = "#ffffff"   # general body text
GREY        = "#a0a0c0"   # disabled / secondary text / inactive tab
ORANGE      = "#ff8800"   # warnings / pending
MAGENTA     = "#d4308a"   # selected list item background (pink highlight bar)

SEL_BG      = MAGENTA     # selected row background
SEL_FG      = WHITE       # selected row text

# ── Font ───────────────────────────────────────────────────────────────────────

_FONT_LOADED = False
PIXEL_FAMILY = "Press Start 2P"


def load_pixel_font() -> str:
    """
    Register the bundled Press Start 2P TTF with Qt and return its family name.
    Falls back to a system monospace font if the file is missing.
    """
    global _FONT_LOADED
    if not _FONT_LOADED:
        ttf = Path(__file__).parent / "assets" / "PressStart2P.ttf"
        if ttf.exists():
            QFontDatabase.addApplicationFont(str(ttf))
        _FONT_LOADED = True
    # Verify Qt can find it
    if PIXEL_FAMILY in QFontDatabase.families():
        return PIXEL_FAMILY
    return "Courier"   # fallback


def pixel_font(size: int = 7, bold: bool = False) -> QFont:
    f = QFont(load_pixel_font(), size)
    f.setBold(bold)
    f.setCapitalization(QFont.Capitalization.AllUppercase)
    # Disable hinting / sub-pixel — keeps pixels sharp
    f.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    return f


# ── Stylesheet ─────────────────────────────────────────────────────────────────

def stylesheet() -> str:
    return f"""
/* ── Global ──────────────────────────────────────────────────────── */
* {{
    font-family: "{PIXEL_FAMILY}", "Courier New", monospace;
    font-size: 7pt;
    color: {GREEN};
    background-color: {BG};
    border: none;
    outline: none;
}}

QMainWindow {{
    background-color: {BG};
}}

/* Dialogs use the lighter medium-blue background */
QDialog {{
    background-color: {BG_DIALOG};
}}
QDialog QWidget {{
    background-color: {BG_DIALOG};
}}
QDialog QLabel {{
    background: transparent;
    color: {GREEN};
}}
QDialog QPushButton {{
    background-color: {BEVEL_MID};
}}
QDialog QPushButton:hover {{
    background-color: {BG_TAB};
}}

/* ── Labels ──────────────────────────────────────────────────────── */
QLabel {{
    background: transparent;
    color: {GREEN};
}}
QLabel[class="section"] {{
    color: {YELLOW};
}}
QLabel[class="cyan"] {{
    color: {CYAN};
}}
QLabel[class="green"] {{
    color: {GREEN};
}}
QLabel[class="red"] {{
    color: {RED};
}}

/* ── Buttons ─────────────────────────────────────────────────────── */
QPushButton {{
    background-color: {BG_PANEL};
    color: {CYAN};
    padding: 4px 10px;
    border-top:    1px solid {BEVEL_HI};
    border-left:   1px solid {BEVEL_HI};
    border-bottom: 1px solid {BEVEL_LO};
    border-right:  1px solid {BEVEL_LO};
    min-height: 18px;
}}
QPushButton:hover {{
    color: {YELLOW};
    background-color: {BEVEL_MID};
}}
QPushButton:pressed {{
    background-color: {BG};
    border-top:    1px solid {BEVEL_LO};
    border-left:   1px solid {BEVEL_LO};
    border-bottom: 1px solid {BEVEL_HI};
    border-right:  1px solid {BEVEL_HI};
}}
QPushButton:disabled {{
    color: {GREY};
    background-color: {BG};
    border-top:    1px solid {GREY};
    border-left:   1px solid {GREY};
    border-bottom: 1px solid {GREY};
    border-right:  1px solid {GREY};
}}
QPushButton[class="primary"] {{
    color: {GREEN};
    border-top:    1px solid {GREEN};
    border-left:   1px solid {GREEN};
    border-bottom: 1px solid {BEVEL_LO};
    border-right:  1px solid {BEVEL_LO};
}}
QPushButton[class="danger"] {{
    color: {RED};
    border-top:    1px solid {RED};
    border-left:   1px solid {RED};
    border-bottom: 1px solid {BEVEL_LO};
    border-right:  1px solid {BEVEL_LO};
}}

/* ── Tree / list ─────────────────────────────────────────────────── */
QTreeWidget, QListWidget {{
    background-color: {BG};
    alternate-background-color: {BG_ROW_ALT};
    color: {GREEN};
    border-top:    1px solid {BEVEL_LO};
    border-left:   1px solid {BEVEL_LO};
    border-bottom: 1px solid {BEVEL_HI};
    border-right:  1px solid {BEVEL_HI};
    selection-background-color: {SEL_BG};
    selection-color: {SEL_FG};
    show-decoration-selected: 1;
    outline: none;
}}
QTreeWidget::item {{
    padding: 3px 4px;
    border: none;
}}
QTreeWidget::item:selected,
QTreeWidget::item:selected:active,
QTreeWidget::item:selected:!active {{
    background-color: {SEL_BG};
    color: {SEL_FG};
}}
QHeaderView::section {{
    background-color: {BG_PANEL};
    color: {CYAN};
    padding: 3px 6px;
    border: none;
    border-bottom: 1px solid {BEVEL_HI};
    border-right:  1px solid {BEVEL_LO};
}}
QTreeWidget::branch {{
    background: {BG};
}}
QTreeWidget::branch:selected {{
    background: {SEL_BG};
}}

/* ── Scrollbars ──────────────────────────────────────────────────── */
QScrollBar:vertical {{
    background: {BG_PANEL};
    width: 12px;
    margin: 12px 0 12px 0;
    border-left: 1px solid {BEVEL_LO};
}}
QScrollBar::handle:vertical {{
    background: {BG_TAB};
    border-top:    1px solid {BEVEL_HI};
    border-left:   1px solid {BEVEL_HI};
    border-bottom: 1px solid {BEVEL_LO};
    border-right:  1px solid {BEVEL_LO};
    min-height: 16px;
}}
QScrollBar::handle:vertical:hover {{ background: {SEL_BG}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    background: {BG_PANEL};
    height: 12px;
    border: 1px solid {BEVEL_LO};
}}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: {BG};
}}
QScrollBar:horizontal {{ height: 0px; }}
QAbstractScrollArea::corner {{
    background-color: {BG};
    border: none;
    border-radius: 0px;
}}
QScrollBar:vertical, QScrollBar:horizontal,
QScrollBar::handle:vertical, QScrollBar::handle:horizontal,
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    border-radius: 0px;
}}

/* ── Progress bar ────────────────────────────────────────────────── */
QProgressBar {{
    background-color: {BG_PANEL};
    color: {CYAN};
    text-align: center;
    border-top:    1px solid {BEVEL_LO};
    border-left:   1px solid {BEVEL_LO};
    border-bottom: 1px solid {BEVEL_HI};
    border-right:  1px solid {BEVEL_HI};
    height: 14px;
}}
QProgressBar::chunk {{
    background-color: {GREEN};
}}

/* ── Status bar ──────────────────────────────────────────────────── */
QStatusBar {{
    background-color: {BG_TAB};
    color: {CYAN};
    border-top: 1px solid {BEVEL_LO};
}}
QStatusBar::item {{
    border: none;
}}
QStatusBar QLabel {{
    background-color: {BG_TAB};
    color: {CYAN};
}}
QSizeGrip {{
    background-color: {BG_TAB};
    border: none;
}}

/* ── Combo box ───────────────────────────────────────────────────── */
QComboBox {{
    background-color: {BG_PANEL};
    color: {YELLOW};
    padding: 2px 6px;
    border-top:    1px solid {BEVEL_LO};
    border-left:   1px solid {BEVEL_LO};
    border-bottom: 1px solid {BEVEL_HI};
    border-right:  1px solid {BEVEL_HI};
    min-height: 18px;
}}
QComboBox QAbstractItemView {{
    background-color: {BG_PANEL};
    color: {GREEN};
    selection-background-color: {SEL_BG};
    selection-color: {WHITE};
    border: 1px solid {BEVEL_HI};
    outline: 0;
}}
QComboBox QAbstractItemView::item {{
    color: {GREEN};
    background-color: {BG_PANEL};
    padding: 4px 6px;
    min-height: 20px;
}}
QComboBox QAbstractItemView::item:selected {{
    background-color: {SEL_BG};
    color: {WHITE};
}}
QComboBox::drop-down {{ border: none; width: 16px; }}

/* ── Line edit ───────────────────────────────────────────────────── */
QLineEdit {{
    background-color: {BG_PANEL};
    color: {YELLOW};
    padding: 2px 4px;
    border-top:    1px solid {BEVEL_LO};
    border-left:   1px solid {BEVEL_LO};
    border-bottom: 1px solid {BEVEL_HI};
    border-right:  1px solid {BEVEL_HI};
    selection-background-color: {SEL_BG};
    min-height: 18px;
}}

/* ── Checkbox — grey square, red tick when checked ───────────────── */
QCheckBox {{
    color: {GREEN};
    spacing: 8px;
    background: transparent;
}}
QCheckBox::indicator {{
    width: 12px;
    height: 12px;
    background-color: {GREY};
    border-top:    1px solid {BEVEL_HI};
    border-left:   1px solid {BEVEL_HI};
    border-bottom: 1px solid {BEVEL_LO};
    border-right:  1px solid {BEVEL_LO};
}}
QCheckBox::indicator:checked {{
    background-color: {GREY};
    image: url(assets/checkmark.png);
}}

/* ── Group box (section) ─────────────────────────────────────────── */
QGroupBox {{
    color: {YELLOW};
    border-top:    1px solid {BEVEL_HI};
    border-left:   1px solid {BEVEL_HI};
    border-bottom: 1px solid {BEVEL_LO};
    border-right:  1px solid {BEVEL_LO};
    margin-top: 16px;
    padding-top: 6px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 4px;
    color: {YELLOW};
    background: transparent;
}}

/* ── Message box ─────────────────────────────────────────────────── */
QMessageBox {{
    background-color: {BG_DIALOG};
}}
QMessageBox QLabel {{
    color: {GREEN};
    background: transparent;
}}

/* ── Scroll area ─────────────────────────────────────────────────── */
QScrollArea {{ border: none; background: transparent; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}

/* ── Tab widget (fallback) ───────────────────────────────────────── */
QTabBar::tab {{
    background: {BG_TAB};
    color: {GREY};
    padding: 4px 14px;
    border-top:    1px solid {BEVEL_HI};
    border-left:   1px solid {BEVEL_HI};
    border-right:  1px solid {BEVEL_LO};
    border-bottom: none;
}}
QTabBar::tab:selected {{
    background: {BG_DIALOG};
    color: {CYAN};
}}
QTabWidget::pane {{
    background-color: {BG_DIALOG};
    border-top: 1px solid {BEVEL_HI};
}}
"""


# ── Custom widgets ─────────────────────────────────────────────────────────────

class PixelTabBar(QWidget):
    """
    A ZSNES-style horizontal tab bar.

    Left side: a small ↓ arrow button (decorative, matches ZSNES).
    Then each tab as a beveled raised button.
    Active tab is brighter; inactive tabs are dimmer.
    Emits ``tab_changed(index)`` when a tab is clicked.
    """

    from PySide6.QtCore import Signal
    tab_changed = Signal(int)

    _ARROW_W = 18   # width of the ↓ glyph area on the left

    def __init__(self, labels: list[str], parent=None):
        super().__init__(parent)
        self._labels   = labels
        self._current  = 0
        self._rects: list[QRect] = []   # one per tab (excludes arrow)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFont(pixel_font(7))

    def current(self) -> int:
        return self._current

    def set_current(self, idx: int):
        if 0 <= idx < len(self._labels):
            self._current = idx
            self.update()

    def sizeHint(self) -> QSize:
        fm = QFontMetrics(self.font())
        h  = fm.height() + 14
        return QSize(self.width(), h)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def paintEvent(self, _event):
        p  = QPainter(self)
        fm = QFontMetrics(self.font())
        h  = self.height()
        hi = QColor(BEVEL_HI)
        lo = QColor(BEVEL_LO)

        # ── Strip background ──────────────────────────────────────
        p.fillRect(self.rect(), QColor(BG_TAB))

        # ── ↓ arrow cell on the far left ─────────────────────────
        ar = QRect(0, 0, self._ARROW_W, h)
        p.fillRect(ar, QColor(BG_TAB))
        p.setPen(QPen(hi, 1))
        p.drawLine(ar.left(), ar.top(), ar.right()-1, ar.top())
        p.drawLine(ar.left(), ar.top(), ar.left(),    ar.bottom())
        p.setPen(QPen(lo, 1))
        p.drawLine(ar.right(), ar.top(), ar.right(), ar.bottom())
        # draw a small downward triangle
        mid = ar.center()
        p.setPen(QPen(QColor(WHITE), 1))
        for row in range(4):
            x0 = mid.x() - row
            x1 = mid.x() + row
            y  = mid.y() - 2 + row
            p.drawLine(x0, y, x1, y)

        # ── Tabs ─────────────────────────────────────────────────
        x = self._ARROW_W
        self._rects.clear()

        for i, label in enumerate(self._labels):
            tw   = fm.horizontalAdvance(label)
            w    = tw + 22
            rect = QRect(x, 0, w, h)
            self._rects.append(rect)
            active = (i == self._current)

            fill = QColor(BG_DIALOG if active else BG_TAB)
            p.fillRect(rect, fill)

            p.setPen(QPen(hi, 1))
            p.drawLine(rect.left(),    rect.top(),    rect.right()-1, rect.top())
            p.drawLine(rect.left(),    rect.top(),    rect.left(),    rect.bottom()-1)
            p.setPen(QPen(lo, 1))
            p.drawLine(rect.right(),   rect.top(),    rect.right(),   rect.bottom())
            if not active:
                p.drawLine(rect.left(), rect.bottom(), rect.right(), rect.bottom())

            text_col = QColor(CYAN if active else GREY)
            p.setPen(QPen(text_col, 1))
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, label)

            x += w

        # ── Remaining strip to the right of last tab ─────────────
        if x < self.width():
            rest = QRect(x, 0, self.width() - x, h)
            p.fillRect(rest, QColor(BG_TAB))
            p.setPen(QPen(lo, 1))
            p.drawLine(rest.left(), rest.bottom(), rest.right(), rest.bottom())

    def mousePressEvent(self, event):
        for i, rect in enumerate(self._rects):
            if rect.contains(event.position().toPoint()):
                if i != self._current:
                    self._current = i
                    self.update()
                    self.tab_changed.emit(i)
                break


class BevelFrame(QWidget):
    """A simple inset or raised bevel border container."""

    def __init__(self, raised: bool = True, parent=None):
        super().__init__(parent)
        self._raised = raised

    def paintEvent(self, _event):
        p  = QPainter(self)
        r  = self.rect().adjusted(0, 0, -1, -1)
        hi = QColor(BEVEL_HI if self._raised else BEVEL_LO)
        lo = QColor(BEVEL_LO if self._raised else BEVEL_HI)
        p.setPen(QPen(hi, 1))
        p.drawLine(r.left(),  r.top(),    r.right(),  r.top())
        p.drawLine(r.left(),  r.top(),    r.left(),   r.bottom())
        p.setPen(QPen(lo, 1))
        p.drawLine(r.right(), r.top(),    r.right(),  r.bottom())
        p.drawLine(r.left(),  r.bottom(), r.right(),  r.bottom())


class ZDialog(QWidget):
    """
    A frameless top-level window that draws its own ZSNES-style title bar
    (medium-blue strip with left-aligned title text and a pixel ✕ button).
    """

    def __init__(self, title: str, parent=None):
        from PySide6.QtCore import Qt as _Qt
        from PySide6.QtWidgets import QVBoxLayout as _VBL
        super().__init__(parent, _Qt.Window | _Qt.FramelessWindowHint)
        self.setAttribute(_Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"background-color: {BG_DIALOG};")
        self._title      = title.upper()
        self._title_h    = 22
        self._drag_pos   = None

        outer = _VBL(self)
        outer.setContentsMargins(2, self._title_h + 2, 2, 2)
        outer.setSpacing(0)

        self.content = QWidget(self)
        self.content.setStyleSheet(f"background-color: {BG_DIALOG};")
        outer.addWidget(self.content)

    # ── Custom title bar painting ─────────────────────────────────────────────

    def paintEvent(self, _event):
        p   = QPainter(self)
        hi  = QColor(BEVEL_HI)
        lo  = QColor(BEVEL_LO)
        r   = self.rect()

        # outer bevel
        p.setPen(QPen(hi, 1))
        p.drawLine(r.left(), r.top(), r.right()-1, r.top())
        p.drawLine(r.left(), r.top(), r.left(),    r.bottom()-1)
        p.setPen(QPen(lo, 1))
        p.drawLine(r.right(), r.top(),    r.right(),   r.bottom())
        p.drawLine(r.left(),  r.bottom(), r.right(),   r.bottom())

        # title bar strip
        title_rect = QRect(1, 1, r.width()-2, self._title_h)
        p.fillRect(title_rect, QColor(BG_TITLE))

        # title text
        p.setFont(pixel_font(7))
        p.setPen(QPen(QColor(WHITE), 1))
        p.drawText(title_rect.adjusted(6, 0, -24, 0),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   self._title)

        # ✕ button area
        close_rect = self._close_rect()
        p.fillRect(close_rect, QColor(BG_PANEL))
        p.setPen(QPen(QColor(BEVEL_HI), 1))
        p.drawLine(close_rect.left(), close_rect.top(),
                   close_rect.right()-1, close_rect.top())
        p.drawLine(close_rect.left(), close_rect.top(),
                   close_rect.left(), close_rect.bottom()-1)
        p.setPen(QPen(QColor(BEVEL_LO), 1))
        p.drawLine(close_rect.right(), close_rect.top(),
                   close_rect.right(), close_rect.bottom())
        p.drawLine(close_rect.left(), close_rect.bottom(),
                   close_rect.right(), close_rect.bottom())
        p.setPen(QPen(QColor(GREY), 1))
        m = close_rect.adjusted(4, 4, -4, -4)
        p.drawLine(m.topLeft(), m.bottomRight())
        p.drawLine(m.topRight(), m.bottomLeft())

    def _close_rect(self) -> QRect:
        w = self.width()
        return QRect(w - 20, 2, 18, self._title_h - 2)

    def mousePressEvent(self, event):
        if self._close_rect().contains(event.position().toPoint()):
            self.close()
        elif event.position().y() < self._title_h:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        if self._drag_pos is not None:
            self.move(event.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, _event):
        self._drag_pos = None


# ── All-caps proxy style + label filter ────────────────────────────────────────

class UpperCaseStyle(QProxyStyle):
    """
    Uppercases text drawn through the Qt style system:
    buttons, checkboxes, tabs, item-view rows, etc.
    QLabel bypasses the style system entirely (uses QPainter.drawText
    directly), so those are handled separately by UpperCaseLabelFilter.
    """

    _TEXT_CONTROLS = {
        QStyle.ControlElement.CE_PushButtonLabel,
        QStyle.ControlElement.CE_CheckBoxLabel,
        QStyle.ControlElement.CE_RadioButtonLabel,
        QStyle.ControlElement.CE_TabBarTabLabel,
        QStyle.ControlElement.CE_ToolButtonLabel,
        QStyle.ControlElement.CE_MenuItem,
    }

    def drawItemText(self, painter, rect, flags, palette, enabled, text,
                     textRole=QPalette.ColorRole.NoRole):
        super().drawItemText(painter, rect, flags, palette, enabled,
                             text.upper(), textRole)

    def drawControl(self, element, option, painter, widget=None):
        if element in self._TEXT_CONTROLS:
            opt = QStyleOptionButton(option)
            opt.text = opt.text.upper()
            super().drawControl(element, opt, painter, widget)
        elif element == QStyle.ControlElement.CE_ItemViewItem:
            opt = QStyleOptionViewItem(option)
            opt.text = opt.text.upper()
            super().drawControl(element, opt, painter, widget)
        else:
            super().drawControl(element, option, painter, widget)


class UpperCaseLabelFilter(QObject):
    """
    Application-level event filter that uppercases QLabel text.
    On Polish (first show) it uppercases existing text and monkey-patches
    setText so future updates are also uppercased.
    """

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Polish and isinstance(obj, QLabel):
            t = obj.text()
            if t:
                QLabel.setText(obj, t.upper())
            # Patch this instance so every future setText is also uppercased
            orig = QLabel.setText
            obj.setText = lambda text, _o=obj, _f=orig: _f(_o, text.upper() if text else text)
        return False   # never consume the event


class UpperCaseDelegate(QStyledItemDelegate):
    """
    Item delegate that uppercases text for QTreeWidget / QListWidget rows.
    This is the reliable path — QStyledItemDelegate.initStyleOption IS
    properly dispatched from Python in PySide6.
    """
    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        option.text = option.text.upper()


def install_uppercase_filter(app) -> UpperCaseLabelFilter:
    """Register the label uppercase filter on the QApplication."""
    f = UpperCaseLabelFilter(app)
    app.installEventFilter(f)
    return f


# ── Label helpers ──────────────────────────────────────────────────────────────

def cyan_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(f"color: {CYAN}; background: transparent;")
    return lbl


def yellow_label(text: str) -> QLabel:
    """Yellow section header — matches ZSNES OPTIONS dialog style."""
    lbl = QLabel(text.upper())
    lbl.setStyleSheet(f"color: {YELLOW}; background: transparent;")
    return lbl


def section_label(text: str) -> QLabel:
    """Alias for yellow_label for use as a section/group header."""
    return yellow_label(text)


def status_label(text: str, color: str = WHITE) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(f"color: {color}; background: transparent;")
    return lbl


# ── Animated cursor ─────────────────────────────────────────────────────────────

class CursorAnimator(QObject):
    """
    Cycles through a directory of frame_NN.png files as an app-wide
    animated cursor using QApplication.setOverrideCursor /
    changeOverrideCursor.

    Keep a reference to the returned object — garbage-collecting it stops
    the animation.

    Usage:
        anim = CursorAnimator(Path("assets/cursor_frames"), hotspot_x=8, hotspot_y=3)
        anim.start()
    """

    _HOTSPOT_X = 8
    _HOTSPOT_Y = 3
    _FPS       = 4.25

    def __init__(self, frames_dir: Path,
                 hotspot_x: int = _HOTSPOT_X,
                 hotspot_y: int = _HOTSPOT_Y,
                 fps: float = _FPS,
                 parent=None):
        super().__init__(parent)
        self._cursors: list[QCursor] = []
        for png in sorted(frames_dir.glob("frame_*.png")):
            px = QPixmap(str(png))
            if not px.isNull():
                self._cursors.append(QCursor(px, hotspot_x, hotspot_y))
        self._idx = 0
        self._timer = QTimer(self)
        self._timer.setInterval(int(1000 / fps))
        self._timer.timeout.connect(self._advance)

    def start(self):
        if not self._cursors:
            return
        QApplication.setOverrideCursor(self._cursors[0])
        if len(self._cursors) > 1:
            self._timer.start()

    def stop(self):
        self._timer.stop()
        QApplication.restoreOverrideCursor()

    def _advance(self):
        self._idx = (self._idx + 1) % len(self._cursors)
        QApplication.changeOverrideCursor(self._cursors[self._idx])


# ── Snow overlay ────────────────────────────────────────────────────────────────

class SnowOverlay(QWidget):
    """
    Transparent overlay that draws ZSNES-style falling snow on top of
    whatever widget it is parented to.

    - Passes all mouse / keyboard events through to the parent.
    - Automatically resizes to match the parent.
    - Call start() / stop() to toggle; or use the enabled property.

    Typical use:
        snow = SnowOverlay(main_window)
        snow.start()
    """

    # Tune these to taste
    _FLAKE_COUNT = 180
    _FPS         = 30
    _COLOURS = [
        QColor(255, 255, 255, 220),   # bright white
        QColor(220, 230, 255, 180),   # faint blue-white
        QColor(200, 210, 255, 140),   # dim blue-white
        QColor(255, 255, 255, 100),   # very faint white
    ]

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self._flakes: list[dict] = []
        self._timer = QTimer(self)
        self._timer.setInterval(1000 // self._FPS)
        self._timer.timeout.connect(self._tick)
        self._init_flakes()
        self.resize(parent.size())
        self.raise_()

    # ── Flake management ──────────────────────────────────────────────────────

    def _make_flake(self, randomise_y: bool = True) -> dict:
        w = max(self.width(), 1)
        h = max(self.height(), 1)
        return {
            "x":     random.uniform(0, w),
            "y":     random.uniform(0, h) if randomise_y else random.uniform(-h * 0.1, 0),
            "speed": random.uniform(0.6, 2.5),          # pixels per frame
            "drift": random.uniform(-0.3, 0.3),          # horizontal wobble
            "size":  random.choice([1, 1, 1, 2]),        # mostly 1-px
            "color": random.choice(self._COLOURS),
        }

    def _init_flakes(self):
        self._flakes = [self._make_flake(randomise_y=True)
                        for _ in range(self._FLAKE_COUNT)]

    def _tick(self):
        h = self.height()
        w = self.width()
        for f in self._flakes:
            f["y"] += f["speed"]
            f["x"] += f["drift"]
            # Wrap horizontally
            if f["x"] < 0:
                f["x"] += w
            elif f["x"] > w:
                f["x"] -= w
            # Reset when it falls off the bottom
            if f["y"] > h:
                f.update(self._make_flake(randomise_y=False))
        self.update()

    # ── Painting ──────────────────────────────────────────────────────────────

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        for f in self._flakes:
            p.fillRect(int(f["x"]), int(f["y"]), f["size"], f["size"], f["color"])

    # ── Resize tracking ───────────────────────────────────────────────────────

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._init_flakes()

    # ── Public API ────────────────────────────────────────────────────────────

    def start(self):
        self.show()
        self.raise_()
        self._timer.start()

    def stop(self):
        self._timer.stop()
        self.hide()

    def is_running(self) -> bool:
        return self._timer.isActive()


# ── Fire overlay ────────────────────────────────────────────────────────────────

class FireOverlay(QWidget):
    """
    Classic demo-scene fire effect: heat seeded at the bottom, diffused
    upward with random cooling, mapped through a black→red→orange→yellow
    colour palette.  Requires numpy for fast vectorised updates.

    Usage:
        fire = FireOverlay(main_window.centralWidget())
        fire.start()
    """

    _FPS   = 30
    _SCALE = 5    # screen pixels per fire cell

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self._fire   = None
        self._fw     = 0
        self._fh     = 0
        self._pal    = None
        self._imgbuf = None

        self._timer = QTimer(self)
        self._timer.setInterval(1000 // self._FPS)
        self._timer.timeout.connect(self._tick)

        if _HAS_NUMPY:
            self._build_palette()
            self._init_fire()

        self.resize(parent.size())
        self.raise_()

    def _build_palette(self):
        pal = _np.zeros((256, 4), dtype=_np.uint8)
        for i in range(256):
            if i == 0:
                r, g, b, a = 0, 0, 0, 0
            elif i < 64:
                r = min(255, i * 4); g = 0; b = 0; a = min(255, i * 4)
            elif i < 128:
                r = 255; g = min(255, (i - 64) * 4); b = 0; a = 220
            elif i < 192:
                r = 255; g = 255; b = min(255, (i - 128) * 4); a = 230
            else:
                r = 255; g = 255; b = min(255, 128 + (i - 192) * 4); a = 200
            pal[i] = [r, g, b, a]
        self._pal = pal

    def _init_fire(self):
        w = max(self.width()  // self._SCALE, 4)
        h = max(self.height() // self._SCALE, 4)
        self._fw = w
        self._fh = h
        self._fire = _np.zeros((h, w), dtype=_np.int32)

    def _tick(self):
        if self._fire is None:
            return
        fire = self._fire
        h, w = fire.shape
        fire[-1, :] = _np.random.randint(210, 256, w)
        below       = fire[1:, :]
        left_below  = _np.roll(below,  1, axis=1)
        right_below = _np.roll(below, -1, axis=1)
        avg     = (below.astype(_np.int32) + left_below + right_below) // 3
        cooling = _np.random.randint(0, 22, (h - 1, w))
        fire[:-1, :] = _np.clip(avg - cooling, 0, 255)
        self.update()

    def paintEvent(self, _event):
        if not _HAS_NUMPY or self._fire is None or self._pal is None:
            return
        from PySide6.QtGui import QImage
        u8   = self._fire.astype(_np.uint8)
        rgba = self._pal[u8].copy()          # (fh, fw, 4) — writable copy

        # Vertical alpha gradient: fully transparent at top, opaque at bottom.
        # Fire fades in over the bottom 35% of the overlay height so it never
        # obscures items above that zone.
        fh = rgba.shape[0]
        fade_rows = int(fh * 0.35)           # transition band (fire cells)
        grad = _np.zeros(fh, dtype=_np.float32)
        grad[-fade_rows:] = _np.linspace(0.0, 1.0, fade_rows)
        grad = (grad ** 1.5)                 # steepen the curve
        rgba[:, :, 3] = (rgba[:, :, 3] * grad[:, _np.newaxis]).astype(_np.uint8)

        s      = self._SCALE
        scaled = rgba.repeat(s, axis=0).repeat(s, axis=1)
        ih, iw = scaled.shape[:2]
        self._imgbuf = scaled.tobytes()
        img = QImage(self._imgbuf, iw, ih, iw * 4,
                     QImage.Format.Format_RGBA8888)
        QPainter(self).drawImage(0, 0, img)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if _HAS_NUMPY:
            self._init_fire()

    def start(self):
        if not _HAS_NUMPY:
            return
        self.show()
        self.raise_()
        self._timer.start()

    def stop(self):
        self._timer.stop()
        self.hide()

    def is_running(self) -> bool:
        return self._timer.isActive()


# ── Blood ripple overlay ────────────────────────────────────────────────────────

class BloodRippleOverlay(QWidget):
    """
    Blood drips fall from the cursor position and splash into expanding
    crimson ripple rings on landing — ties the animated bloody-hand cursor
    directly into the UI environment.

    - Drops spawn periodically at the current cursor position.
    - Each drop accelerates downward under simulated gravity.
    - On landing a ring is created that expands and fades.
    - Fully mouse-transparent; toggle with start() / stop().
    """

    _FPS          = 30
    _SPAWN_MS     = 1100    # ms between new drops
    _TRAIL_LEN    = 18      # how many past positions to keep as a wet streak
    _DROP_RADIUS  = 3       # head drop drawn radius
    _RING_MAX_R   = 50
    _RING_SPEED   = 2.2
    _RING_WIDTH   = 2
    # Offset from cursor hotspot (fingertip) to the bloody wrist drip point
    _WRIST_DX     = 24
    _WRIST_DY     = 45

    # Blood colour variants
    _DROP_COLOR  = QColor(180,  10,  10, 230)
    _RING_COLORS = [
        QColor(160,   0,   0),
        QColor(140,  10,  10),
        QColor(120,   5,   5),
    ]

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self._drops: list[dict] = []   # falling drop particles
        self._rings: list[dict] = []   # expanding ripple rings

        # Last wrist position — used to detect cursor movement for trail rings
        self._last_wrist: tuple | None = None
        self._move_accum: float = 0.0   # accumulated distance since last trail ring

        # Drip sounds — pre-loaded for zero-latency playback
        self._drip_files: list = []
        self._drip_effects: dict = {}
        self._recent_drips: deque = deque(maxlen=2)
        if _HAS_SOUND:
            _drips_dir = Path(__file__).parent / "assets" / "drips"
            for wav in sorted(_drips_dir.glob("*.wav")):
                fx = _QSoundEffect()
                fx.setSource(QUrl.fromLocalFile(str(wav)))
                fx.setVolume(0.75)
                self._drip_files.append(wav)
                self._drip_effects[wav] = fx

        # Tick timer — drives physics + painting
        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(1000 // self._FPS)
        self._tick_timer.timeout.connect(self._tick)

        # Spawn timer — creates a new drop periodically
        self._spawn_timer = QTimer(self)
        self._spawn_timer.setInterval(self._SPAWN_MS)
        self._spawn_timer.timeout.connect(self._spawn_drop)

        # Gush splash — play once when the first gush drop lands
        self._gush_splash_pending: bool = False
        self._splash_fx: object = None
        _splash_path = Path(__file__).parent / "assets" / "drips" / "splash.wav"
        if _HAS_SOUND and _splash_path.exists():
            self._splash_fx = _QSoundEffect()
            self._splash_fx.setSource(QUrl.fromLocalFile(str(_splash_path)))
            self._splash_fx.setVolume(0.9)

        self.resize(parent.size())
        self.raise_()

    # ── Particle management ───────────────────────────────────────────────────

    def _make_drop(self, x: float, y: float, vy_range=(2.5, 4.0), vx_scale=1.0) -> dict:
        return {
            "x":    x,
            "y":    y,
            "vy":   random.uniform(*vy_range),
            "vx":   random.uniform(-0.15, 0.15) * vx_scale,
            "ax":   random.uniform(-0.04, 0.04),
            "trail": [],
        }

    def _wrist_pos(self):
        """Return local (x, y) of the bloody wrist on the current cursor."""
        local_pos = self.mapFromGlobal(QCursor.pos())
        return (local_pos.x() + self._WRIST_DX,
                local_pos.y() + self._WRIST_DY)

    def _spawn_drop(self):
        """Spawn a single sliding drop from the bloody wrist — one at a time max."""
        # Vary the next interval slightly for an organic drip cadence
        self._spawn_timer.setInterval(random.randint(400, 2400))
        if self._drops:
            return
        x, y = self._wrist_pos()
        if 0 <= x <= self.width() and 0 <= y <= self.height():
            self._drops.append(self._make_drop(float(x), float(y)))

    def gush(self, global_pos):
        """Double-click burst: drops gush from the wrist, not the click point."""
        x, y = self._wrist_pos()
        _ = global_pos  # unused — position comes from cursor wrist
        if not (0 <= x <= self.width() and 0 <= y <= self.height()):
            return

        self._gush_splash_pending = True   # first gush drop to land plays splash.wav

        count = random.randint(6, 10)
        for _ in range(count):
            drop = self._make_drop(
                x + random.uniform(-8, 8),
                y,
                vy_range=(1.5, 5.5),
                vx_scale=4.0,
            )
            drop["vx"] += random.uniform(-1.2, 1.2)
            drop["is_gush"] = True
            self._drops.append(drop)


    def _spawn_trail_rings(self):
        """Emit small blood ripples from the wrist as the cursor moves."""
        import math
        wx, wy = self._wrist_pos()
        if self._last_wrist is not None:
            lx, ly = self._last_wrist
            dist = math.hypot(wx - lx, wy - ly)
            self._move_accum += dist
            # Emit a ring every ~18 px of cursor travel
            if self._move_accum >= 18:
                self._move_accum = 0.0
                if 0 <= wx <= self.width() and 0 <= wy <= self.height():
                    self._rings.append({
                        "x": wx, "y": wy,
                        "r": 1.0,
                        "alpha": random.randint(110, 160),
                        "color": random.choice(self._RING_COLORS),
                        "speed": random.uniform(1.0, 1.8),
                        "max_r": random.uniform(18, 32),
                    })
        self._last_wrist = (wx, wy)

    def _play_drip_sound(self):
        """Play a random drip WAV, never repeating either of the last two played."""
        if not self._drip_files:
            return
        pool = [f for f in self._drip_files if f not in self._recent_drips]
        if not pool:           # fallback: all sounds excluded (shouldn't happen with 10)
            pool = list(self._drip_files)
        chosen = random.choice(pool)
        self._recent_drips.append(chosen)
        self._drip_effects[chosen].play()

    def _tick(self):
        import math
        h = self.height()
        w = self.width()

        self._spawn_trail_rings()

        surviving = []
        for d in self._drops:
            # Record trail position before moving
            d["trail"].append((d["x"], d["y"]))
            if len(d["trail"]) > self._TRAIL_LEN:
                d["trail"].pop(0)

            # Fast downward with tiny squiggle sideways
            d["vy"]  = min(d["vy"] + 0.18, 9.0)            # accelerate downward
            d["ax"] += random.uniform(-0.025, 0.025)        # tiny random nudge
            d["ax"]  = max(-0.05, min(0.05, d["ax"]))       # keep wobble tight
            d["vx"] += d["ax"]
            d["vx"]  = max(-0.35, min(0.35, d["vx"]))       # barely sideways
            d["x"]  += d["vx"]
            d["y"]  += d["vy"]

            # Soft bounce off walls
            if d["x"] < 2 or d["x"] > w - 2:
                d["vx"] *= -0.5
                d["ax"] *= -1

            if d["y"] >= h - 4:
                ix, iy = d["x"], float(h - 4)
                if d.get("is_gush") and self._gush_splash_pending:
                    # First gush drop to land — play splash once
                    self._gush_splash_pending = False
                    if self._splash_fx:
                        self._splash_fx.play()
                elif not d.get("is_gush"):
                    self._play_drip_sound()
                # Impact ring
                self._rings.append({
                    "x": ix, "y": iy, "r": 2.0, "alpha": 230,
                    "color": random.choice(self._RING_COLORS),
                    "speed": self._RING_SPEED, "max_r": self._RING_MAX_R,
                })
                # Small scatter rings
                for _ in range(random.randint(3, 5)):
                    angle = random.uniform(0, math.pi * 2)
                    dist  = random.uniform(8, 40)
                    self._rings.append({
                        "x": max(0, min(w, ix + dist * math.cos(angle))),
                        "y": max(0, min(h, iy + dist * 0.35 * math.sin(angle))),
                        "r": random.uniform(1.0, 2.5),
                        "alpha": random.randint(80, 150),
                        "color": random.choice(self._RING_COLORS),
                        "speed": random.uniform(0.8, 1.8),
                        "max_r": random.uniform(14, 36),
                    })
            else:
                surviving.append(d)
        self._drops = surviving

        # Update rings
        living = []
        for ring in self._rings:
            ring["r"]     += ring["speed"]
            ring["alpha"] -= 255 / (ring["max_r"] / ring["speed"])
            if ring["alpha"] > 0 and ring["r"] < ring["max_r"]:
                living.append(ring)
        self._rings = living

        self.update()

    # ── Painting ──────────────────────────────────────────────────────────────

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Draw each drop: wet streak trail + head
        p.setPen(Qt.PenStyle.NoPen)
        for d in self._drops:
            trail = d["trail"]
            n = len(trail)
            for i, (tx, ty) in enumerate(trail):
                # Trail fades from transparent at tail to opaque at head
                alpha = int(180 * (i / max(n, 1)) ** 1.4)
                radius = max(1, self._DROP_RADIUS - 1)
                c = QColor(180, 10, 10, alpha)
                p.setBrush(c)
                p.drawEllipse(int(tx) - radius, int(ty) - radius,
                              radius * 2, radius * 2)
            # Drop head — full opacity teardrop shape
            p.setBrush(self._DROP_COLOR)
            p.drawEllipse(
                int(d["x"]) - self._DROP_RADIUS,
                int(d["y"]) - self._DROP_RADIUS,
                self._DROP_RADIUS * 2,
                self._DROP_RADIUS * 2,
            )

        # Draw ripple rings
        for ring in self._rings:
            c = QColor(ring["color"])
            c.setAlpha(max(0, int(ring["alpha"])))
            pen = QPen(c, self._RING_WIDTH)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            r = int(ring["r"])
            p.drawEllipse(int(ring["x"]) - r, int(ring["y"]) - r, r * 2, r * 2)

    # ── Resize ────────────────────────────────────────────────────────────────

    def resizeEvent(self, event):
        super().resizeEvent(event)

    # ── Public API ────────────────────────────────────────────────────────────

    def start(self):
        self.show()
        self.raise_()
        self._tick_timer.start()
        self._spawn_timer.start()

    def stop(self):
        self._tick_timer.stop()
        self._spawn_timer.stop()
        self._drops.clear()
        self._rings.clear()
        for fx in self._drip_effects.values():
            fx.stop()
        if self._splash_fx:
            self._splash_fx.stop()
        self.hide()

    def is_running(self) -> bool:
        return self._tick_timer.isActive()
