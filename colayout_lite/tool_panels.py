"""One tabbed right-side tool area; preserve the camera when revealing tools."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDockWidget,QTabWidget,QTabBar
from .camera import capture,restore


def show_tool(window,dock):
    state=capture(window.canvas)
    if getattr(getattr(window,'studio',None),'mode',None)=='studio':
        window.setTabPosition(Qt.DockWidgetArea.RightDockWidgetArea,QTabWidget.TabPosition.North)
        dock.setProperty('studioTool',True)
        peers=[d for d in window.findChildren(QDockWidget) if d is not dock and d.property('studioTool') and not d.isHidden()]
        if peers:window.tabifyDockWidget(peers[-1],dock)
        # Qt's native tab base paints a white line only after the final tab.
        # The stylesheet already owns the underline; suppress that extra base.
        for bar in window.findChildren(QTabBar):bar.setDrawBase(False);bar.setExpanding(False)
    dock.show();dock.raise_();window.layout().activate();restore(window.canvas,state)
    from .presentation.dock_tabs import refresh_tabs
    refresh_tabs(window)
