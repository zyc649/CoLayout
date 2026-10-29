from PySide6.QtCore import QPointF,Qt
from PySide6.QtGui import QPainterPath
from colayout_lite.geometry import shape_figure
from colayout_lite.model import Shape
from colayout_lite.render import figure_path

def test_user_z_path_matches_native_converted_polygon_without_inner_seams():
    # Independent IC618 dbConvertPathToPolygon oracle, from new test copy.
    shape=Shape(kind='path',lpp=('M1','drawing'),points=((-300000,1120000),(-180000,1120000),(-180000,1000000),(-60000,1000000)),width=20000)
    actual=figure_path(shape_figure(shape));native=QPainterPath()
    pts=[(-300000,1110000),(-190000,1110000),(-190000,990000),(-60000,990000),(-60000,1010000),(-170000,1010000),(-170000,1130000),(-300000,1130000)]
    for i,(x,y) in enumerate(pts):(native.moveTo if i==0 else native.lineTo)(x,-y)
    native.closeSubpath()
    assert actual.subtracted(native).isEmpty() and native.subtracted(actual).isEmpty()
    assert actual.elementCount()==9  # exactly one 8-edge perimeter, no small squares

def test_closed_guard_path_keeps_its_hole_after_simplification():
    shape=Shape(kind='path',lpp=('M1','drawing'),points=((0,0),(1000,0),(1000,1000),(0,1000),(0,0)),width=100)
    path=figure_path(shape_figure(shape))
    assert path.contains(QPointF(0,-500)) and not path.contains(QPointF(500,-500))
