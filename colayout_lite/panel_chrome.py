"""Shared compact panel header for embedded and docked tools."""
from PySide6.QtCore import QSize
from PySide6.QtWidgets import QWidget,QHBoxLayout,QLabel,QToolButton
from .studio_icons import icon
from .compact_style import ICON_COLOR


def header(title,close,parent=None):
    widget=QWidget(parent);widget.setObjectName('compactHeader');widget.setFixedHeight(30)
    row=QHBoxLayout(widget);row.setContentsMargins(12,0,4,0);row.addWidget(QLabel(title))
    button=QToolButton();button.setObjectName('compactIconButton');button.setFixedSize(26,26)
    button.setIcon(icon('close',ICON_COLOR));button.setIconSize(QSize(16,16));button.setToolTip('收起'+title)
    button.setAccessibleName('收起'+title);button.clicked.connect(close);row.addWidget(button);row.addStretch()
    return widget


def style_dock(window,dock,formal=None):
    if formal is None:formal=getattr(getattr(window,'studio',None),'mode',None)=='studio'
    old=dock.titleBarWidget()
    if formal and old is None:dock.setTitleBarWidget(header(dock.windowTitle(),dock.close,dock))
    elif not formal and old is not None:dock.setTitleBarWidget(None);old.deleteLater()
