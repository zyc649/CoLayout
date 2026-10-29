"""Bounded vector batches for disposable routing overlays, independent of zoom.

Preserve path order and cosmetic pens. Styles are part of the recording key;
camera changes replay vectors, never stretch pixels or rebuild geometry.
"""
from PySide6.QtCore import QPointF,QRectF
from PySide6.QtGui import QColor,QPen,QPicture,QPainter


class PreviewDrawing:
    def __init__(self,paths):
        self.paths=paths
        self.key=None
        self.batches=[]

    def paint(self,painter,visible,styles,override=None):
        colors={layer:override or tuple(styles.get(layer+'/drawing',{}).get('fill_rgb',[105,219,149]))
            for layer,_ in self.paths}
        key=tuple(sorted(colors.items()))
        if key!=self.key:
            batches=[]
            for start in range(0,len(self.paths),64):
                picture=QPicture();recorder=QPainter(picture);bounds=QRectF();previous=None
                try:
                    for layer,path in self.paths[start:start+64]:
                        value=colors[layer]
                        if value!=previous:
                            color=QColor(value) if isinstance(value,str) else QColor(*value)
                            pen=QPen(color,1.7);pen.setCosmetic(True);recorder.setPen(pen)
                            color.setAlpha(90);recorder.setBrush(color);previous=value
                        recorder.drawPath(path);bounds=bounds.united(path.boundingRect())
                finally:recorder.end()
                batches.append((bounds,picture))
            self.key=key;self.batches=batches
        for bounds,picture in self.batches:
            if visible.intersects(bounds):painter.drawPicture(QPointF(),picture)
