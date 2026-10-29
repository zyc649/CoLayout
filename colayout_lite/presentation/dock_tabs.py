"""Close the owning dock beside its native tab title; no duplicate far-edge X."""

from PySide6.QtCore import QObject, QTimer, QSize
from PySide6.QtWidgets import QDockWidget, QTabBar, QToolButton
from ..studio_icons import icon
from ..compact_style import ICON_COLOR


class DockTabs(QObject):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.refresh)
        self.observed = set()

    def schedule(self, *_):
        self.timer.start(0)

    def refresh(self):
        window = self.window
        formal = getattr(getattr(window, 'studio', None), 'mode', None) == 'studio'
        docks = window.findChildren(QDockWidget)
        tabbed = set()
        for dock in docks:
            if dock not in self.observed:
                dock.visibilityChanged.connect(self.schedule)
                dock.topLevelChanged.connect(self.schedule)
                self.observed.add(dock)
        for bar in window.findChildren(QTabBar):
            if bar.parentWidget() is not window or not bar.isVisible():
                continue
            for index in range(bar.count()):
                matches = [
                    d
                    for d in docks
                    if d.property('studioTool') and not d.isHidden()
                    and not d.isFloating()
                    and d.windowTitle().replace('&', '') == bar.tabText(index).replace('&', '')
                ]
                if not formal or len(matches) != 1:
                    continue
                dock = matches[0]
                tabbed.add(dock)
                button = bar.tabButton(index, QTabBar.ButtonPosition.RightSide)
                if (
                    button is None
                    or button.property('dockOwner') != dock.objectName()
                ):
                    button = QToolButton(bar)
                    button.setObjectName('dockTabClose')
                    button.setProperty('dockOwner', dock.objectName())
                    button.setIcon(icon('close', ICON_COLOR))
                    button.setIconSize(QSize(14, 14))
                    button.setFixedSize(20, 20)
                    button.setStyleSheet('QToolButton { padding: 0; margin: 0; border: 0; min-width: 0; min-height: 0; background: transparent; } QToolButton:hover { background: #484c54; }')
                    button.setAccessibleName('关闭' + dock.windowTitle() + '标签页')
                    button.setToolTip('关闭' + dock.windowTitle())
                    button.clicked.connect(dock.close)
                    bar.setTabButton(index, QTabBar.ButtonPosition.RightSide, button)
            if not formal:
                for index in range(bar.count()):
                    button = bar.tabButton(index, QTabBar.ButtonPosition.RightSide)
                    if button and button.objectName() == 'dockTabClose':
                        bar.setTabButton(index, QTabBar.ButtonPosition.RightSide, None)
                        button.deleteLater()
        for dock in docks:
            header = dock.titleBarWidget()
            if header and header.objectName() == 'compactHeader':
                header.setFixedHeight(0 if formal and dock in tabbed else 30)


def refresh_tabs(window):
    controller = getattr(window, '_dock_tabs', None)
    if controller is None:
        controller = DockTabs(window)
        window._dock_tabs = controller
    controller.refresh()
    controller.schedule()
