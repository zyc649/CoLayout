"""Window-local styling for the quiet, canvas-first presentation.

Surface steps are deliberate: the charcoal canvas is deepest, tool windows
sit one step above it, and the header/menus provide a visible frame. Blue is a
control focus/selection cue; electrical result colors belong to theme.py.
The palette also covers native-painted controls and popups.  Container rules
are named deliberately: styling every QWidget background would paint over the
layout viewport and its lightweight overlays.  The shell owns switching; this
module does not edit the application-wide palette or any workspace state.
"""
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtGui import QColor, QPalette
from .theme import COMPACT


ICON_COLOR = '#c8ced8'


def window_palette(source=None):
    """Return a complete neutral palette, retaining unrelated platform roles."""
    result = QPalette(source) if source is not None else QPalette()
    colors = {
        'Window': '#2b2d30', 'WindowText': '#d8dee5',
        'Base': '#202126', 'AlternateBase': '#313338',
        'Text': '#d8dee5', 'Button': '#35373c', 'ButtonText': '#d8dee5',
        'Highlight': '#3c4b63', 'HighlightedText': '#e4e8ef',
        'BrightText': '#e4e8ef', 'Link': '#9dbcec', 'LinkVisited': '#9dbcec',
        'ToolTipBase': '#35373c', 'ToolTipText': '#e4e8ef',
        'PlaceholderText': '#9299a4', 'Light': '#55585a',
        'Midlight': '#45484a', 'Mid': '#404348', 'Dark': '#1b1c1e',
        'Shadow': '#151617',
    }
    for role, value in colors.items():
        result.setColor(getattr(QPalette.ColorRole, role), QColor(value))
    for role, value in {
        'WindowText': '#747b85', 'Text': '#8b929c', 'ButtonText': '#747b85',
        'Base': '#262729', 'Button': '#282a2c',
        'Highlight': '#3a3e42', 'HighlightedText': '#9b9da0',
    }.items():
        result.setColor(QPalette.ColorGroup.Disabled,
                        getattr(QPalette.ColorRole, role), QColor(value))
    return result


@dataclass(frozen=True)
class ThemeSnapshot:
    """Presentation state needed to return to the retained UI unchanged."""
    palette: QPalette
    style_sheet: str


def apply_window_theme(window):
    """Apply compact chrome and return the exact state to restore on exit."""
    previous = ThemeSnapshot(QPalette(window.palette()), window.styleSheet())
    window.setPalette(window_palette(previous.palette))
    window.setStyleSheet(COMPACT_STYLE_SHEET)
    return previous


def restore_window_theme(window, previous):
    """Restore this window only; other open documents keep their own theme."""
    window.setStyleSheet(previous.style_sheet)
    window.setPalette(previous.palette)


COMPACT_STYLE_SHEET = """
QToolBar { spacing: 2px; padding: 2px 4px; border: 0; }
QToolBar::separator { width: 1px; background: #454951; margin: 8px 5px; }
QDialog, QDockWidget { background: #2b2d30; color: #d8dee5; }
QScrollArea#processConfigScroll, QWidget#processConfigPage { background: #292b2f; color: #d8dee5; }
QScrollArea#processConfigScroll QHeaderView { background: #303238; }
QDialog QLabel, QDockWidget QLabel { color: #c8ced8; background: transparent; }
QDockWidget::title { background: #313338; color: #d8dee5; padding: 6px; }
QPushButton#canvasDraw, QPushButton#drcRun { background: #35373c; border: 1px solid #596578; padding: 6px 10px; }
QToolButton#compactIconButton { padding: 2px; }
QDockWidget#routingDock QPushButton#routingGenerate,
QDockWidget#routingDock QPushButton#routingApply {
    color: #d8dee5; background: #35373c; border: 1px solid #596578; padding: 6px 10px;
}
QDockWidget#routingDock QPushButton#routingGenerate:hover,
QDockWidget#routingDock QPushButton#routingApply:hover { background: #42484d; border-color: #8b969f; }
QDockWidget#routingDock QPushButton#routingGenerate:disabled,
QDockWidget#routingDock QPushButton#routingApply:disabled { color: #747b85; background: #282a2c; border-color: #404348; }
QWidget#compactChrome, QWidget#compactHeader, QWidget#compactFooter,
QWidget#compactToolbar, QWidget#compactBreadcrumb {
    background: #2b2d30; color: #d8dee5;
    font-family: 'Segoe UI', 'Microsoft YaHei UI'; font-size: 12px;
}
QWidget#compactHeader, QWidget#compactToolbar { border-bottom: 1px solid #393c42; }
QWidget#compactFooter, QWidget#compactBreadcrumb { border-top: 1px solid #393c42; }
QWidget#studioProperties, QWidget#studioInspectorBody, QWidget#studioHierarchy {
    background: #25262a; color: #d8dee5;
    font-family: 'Segoe UI', 'Microsoft YaHei UI'; font-size: 12px;
}
QWidget#studioProperties { border-left: 1px solid #404348; }
QWidget#studioHierarchy { border-right: 1px solid #404348; }
QWidget#studioInspectorBody { border: 0; }
QScrollArea#studioInspectorScroll { background: #25262a; border: 0; }
QWidget#compactChrome QLabel, QToolBar#compactToolbar QLabel { color: #c8ced8; background: transparent; border: 0; }
QWidget#compactChrome QLabel#compactBrand, QToolBar#compactToolbar QLabel#compactBrand {
    color: #e4e8ef; font-size: 13px; font-weight: 600;
}
QWidget#compactChrome QLabel#studioTitle {
    color: #e4e8ef; font-size: 14px; font-weight: 600;
}
QWidget#compactChrome QLabel#studioSubtitle,
QWidget#compactChrome QLabel#studioMuted,
QWidget#compactChrome QLabel#studioSection,
QWidget#compactChrome QLabel#compactSubtitle,
QWidget#compactChrome QLabel#compactSelection,
QToolBar#compactToolbar QLabel#compactSubtitle {
    color: #a2a9b2; font-size: 11px;
}
QWidget#compactChrome QLabel#studioSection { margin-top: 4px; }
QWidget#compactChrome QLabel#compactSyncBadge, QToolBar#compactToolbar QLabel#compactSyncBadge {
    color: #bdb8ab; padding: 0 5px; font-size: 11px;
}
QWidget#compactChrome QLabel#studioWorkingBadge {
    color: #cfb993; background: #302c26; border: 1px solid #514736;
    border-radius: 2px; padding: 5px 7px;
}
QWidget#compactChrome QLabel#propertyMessage { color: #c5bea9; }

/* Specific controls, never a blanket QWidget background. These also style
   parented dialogs and popups opened by the compact shell. */
QPushButton, QToolButton {
    color: #c8ced8; background: transparent; border: 1px solid transparent;
    border-radius: 3px; padding: 4px 8px;
    font-family: 'Segoe UI', 'Microsoft YaHei UI'; font-size: 12px;
}
QPushButton:hover, QToolButton:hover { background: #393c43; border-color: #454951; }
QPushButton:pressed, QToolButton:pressed { background: #454a54; border-color: #6d7a8e; }
QPushButton:checked, QToolButton:checked {
    color: #e4e8ef; background: #3c4b63; border-color: #647fa6;
}
QPushButton:focus, QToolButton:focus { border-color: #7aa2de; }
QPushButton:disabled, QToolButton:disabled {
    color: #747b85; background: transparent; border-color: transparent;
}
QWidget#studioProperties QPushButton {
    background: #35373c; border-color: #45484a; padding: 5px 8px;
}
QWidget#studioProperties QPushButton:hover { background: #3a3d40; border-color: #6d7a8e; }
QWidget#studioProperties QPushButton:checked { background: #42484d; border-color: #8b969f; }
QWidget#studioProperties QPushButton:disabled {
    color: #747b85; background: #313338; border-color: #3a3d40;
}
QToolButton::menu-indicator { subcontrol-position: right center; right: 3px; }
QToolButton#compactMenuButton { padding: 4px 10px; }
QToolButton#compactIconButton { padding: 4px; }

QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateTimeEdit {
    color: #d8dee5; background: #202126; border: 1px solid #50545b;
    border-radius: 3px; padding: 4px 6px; min-height: 17px;
    selection-background-color: #3c4b63; selection-color: #e4e8ef;
    font-family: 'Segoe UI', 'Microsoft YaHei UI'; font-size: 12px;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus,
QDateTimeEdit:focus { border-color: #7aa2de; }
QLineEdit:read-only { color: #b6bdc8; background: #303238; }
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled,
QDoubleSpinBox:disabled, QDateTimeEdit:disabled {
    color: #818995; background: #282a2c; border-color: #3b3e40;
}
QComboBox { padding-right: 22px; }
QComboBox::drop-down { border: 0; width: 22px; }
QComboBox QAbstractItemView {
    color: #d8dee5; background: #303238; border: 1px solid #62676c;
    selection-background-color: #3c4b63; selection-color: #e4e8ef;
    padding: 3px; outline: 0;
}
QSpinBox::up-button, QDoubleSpinBox::up-button, QDateTimeEdit::up-button,
QSpinBox::down-button, QDoubleSpinBox::down-button, QDateTimeEdit::down-button {
    background: #303336; border: 0; width: 16px;
}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover { background: #3b4658; }
QCheckBox, QRadioButton {
    color: #c8ced8; background: transparent; spacing: 7px; padding: 3px 0;
    font-family: 'Segoe UI', 'Microsoft YaHei UI'; font-size: 12px;
}
QCheckBox:disabled, QRadioButton:disabled { color: #818995; }
QCheckBox::indicator, QAbstractItemView::indicator { width: 14px; height: 14px; }
QRadioButton::indicator { width: 14px; height: 14px; }

QTreeView, QTableView, QListView, QTextEdit, QPlainTextEdit {
    color: #c8ced8; background: #202126; alternate-background-color: #282a2f;
    border: 1px solid #404348; border-radius: 2px; gridline-color: #393d43;
    selection-background-color: #3c4b63; selection-color: #e4e8ef;
    font-family: 'Segoe UI', 'Microsoft YaHei UI'; font-size: 12px;
    outline: 0;
}
QTreeView::item, QListView::item { padding: 4px 3px; min-height: 20px; }
QTreeView::item:hover, QListView::item:hover { background: #34373e; }
QTreeView::item:selected, QListView::item:selected {
    color: #e4e8ef; background: #3c4b63;
}
QWidget#studioHierarchy QTreeWidget { background: #25262a; border: 0; }
QHeaderView::section {
    background: #303238; color: #bbc3ce; border: 0;
    border-bottom: 1px solid #454951; padding: 5px 7px; font-weight: 400;
}
QTableCornerButton::section { background: #303238; border: 0; }
QGroupBox { color: #c8ced8; border: 1px solid #404348; border-radius: 2px; margin-top: 14px; }
QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 3px; }
QTabWidget::pane { border: 1px solid #454951; background: #2b2d30; }
QTabBar::tab {
    color: #d8dee5; background: #2b2d30; border: 0; padding: 7px 10px;
    border-bottom: 2px solid #aeb5bf;
}
QTabBar::tab:selected { color: #e4e8ef; border-bottom-color: #7aa2de; background: #34373e; }
QTabBar::tab:hover { color: #e4e8ef; background: #34373e; }

QMenu {
    color: #d8dee5; background: #303238; border: 1px solid #555b60;
    padding: 5px 3px; font-family: 'Segoe UI', 'Microsoft YaHei UI'; font-size: 12px;
}
QMenu::item { padding: 6px 26px 6px 22px; border: 1px solid transparent; border-radius: 2px; }
QMenu::item:selected { color: #e4e8ef; background: #3b4658; border-color: #586a84; }
QMenu::item:disabled { color: #81878b; }
QMenu::separator { height: 1px; background: #44494d; margin: 4px 7px; }
QMenu::indicator { width: 14px; height: 14px; }
QMenuBar { color: #c8ced8; background: #2b2d30; }
QMenuBar::item:selected { background: #3c4b63; }
QDialog, QMessageBox, QFileDialog { color: #d8dee5; background: #2b2d30; }
QDialog QLabel, QMessageBox QLabel { color: #c8ced8; background: transparent; }
QDialogButtonBox QPushButton { background: #363b3f; border-color: #555d63; min-width: 64px; }
QDialogButtonBox QPushButton:hover { background: #474f56; }
QToolTip {
    color: #e4e8ef; background: #32363a; border: 1px solid #656e75;
    padding: 5px 7px; font-family: 'Segoe UI', 'Microsoft YaHei UI'; font-size: 12px;
}

QScrollBar:vertical { width: 10px; background: transparent; margin: 0; }
QScrollBar:horizontal { height: 10px; background: transparent; margin: 0; }
QScrollBar::handle:vertical { background: #585e68; border-radius: 3px; min-height: 26px; margin: 2px; }
QScrollBar::handle:horizontal { background: #585e68; border-radius: 3px; min-width: 26px; margin: 2px; }
QScrollBar::handle:hover { background: #79828f; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
QSplitter::handle { background: #404348; width: 1px; height: 1px; }
QProgressBar { color: #c8ced8; background: #202126; border: 1px solid #454951; text-align: center; }
QProgressBar::chunk { background: #687781; }
QStatusBar { color: #a2a9b2; background: #2b2d30; border-top: 1px solid #393c42; font-size: 11px; }
QStatusBar::item { border: 0; }
QStatusBar QLabel { color: #a2a9b2; background: transparent; }
"""


# File-backed SVGs remain crisp at fractional desktop scaling. Qt's stylesheet
# engine does not consistently support SVG data URLs, so resolve package paths
# independently of the process working directory.
_ASSETS = Path(__file__).with_name('assets') / 'compact'

# QSS polish can reset the viewport's imperative Base/Window palette. At
# fractional DPI, panning exposes its final device-pixel row/column. Scope the
# fallback to the canvas so the rest of the window keeps its own surfaces.
COMPACT_STYLE_SHEET += f'\nQGraphicsView#layoutCanvas {{ background: {COMPACT.background}; border: 0; }}\n'


def _asset(name):
    return 'url("' + (_ASSETS / (name + '.svg')).as_posix() + '")'


COMPACT_STYLE_SHEET += """
QCheckBox::indicator, QAbstractItemView::indicator {
    background: #202126; border: 1px solid #717b89; border-radius: 2px;
}
QCheckBox::indicator:hover, QAbstractItemView::indicator:hover { border-color: #9dbcec; }
QCheckBox::indicator:checked, QAbstractItemView::indicator:checked {
    background: #c8ced8; border-color: #c8ced8; image: CHECK_IMAGE;
}
QCheckBox::indicator:indeterminate, QAbstractItemView::indicator:indeterminate {
    background: #c8ced8; border-color: #c8ced8; image: DASH_IMAGE;
}
QCheckBox::indicator:disabled, QAbstractItemView::indicator:disabled {
    background: #292d30; border-color: #535b60;
}
QCheckBox::indicator:checked:disabled, QAbstractItemView::indicator:checked:disabled {
    background: #798187; border-color: #798187; image: CHECK_IMAGE;
}
QRadioButton::indicator { background: #202126; border: 1px solid #717b89; border-radius: 7px; }
QRadioButton::indicator:checked { background: #c8ced8; border: 3px solid #64748b; border-radius: 7px; }
QRadioButton::indicator:disabled { border-color: #555d63; }
QRadioButton::indicator:checked:disabled { background: #798187; }
QMenu::indicator:checked { image: MENU_CHECK_IMAGE; }
QComboBox::down-arrow, QSpinBox::down-arrow, QDoubleSpinBox::down-arrow,
QDateTimeEdit::down-arrow { image: DOWN_IMAGE; width: 10px; height: 10px; }
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow, QDateTimeEdit::up-arrow {
    image: UP_IMAGE; width: 10px; height: 10px;
}
QMenu::right-arrow { image: RIGHT_IMAGE; width: 10px; height: 10px; }
QTreeView::branch:closed:has-children { image: RIGHT_IMAGE; }
QTreeView::branch:open:has-children { image: DOWN_IMAGE; }
""".replace('MENU_CHECK_IMAGE', _asset('menu-check')).replace('CHECK_IMAGE', _asset('check')).replace(
    'DASH_IMAGE', _asset('dash')).replace('DOWN_IMAGE', _asset('down')).replace(
    'UP_IMAGE', _asset('up')).replace('RIGHT_IMAGE', _asset('right'))
