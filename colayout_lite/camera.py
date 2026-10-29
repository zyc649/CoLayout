"""View-only navigation, independent of selection and workspace commands."""
from PySide6.QtCore import QPointF,QRectF,Qt,QSize
from PySide6.QtGui import QTransform
from dataclasses import dataclass


@dataclass(frozen=True)
class CameraState:
    transform:QTransform
    bounds:QRectF
    center:QPointF
    viewport_size:QSize
    scroll:tuple


def capture(view):
    return CameraState(QTransform(view.transform()),QRectF(view.sceneRect()),
        view.mapToScene(view.viewport().rect().center()),view.viewport().size(),
        (view.horizontalScrollBar().value(),view.verticalScrollBar().value()))


def restore(view,state):
    view.setSceneRect(state.bounds);view.setTransform(state.transform)
    if view.viewport().size()==state.viewport_size:
        view.horizontalScrollBar().setValue(state.scroll[0]);view.verticalScrollBar().setValue(state.scroll[1])
    else:
        view.centerOn(state.center)
        # centerOn uses the viewport's half width while capture uses its
        # integer pixel center. Correct that rounding instead of accumulating
        # a one-pixel drift on every property-panel open/close.
        pixel=view.viewportTransform().map(state.center)-QPointF(view.viewport().rect().center())
        view.horizontalScrollBar().setValue(view.horizontalScrollBar().value()+round(pixel.x()))
        view.verticalScrollBar().setValue(view.verticalScrollBar().value()+round(pixel.y()))
    view.viewport().update()


def fit_bounds(view,bounds):
    """Scale-independent breathing room, including small viewport and PIN markers."""
    if bounds.isEmpty():return
    fraction=max(.06,32/max(100,min(view.viewport().width(),view.viewport().height())))
    pad=max(bounds.width(),bounds.height(),1)*fraction
    view.fitInView(bounds.adjusted(-pad,-pad,pad,pad),Qt.AspectRatioMode.KeepAspectRatio)


def displayed_bounds(window):
    from PySide6.QtWidgets import QGraphicsRectItem
    result=QRectF()
    for group in window.groups.values():
        if any(part.isVisible() for part in group.parts.values()):
            rect=group.selection_rect()
            if rect is not None:result=result.united(rect)
            for part in group.parts.values():
                if part.isVisible():result=result.united(part.sceneBoundingRect())
    for item in window._workspace_overlay_items:
        if isinstance(item,QGraphicsRectItem) and item.isVisible():result=result.united(item.sceneBoundingRect())
    return result


def navigation_room(view):
    # A fitted scene may be smaller than its viewport. Give scroll bars room
    # before navigating, otherwise Qt's centering alignment moves the anchor.
    visible=view.mapToScene(view.viewport().rect()).boundingRect()
    margin=max(visible.width(),visible.height(),1)*3
    view.setSceneRect(view.sceneRect().united(visible.adjusted(-margin,-margin,margin,margin)))


def zoom_at(view,pixel,factor):
    scale=abs(view.transform().m11())
    factor=max(1e-7,min(100,scale*factor))/max(scale,1e-12)
    navigation_room(view)
    anchor=view.mapToScene(pixel.toPoint())
    view.scale(factor,factor)
    after=view.mapToScene(pixel.toPoint())
    view.translate(after.x()-anchor.x(),after.y()-anchor.y())


def pan_by(view,pixels):
    navigation_room(view)
    center=QPointF(view.viewport().rect().center())
    old=view.mapToScene(center.toPoint())
    moved=view.mapToScene((center-pixels).toPoint())
    view.centerOn(old+(moved-old))
