"""Immutable world-space PIN facts and one bounded vector presentation frame.

These are disposable view caches, never workspace or connectivity evidence.
Unprepared records remain supported by render_pins for tests/standalone callers.
"""
from dataclasses import dataclass
from PySide6.QtCore import QRectF
from PySide6.QtGui import QPicture,QPainter,QTransform


@dataclass(frozen=True)
class PinGeometry:
    bounds: QRectF
    figures: tuple
    center_inside: tuple
    max_width: float
    max_height: float


def facts(record):
    cached=record.get('geometry_info')
    if cached is not None:return cached
    figures=tuple(path.boundingRect() for path in record['paths']);bounds=QRectF()
    for rect in figures:bounds=bounds.united(rect)
    return PinGeometry(bounds,figures,tuple(path.contains(rect.center()) for path,rect in zip(record['paths'],figures)),
        max((r.width() for r in figures),default=0),max((r.height() for r in figures),default=0))


def prepared_record(pin,paths):
    record={'pin':pin,'paths':paths};record['geometry_info']=facts(record);return record


def translated_record(record,pin,dx,dy):
    data=facts(record);tr=QTransform.fromTranslate(dx,dy)
    return {'pin':pin,'paths':[tr.map(path) for path in record['paths']],
        'geometry_info':PinGeometry(data.bounds.translated(dx,dy),tuple(r.translated(dx,dy) for r in data.figures),
            data.center_inside,data.max_width,data.max_height)}


class PinFrameCache:
    """Replay vector commands only at exactly the view/state that recorded them."""
    def __init__(self):
        self.key=None;self.picture=None;self.hits=[];self.builds=0;self.reuses=0

    def paint(self,painter,key,render):
        if key==self.key and self.picture is not None:
            picture=self.picture;hits=self.hits;self.reuses+=1
        else:
            picture=QPicture();recording=QPainter(picture);recording.setRenderHints(painter.renderHints())
            try:hits=render(recording)
            finally:recording.end()
            self.builds+=1
            if picture.size()<=8*1024*1024:self.picture=picture;self.key=key;self.hits=hits
            else:self.picture=None;self.key=None;self.hits=[]
        painter.save()
        try:painter.resetTransform();painter.drawPicture(0,0,picture)
        finally:painter.restore()
        return hits
