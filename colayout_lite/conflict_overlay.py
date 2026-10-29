"""Mark conflicting terminals, without pretending to locate a physical short."""
from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor,QPen


def terminals(graph,trace):
    pins={p['id']:p for p in graph['pins']};marks=[]
    for conflict in trace.get('conflicts',[]):
        shown=set()
        for uid in conflict['pin_ids']:
            pin=pins[uid]
            if pin['net'] in shown or not pin['figures']:continue
            g=pin['figures'][0][1];point=g.representative_point();shown.add(pin['net'])
            marks.append((QPointF(point.x,-point.y),pin['label'],pin['net']))
    return marks


def paint(painter,transform,viewport,marks,color):
    painter.save();painter.resetTransform();painter.setPen(QPen(QColor(color),2))
    try:
        for point,label,net in marks:
            p=transform.map(point)+QPointF(7,-7)
            if not viewport.contains(p):continue
            painter.drawLine(p+QPointF(-4,-4),p+QPointF(4,4))
            painter.drawLine(p+QPointF(-4,4),p+QPointF(4,-4))
    finally:painter.restore()
