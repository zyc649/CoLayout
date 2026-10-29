"""Static, screen-width illumination; no blur effects, bitmaps or repaint timer."""
from math import hypot
from PySide6.QtCore import Qt,QRectF
from PySide6.QtGui import QColor,QPen,QLinearGradient,QBrush


def paint(painter,rect):
    painter.save()
    painter.setClipRect(rect,Qt.ClipOperation.IntersectClip)
    painter.fillRect(rect,QColor(255,230,169,7))
    tr=painter.worldTransform()
    sx=max(hypot(tr.m11(),tr.m12()),1e-9);sy=max(hypot(tr.m21(),tr.m22()),1e-9)
    dx=min(28/sx,rect.width()/3);dy=min(28/sy,rect.height()/3)
    x,y,xx,yy=rect.left(),rect.top(),rect.right(),rect.bottom()
    for area,start,end in (
        (QRectF(x,y,dx,rect.height()),(x,y),(x+dx,y)),
        (QRectF(xx-dx,y,dx,rect.height()),(xx,y),(xx-dx,y)),
        (QRectF(x,y,rect.width(),dy),(x,y),(x,y+dy)),
        (QRectF(x,yy-dy,rect.width(),dy),(x,yy),(x,yy-dy))):
        light=QLinearGradient(*start,*end)
        for stop,opacity in ((0,96),(.12,56),(.4,22),(1,0)):
            light.setColorAt(stop,QColor(255,227,160,opacity))
        painter.fillRect(area,QBrush(light))
    pen=QPen(QColor('#ffe6ac'));pen.setCosmetic(True);pen.setWidthF(1.3)
    painter.setPen(pen);painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRect(rect)
    painter.restore()
