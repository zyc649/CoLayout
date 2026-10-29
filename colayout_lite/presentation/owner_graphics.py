"""A selectable owner composed of independently stacked display layers."""

from PySide6.QtGui import QTransform
from PySide6.QtWidgets import QGraphicsItem
from ..render import PreviewGroup
from ..geometry_paths import box_rect


def qt_transform(t):
    a, b, c, d, x, y = t
    return QTransform(a, -c, -b, d, x, -y)


class OwnerGraphics:
    """One transform owner, with independent global layer stacking groups."""

    def __init__(self, scene, uid, reference_bbox=None):
        self.scene = scene
        self.uid = uid
        self.parts = {}
        self.reference_bbox = reference_bbox
        self.transform = QTransform()

    def addToGroup(self, item, priority=None):
        priority = item.zValue() if priority is None else priority
        if priority not in self.parts:
            group = PreviewGroup()
            group.setData(0, self.uid)
            group.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
            group.setZValue(priority)
            self.scene.addItem(group)
            self.parts[priority] = group
        self.parts[priority].addToGroup(item)
        item.setZValue(0)

    def childItems(self):
        return [item for group in self.parts.values() for item in group.childItems()]

    def setTransform(self, tr):
        self.transform = tr
        for group in self.parts.values():
            group.setTransform(tr)

    def selection_rect(self):
        if self.reference_bbox is not None:
            return self.transform.mapRect(box_rect(self.reference_bbox))
        rect = None
        for part in self.parts.values():
            rect = (
                part.sceneBoundingRect() if rect is None else rect.united(part.sceneBoundingRect())
            )
        return rect

    def setToolTip(self, text):
        for group in self.parts.values():
            group.setToolTip(text)

    def remove(self):
        for group in self.parts.values():
            self.scene.removeItem(group)
        self.parts.clear()
