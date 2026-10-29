"""Window-owned routing tasks: one dock per region, two concurrent workers.

Closing a dock only hides its view. The application owns task cancellation and
shutdown; editor identity and full source checks continue to guard adoption.
"""

from concurrent.futures import ThreadPoolExecutor
from PySide6.QtCore import Qt
from ..camera import capture, restore


def selected_region(window):
    e = window.editor
    if not e:
        return None
    ids = [uid for uid in window.human.ids() if uid in e.w.local_data.regions]
    return ids[0] if len(ids) == 1 else e.scope_id


class RoutingWorkbench:
    def __init__(self, window):
        self.window = window
        self.panels = {}
        self.closed = False
        self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix='routing-host')
        window.canvas.routing_overlay = self.paint

    def bind(self, panel, region_id):
        key = (id(panel.editor_context), region_id)
        other = self.panels.get(key)
        if other is not None and other is not panel:
            from ..model import LiteError

            raise LiteError('ROUTING_TASK_EXISTS', '此操作区已有布线面板，请打开该操作区的任务。')
        for previous, value in list(self.panels.items()):
            if value is panel:
                self.panels.pop(previous)
        panel.region_id = region_id
        self.panels[key] = panel
        region = panel.editor_context.w.local_data.regions.get(region_id)
        if region:
            panel.region_name = region.name
            panel.dock.setWindowTitle(region.name + ' · 自动布线')

    def open(self, *, registry_path=None, job_root=None):
        from .panel import RoutingPanel, RoutingDock
        from ..panel_chrome import style_dock
        from ..tool_panels import show_tool

        w = self.window
        region_id = selected_region(w)
        key = (id(w.editor), region_id)
        panel = self.panels.get(key)
        if panel is None:
            state = capture(w.canvas)
            dock = RoutingDock(w)
            dock.setObjectName('routingDock' + str(len(self.panels)))
            panel = RoutingPanel(
                w,
                registry_path=registry_path,
                job_root=job_root,
                workbench=self,
                region_id=region_id,
            )
            panel.dock = dock
            dock.setWidget(panel)
            w.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
            self.panels[key] = panel
            if region_id:
                self.bind(panel, region_id)
            style_dock(w, dock)
            dock.visibilityChanged.connect(lambda visible, p=panel: self.visibility(p, visible))
            w.resizeDocks([dock], [480], Qt.Orientation.Horizontal)
            w.layout().activate()
            restore(w.canvas, state)
        # Compatibility aliases identify the last explicitly opened tool only.
        w.routing_panel = panel
        w.routing_dock = panel.dock
        show_tool(w, panel.dock)
        panel.exposed = True
        panel.refresh()
        panel.restore_preview()
        return panel

    def visibility(self, panel, visible):
        if self.closed:
            return
        panel.exposed = visible
        if panel.dock.isHidden():
            panel.clear_preview()
        elif visible:
            panel.restore_preview()
        panel.refresh()
        self.window.view_state_changed.emit()

    def paint(self, painter):
        for panel in self.panels.values():
            if panel.owns_preview():
                panel.paint(painter)

    def shutdown(self):
        if self.closed:
            return
        self.closed = True
        for panel in tuple(self.panels.values()):
            panel.shutdown()
        self.executor.shutdown(wait=False, cancel_futures=True)
