"""Presentation tokens for the optional Studio shell and its layout canvas.

These tokens never replace PDK layer colors.  Classic is the default so the
communication/test window keeps its established appearance.  A theme switch
only changes display state; it must not publish a workspace revision.
"""
from dataclasses import dataclass

from PySide6.QtGui import QColor, QBrush


@dataclass(frozen=True)
class CanvasPalette:
    name: str
    background: str
    local_border: str
    local_fill: str
    local_label: str
    group: str
    markup: str
    keepout: str
    native_border: str
    native_fill: str
    native_label: str
    pin: str
    pin_dim: str
    pin_target: str
    pin_contact: str
    pin_error: str
    pin_label_fill: str
    net_connected: str
    net_short: str
    net_badge: str
    selection: str
    selection_halo: str
    marquee_contains: str
    marquee_intersects: str
    working_border: str
    working_glow: str
    working_fill: str
    pin_label_style: str = 'boxed'
    net_dim_alpha: int = 185
    net_line_width: float = 2.0
    net_fill_alpha: int = 100


CLASSIC = CanvasPalette(
    name='classic', background='#090c10', local_border='#67d7c4',
    local_fill='#182833', local_label='#67d7c4', group='#64d3bd',
    markup='#c9a1ff', keepout='#f26d77', native_border='#6f9dca',
    native_fill='#152233', native_label='#a7c8da', pin='#6eeaff',
    pin_dim='#38565f', pin_target='#ffd574', pin_contact='#9aff9a',
    pin_error='#ff7777', pin_label_fill='#090c10', net_connected='#75ff76',
    net_short='#ff6262', net_badge='#101b1a', selection='#ffd35c',
    selection_halo='#091014', marquee_contains='#77c9ff',
    marquee_intersects='#69e8b3', working_border='#ffe6ac',
    working_glow='#423d30', working_fill='#24272b',
)

STUDIO = CanvasPalette(
    name='studio', background='#14191f', local_border='#75b9b0',
    local_fill='#213036', local_label='#9bcfc5', group='#85bdb3',
    markup='#afa1c5', keepout='#c98886', native_border='#758aab',
    native_fill='#1c2633', native_label='#a7b9d0', pin='#a0cfdb',
    pin_dim='#42545d', pin_target='#e7c480', pin_contact='#99d6ad',
    pin_error='#ee9b98', pin_label_fill='#1a222b', net_connected='#98dbad',
    net_short='#ed9490', net_badge='#202d2b', selection='#ead394',
    selection_halo='#14191f', marquee_contains='#91bcdf',
    marquee_intersects='#91c9b6', working_border='#ffe6ac',
    working_glow='#423f34', working_fill='#2c2d2c',
)


COMPACT = CanvasPalette(
    # Quiet surfaces carry the everyday view; saturated colors are reserved for
    # temporary electrical results. PDK layers retain their imported colors.
    name='compact', background='#1e1f22', local_border='#93979e',
    local_fill='#28292c', local_label='#b6b8bd', group='#a8b2ad',
    markup='#aca8b4', keepout='#c3918a', native_border='#93979e',
    native_fill='#28292c', native_label='#b6b8bd', pin='#c5ccd5',
    pin_dim='#5b6069', pin_target='#efbd65', pin_contact='#69db95',
    pin_error='#f27778', pin_label_fill='#1e1f22', net_connected='#69db95',
    net_short='#f27778', net_badge='#2b2d30', selection='#9dbcec',
    selection_halo='#1e1f22', marquee_contains='#96b5e0',
    marquee_intersects='#a5c8ad', working_border='#ffe6ac',
    working_glow='#403d33', working_fill='#2d2d2c', pin_label_style='plain',
    net_dim_alpha=168, net_line_width=2.6, net_fill_alpha=52,
)

_PALETTES = {p.name: p for p in (CLASSIC, STUDIO, COMPACT)}

# Per-inspection accents. A single query uses one hue for every conductor/PIN,
# while connectivity/short status stays in the report rather than color codes.
NET_ACCENTS=('#69db95','#86b9ed','#e5bd76','#c1a7ea')


def net_fill(color,background,amount=.24):
    """Opaque tint: underlying PDK stipples must not leak other net colors."""
    fg,bg=QColor(color),QColor(background)
    return QColor(*(round(a*amount+b*(1-amount)) for a,b in zip(fg.getRgb()[:3],bg.getRgb()[:3])))


def palette(source=None):
    """Resolve view-only state without consulting the workspace or server."""
    return _PALETTES.get(getattr(source, 'visual_theme', 'classic'), CLASSIC)


def set_visual_theme(canvas, name):
    """Switch canvas chrome; caller refreshes styled native/local scene items.

    Native layer command buffers remain valid until their actual item styles
    change. No workspace edit, autosave, geometry query or transport is involved.
    """
    if name not in _PALETTES:
        raise ValueError('Unknown visual theme: ' + str(name))
    canvas.visual_theme = name
    canvas.setBackgroundBrush(QBrush(QColor(palette(canvas).background)))
    canvas.viewport().update()


def alpha(color, opacity):
    result = QColor(color)
    result.setAlphaF(opacity)
    return result


# Apply to the Studio window, but scope every rule to Studio object names.
# Classic widgets/communication diagnostics are intentionally not restyled.
STUDIO_STYLE_SHEET = """
QWidget#studioChrome, QWidget#studioRibbon, QWidget#studioProperties, QWidget#studioHierarchy {
    background: #f7f8fa; color: #29313d;
    font-family: 'Segoe UI', 'Microsoft YaHei UI'; font-size: 12px;
}
QWidget#studioChrome QLabel, QWidget#studioRibbon QLabel, QWidget#studioProperties QLabel {
    color: #475262; background: transparent;
}
QWidget#studioChrome QLabel#studioTitle { color: #202936; font-size: 16px; font-weight: 600; }
QWidget#studioChrome QLabel#studioSubtitle, QWidget#studioProperties QLabel#studioMuted {
    color: #7a8491; font-size: 11px;
}
QWidget#studioChrome QPushButton, QWidget#studioRibbon QPushButton,
QWidget#studioProperties QPushButton, QWidget#studioChrome QToolButton,
QWidget#studioRibbon QToolButton, QWidget#studioProperties QToolButton {
    color: #344151; background: transparent; border: 1px solid transparent;
    border-radius: 5px; padding: 6px 10px;
}
QWidget#studioChrome QPushButton:hover, QWidget#studioRibbon QPushButton:hover,
QWidget#studioProperties QPushButton:hover, QWidget#studioChrome QToolButton:hover,
QWidget#studioRibbon QToolButton:hover, QWidget#studioProperties QToolButton:hover {
    background: #e9edf2; border-color: #dce2ea;
}
QWidget#studioChrome QPushButton:checked, QWidget#studioRibbon QPushButton:checked,
QWidget#studioProperties QPushButton:checked, QWidget#studioChrome QToolButton:checked,
QWidget#studioRibbon QToolButton:checked, QWidget#studioProperties QToolButton:checked {
    color: #28586a; background: #e2edf0; border-color: #bed5dc;
}
QWidget#studioChrome QPushButton:disabled, QWidget#studioRibbon QPushButton:disabled,
QWidget#studioProperties QPushButton:disabled, QWidget#studioChrome QToolButton:disabled,
QWidget#studioRibbon QToolButton:disabled, QWidget#studioProperties QToolButton:disabled {
    color: #a5abb3;
}
QWidget#studioRibbon QPushButton#studioPrimary, QWidget#studioChrome QPushButton#studioPrimary {
    color: white; background: #386b77; border-color: #386b77;
    padding: 7px 13px; font-weight: 600;
}
QWidget#studioRibbon QPushButton#studioPrimary:hover,
QWidget#studioChrome QPushButton#studioPrimary:hover { background: #2d5d69; }
QWidget#studioProperties QLineEdit, QWidget#studioProperties QComboBox,
QWidget#studioProperties QSpinBox, QWidget#studioProperties QDoubleSpinBox,
QWidget#studioRibbon QComboBox, QWidget#studioChrome QComboBox {
    color: #344151; background: #ffffff; border: 1px solid #dce1e7;
    border-radius: 4px; padding: 5px 7px; min-height: 19px;
}
QWidget#studioProperties QLineEdit:focus, QWidget#studioProperties QComboBox:focus,
QWidget#studioProperties QSpinBox:focus, QWidget#studioProperties QDoubleSpinBox:focus {
    border-color: #749ca7;
}
QWidget#studioProperties QLineEdit:disabled, QWidget#studioProperties QComboBox:disabled,
QWidget#studioProperties QSpinBox:disabled, QWidget#studioProperties QDoubleSpinBox:disabled {
    color: #8e99a5; background: #f2f4f6; border-color: #e4e8ed;
}
QWidget#studioProperties QTreeWidget, QWidget#studioProperties QTableWidget,
QWidget#studioProperties QListWidget, QWidget#studioProperties QTextEdit {
    color: #344151; background: #ffffff; alternate-background-color: #f7f9fb;
    border: 1px solid #e2e6eb; border-radius: 4px; gridline-color: #edf0f3;
    selection-background-color: #e1ecf0; selection-color: #244959;
}
QWidget#studioProperties QTreeWidget::item, QWidget#studioProperties QListWidget::item {
    padding: 4px; min-height: 20px;
}
QWidget#studioProperties QHeaderView::section {
    background: #f1f4f7; color: #6a7583; border: 0; border-bottom: 1px solid #dfe4eb;
    padding: 6px; font-weight: 400;
}
QWidget#studioProperties QGroupBox { border: 0; margin-top: 18px; font-weight: 600; }
QWidget#studioProperties QGroupBox::title { subcontrol-origin: margin; left: 0px; color: #465467; }
QWidget#studioProperties QCheckBox { color: #465467; spacing: 7px; padding: 4px 0; }
QWidget#studioProperties QCheckBox::indicator { width: 14px; height: 14px; }
QWidget#studioProperties QTabWidget::pane { border: 0; border-top: 1px solid #e0e5eb; }
QWidget#studioProperties QTabBar::tab {
    background: transparent; color: #78828f; padding: 8px 11px; border: 0;
    border-bottom: 2px solid transparent;
}
QWidget#studioProperties QTabBar::tab:selected { color: #345f6d; border-bottom-color: #527f8b; }
QWidget#studioProperties QScrollBar:vertical { width: 9px; background: transparent; margin: 0; }
QWidget#studioProperties QScrollBar::handle:vertical { background: #cbd3dc; border-radius: 4px; min-height: 24px; }
QWidget#studioProperties QScrollBar::add-line:vertical,
QWidget#studioProperties QScrollBar::sub-line:vertical { height: 0; }
QWidget#studioProperties QScrollBar::add-page:vertical,
QWidget#studioProperties QScrollBar::sub-page:vertical { background: transparent; }
QWidget#studioProperties QLabel#studioWorkingBadge {
    color: #87632e; background: #f3eadb; border: 1px solid #e7d7bc;
    border-radius: 4px; padding: 6px 8px;
}
QWidget#studioChrome QLabel#studioSection, QWidget#studioProperties QLabel#studioSection {
    color: #7d8794; font-size: 11px; font-weight: 600;
}
QWidget#studioHierarchy QTreeWidget {
    color: #344151; background: #f7f8fa; border: 0; outline: 0;
    selection-background-color: #e1ecf0; selection-color: #244959;
}
QWidget#studioHierarchy QTreeWidget::item { padding: 4px 3px; min-height: 21px; }
QWidget#studioHierarchy QTreeWidget::item:hover { background: #edf0f4; }
QWidget#studioHierarchy QTreeWidget::item:selected { background: #e1ecf0; }
QWidget#studioHierarchy QHeaderView::section {
    background: #f7f8fa; color: #7a8491; border: 0; padding: 6px 3px;
}
QWidget#studioChrome QSplitter::handle { background: #e3e7ec; }
QWidget#studioChrome QSplitter::handle:horizontal { width: 1px; }
QWidget#studioChrome QSplitter::handle:vertical { height: 1px; }
"""
