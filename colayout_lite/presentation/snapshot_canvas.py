"""Read-only scene host. No main window, Editor, tool panels, persistence or bridge."""

from dataclasses import dataclass
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QWidget, QVBoxLayout, QGraphicsScene
from .canvas import Canvas
from . import layout_scene
from ..editor import projected
from ..scene import figures_by_owner
from ..render import make_texture
from ..inspection_view import InspectionView
from .. import workspace_overlay
from ..theme import set_visual_theme
from ..compact_style import apply_window_theme


@dataclass
class SceneState:
    w: object
    profile: object
    scope_id: str


@dataclass(frozen=True)
class DisplayOption:
    enabled: bool = True

    def isChecked(self):
        return self.enabled


class SnapshotCanvas(QWidget):
    def __init__(self, workspace, profile, region_id, width, height):
        super().__init__()
        self.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFont(QFont('Microsoft YaHei UI', 9))
        apply_window_theme(self)
        self.editor = SceneState(workspace, profile, region_id)
        self.pattern = self.cuts = self.internal = DisplayOption()
        self.groups = {}
        self._workspace_overlay_items = []
        self._local_pin_items = []
        self.scene = QGraphicsScene(self)
        self.scene.setMinimumRenderSize(0.4)
        self.canvas = Canvas(self.scene)
        set_visual_theme(self.canvas, 'compact')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.canvas)
        self.canvas.setFixedSize(width, height)
        self.setFixedSize(width, height)
        self._visible_objects = projected(workspace)
        from ..view_scope import visible_geometry
        _,self._draw_uids,_=visible_geometry(workspace,profile,region_id,objects=self._visible_objects)
        self.base_figures, self.styles = figures_by_owner(
            workspace.baseline, modes=workspace.instance_display,owner_filter=self._draw_uids
        )
        self.textures = {key: make_texture(style) for key, style in self.styles.items()}
        self.canvas.owner_ids = lambda: list(self.groups)
        self.canvas.owner_items = self.visible_owner_items
        self.canvas.overlay_items = lambda: self._workspace_overlay_items
        self.canvas.configure_preview(sum(map(len, self.base_figures.values())))
        for uid in workspace.baseline.objects:
            self.draw_owner(uid)
        self.refresh_graphics({op.uid for op in workspace.operations}&self._draw_uids, self._visible_objects)
        # Uses exactly the human canvas's PIN projection/painter, without starting a query.
        self.inspection = InspectionView(self)
        self.refresh_overlay()
        self.canvas.view_changed.connect(self.refresh_overlay)

    def visible_owner_items(self, uid):
        graphics = self.groups.get(uid)
        if graphics is None or not any(p.isVisible() for p in graphics.parts.values()):
            return []
        return graphics.childItems()

    def draw_owner(self, uid, figures=None):
        if uid not in self._draw_uids:return
        return layout_scene.draw_owner(self, uid, figures)

    def refresh_graphics(self, changed, objects):
        return layout_scene.refresh_graphics(self, changed, objects)

    def refresh_overlay(self):
        workspace_overlay.refresh(self)
        self.inspection.refresh()

    def closeEvent(self, event):
        self.inspection.close()
        self.canvas.close()
        super().closeEvent(event)
