"""World-anchored box gesture shared by drawing tools and region selection."""
from PySide6.QtCore import QPoint,QPointF,QRect,QRectF
from PySide6.QtWidgets import QRubberBand


class BoxCapture:
    def __init__(self,view):
        self.view=view;self.start=None;self.end=None
        self.band=QRubberBand(QRubberBand.Shape.Rectangle,view.viewport())

    @property
    def active(self):return self.start is not None

    def begin(self,pixel):
        self.start=self.view.mapToScene(pixel.toPoint());self.end=QPointF(self.start)
        self.refresh();self.band.show()

    def update(self,pixel):
        if self.active:self.end=self.view.mapToScene(pixel.toPoint());self.refresh()

    def refresh(self):
        if self.active:
            a=self.view.mapFromScene(self.start);b=self.view.mapFromScene(self.end)
            self.band.setGeometry(QRect(QPoint(min(a.x(),b.x()),min(a.y(),b.y())),QPoint(max(a.x(),b.x()),max(a.y(),b.y()))))

    def finish(self,pixel):
        self.update(pixel);result=None
        if self.active:
            screen=self.band.geometry();world=QRectF(self.start,self.end).normalized()
            if screen.width()>2 and screen.height()>2 and world.width()>0 and world.height()>0:
                result=(world.left(),-world.bottom(),world.right(),-world.top())
        self.cancel();return result

    def cancel(self):
        self.start=None;self.end=None;self.band.hide()
