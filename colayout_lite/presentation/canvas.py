"""Canvas gestures and ordered overlays; no workspace persistence or bridge."""

from PySide6.QtCore import Qt, Signal, QRect, QPointF, QEvent
from PySide6.QtGui import QColor, QPainter, QContextMenuEvent
from PySide6.QtWidgets import QApplication, QGraphicsView
from ..preview import PreviewView


class Canvas(PreviewView):
    clicked_at = Signal(float, float)
    inspection_clicked = Signal(float, float)
    region_picked = Signal(object)
    region_cancelled = Signal()
    object_activated = Signal(str)
    view_changed = Signal()
    peek_changed = Signal(int)
    inspection_clear = Signal()

    def __init__(self, scene):
        super().__init__(scene)
        self.setObjectName('layoutCanvas')
        self.setBackgroundBrush(QColor('#090c10'))
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.NoAnchor)
        self.region_select = False
        self.drc_overlay = None
        self.routing_overlay = None
        self.guard_overlay = None
        self.blackbox_peek = 0
        self.inspection_overlay = None
        self.peek_modifiers = Qt.KeyboardModifier.ControlModifier
        self.human = None
        self.selection_ui = None
        self._normal_press = None
        self._pan_last = None
        self._pan_button = None
        self._pan_started = False
        self._suppress_context_menu = False
        self._preview_press = False
        from ..box_capture import BoxCapture

        self.box_capture = BoxCapture(self)
        self.view_changed.connect(self.box_capture.refresh)

    @property
    def region_select(self):
        return self._region_select

    @region_select.setter
    def region_select(self, value):
        self._region_select = bool(value)
        if not value and hasattr(self, 'box_capture'):
            self.box_capture.cancel()

    def fitInView(self, rect, mode=Qt.AspectRatioMode.IgnoreAspectRatio):
        if self.selection_ui:
            self.selection_ui.cancel()
        if self.human:
            self.human.cancel()
        # Navigation gives this view its own scene rect. Every focus/fit entry
        # point must reset it, including existing DRC and render-view callers.
        self.setSceneRect(rect)
        super().fitInView(rect, mode)
        if hasattr(self, 'box_capture'):
            self.box_capture.refresh()

    def wheelEvent(self, event):
        delta = event.angleDelta().y() or event.pixelDelta().y()
        if not delta:
            return
        if self._preview_press:
            self._preview_press = False
            self._normal_press = None
        if self.selection_ui:
            self.selection_ui.cancel()
        if self.human and self.human.armed:
            self.human.cancel()
            self._normal_press = None
        if event.modifiers() == self.peek_modifiers:
            level = max(0, min(2, self.blackbox_peek + (-1 if delta > 0 else 1)))
            if level != self.blackbox_peek:
                self.blackbox_peek = level
                self.peek_changed.emit(level)
            event.accept()
            return
        from ..camera import zoom_at

        self.wheel_activity()
        zoom_at(self, event.position(), 1.2 ** (max(-1200, min(1200, delta)) / 120))
        self.box_capture.update(event.position())
        self.view_changed.emit()
        event.accept()

    def mousePressEvent(self, event):
        if event.button() in (Qt.MouseButton.MiddleButton, Qt.MouseButton.RightButton):
            self._preview_press = False
            if self.selection_ui:
                self.selection_ui.cancel()
            if self.human:
                self.human.cancel()
            self._normal_press = None
            self._pan_last = QPointF(event.position())
            self._pan_button = event.button()
            self._pan_started = event.button() == Qt.MouseButton.MiddleButton
            self._suppress_context_menu = False
            if self._pan_started:self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        if self.region_select and event.button() == Qt.MouseButton.LeftButton:
            self.box_capture.begin(event.position())
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self._normal_press = event.position()
            pt = self.mapToScene(event.position().toPoint())
            self.clicked_at.emit(pt.x(), -pt.y())
            inspection = getattr(self.window(), 'inspection', None)
            if inspection and inspection.preview_hit(pt.x(), -pt.y()) and not event.modifiers():
                self._preview_press = True
                event.accept()
                return
            if self.human and self.human.begin(event):
                event.accept()
                return
            if self.selection_ui and self.selection_ui.begin(event):
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._pan_last is not None:
            from ..camera import pan_by

            if not self._pan_started:
                if (event.position()-self._pan_last).manhattanLength()<QApplication.startDragDistance():
                    event.accept();return
                self._pan_started=True
                self._suppress_context_menu=True
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
            pan_by(self, event.position() - self._pan_last)
            self._pan_last = QPointF(event.position())
            self.view_changed.emit()
            event.accept()
            return
        if self.box_capture.active:
            self.box_capture.update(event.position())
            event.accept()
            return
        if self._preview_press:
            event.accept()
            return
        if self.selection_ui and self.selection_ui.move(event):
            event.accept()
            return
        if self.human and self.human.move(event):
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == self._pan_button and self._pan_last is not None:
            self._pan_last = None
            self._pan_button = None
            if self.region_select:
                self.setCursor(Qt.CursorShape.CrossCursor)
            else:
                self.unsetCursor()
            event.accept()
            return
        if event.button() != Qt.MouseButton.LeftButton:
            super().mouseReleaseEvent(event)
            return
        if self._preview_press:
            self._preview_press = False
            if (
                self._normal_press is not None
                and (event.position() - self._normal_press).manhattanLength()
                < QApplication.startDragDistance()
            ):
                pt = self.mapToScene(self._normal_press.toPoint())
                self.inspection_clicked.emit(pt.x(), -pt.y())
            self._normal_press = None
            event.accept()
            return
        if self.box_capture.active:
            bounds = self.box_capture.finish(event.position())
            if bounds is not None:
                self.region_picked.emit(bounds)
            event.accept()
            return
        if self.selection_ui and self.selection_ui.finish(event):
            event.accept()
            self._normal_press = None
            return
        if self.human and self.human.finish(event):
            event.accept()
            self._normal_press = None
            return
        super().mouseReleaseEvent(event)
        if (
            self._normal_press is not None
            and (event.position() - self._normal_press).manhattanLength()
            < QApplication.startDragDistance()
        ):
            pt = self.mapToScene(self._normal_press.toPoint())
            self.inspection_clicked.emit(pt.x(), -pt.y())
        self._normal_press = None

    def viewportEvent(self, event):
        # CustomContextMenu dispatch bypasses contextMenuEvent, so consume the
        # gesture's OS menu event before Qt emits customContextMenuRequested.
        if (event.type()==QEvent.Type.ContextMenu and
                event.reason()==QContextMenuEvent.Reason.Mouse and self._suppress_context_menu):
            self._suppress_context_menu=False
            event.accept();return True
        return super().viewportEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape and self.region_select:
            self.region_select = False
            self.region_cancelled.emit()
            self.setCursor(Qt.CursorShape.ArrowCursor)
            event.accept()
            return
        if event.key() == Qt.Key.Key_Escape:
            self._normal_press = None
            self._preview_press = False
            self.inspection_clear.emit()
        super().keyPressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if self.region_select:
            self.mousePressEvent(event)
            return
        self._preview_press = False
        from ..canvas_hits import local_module_at, native_module_at

        ident = local_module_at(self.window(), event.position())
        if ident:
            if self.human:
                self.human.cancel()
            self.object_activated.emit(ident)
            event.accept()
            return
        native = native_module_at(self.window(), event.position())
        if native:
            from PySide6.QtWidgets import QToolTip

            if self.human:
                self.human.cancel()
            if self.selection_ui:
                self.selection_ui.cancel()
            self._normal_press = None
            self.window().inspection.clear_trace()
            name = self.window().editor.w.layout_connectivity.instances[native].name
            message = f'{name} 是 Virtuoso 原生模块，在 CoLayout 中仅作黑盒使用，不能进入内部；请到 Virtuoso 编辑。'
            self.window().status.setText(message)
            QToolTip.showText(
                self.viewport().mapToGlobal(event.position().toPoint()),
                message,
                self.viewport(),
                QRect(),
                6500,
            )
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.routing_overlay:
            painter = QPainter(self.viewport())
            try:
                self.routing_overlay(painter)
            finally:
                painter.end()
        if self.drc_overlay:
            painter = QPainter(self.viewport())
            try:
                self.drc_overlay(painter)
            finally:
                painter.end()
        if self.inspection_overlay:
            painter = QPainter(self.viewport())
            try:
                self.inspection_overlay(painter)
            finally:
                painter.end()
        if self.selection_ui:
            painter = QPainter(self.viewport())
            try:
                self.selection_ui.paint(painter)
            finally:
                painter.end()
        if self.human:
            painter = QPainter(self.viewport())
            try:
                self.human.paint(painter)
            finally:
                painter.end()
        if self.guard_overlay:
            painter = QPainter(self.viewport())
            try:
                self.guard_overlay(painter)
            finally:
                painter.end()
