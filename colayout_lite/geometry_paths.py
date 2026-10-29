"""Shared exact vector outlines for rendering and physical checks.

QtCore/QtGui provide the verified stroker; this module creates no widgets,
scene, application or display cache. Coordinates in paths use Qt Y-down.
Keep native end/corner semantics unchanged when replacing the geometry backend.
"""

import math
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QPainterPath, QPainterPathStroker


def box_rect(box):
    (x1, y1), (x2, y2) = box
    return QRectF(x1, -y2, x2 - x1, y2 - y1)


def figure_path(figure):
    """Physical outline, not a thick cosmetic pen or a bounding-box substitute."""
    path = QPainterPath()
    path.setFillRule(Qt.FillRule.OddEvenFill)
    kind, g = figure['kind'], figure['geometry']
    if kind == 'rect':
        path.addRect(box_rect(figure['bbox']))
    elif kind == 'ellipse':
        path.addEllipse(box_rect(figure['bbox']))
    elif kind == 'polygon' or (kind == 'pathSeg' and g.get('boundary')):
        for n, (x, y) in enumerate(g['boundary'] if kind == 'pathSeg' else g['points']):
            (path.moveTo if n == 0 else path.lineTo)(x, -y)
        path.closeSubpath()
    elif kind in ('path', 'pathSeg', 'line'):
        points = [list(p) for p in g['points']]
        if len(points) < 2:
            return path
        g = dict(g)
        if kind == 'pathSeg':
            if all(a != b for a, b in zip(points[0], points[-1])) and not g.get(
                'perpendicular_units'
            ):
                g['width'] /= math.sqrt(2)
                g['begin_extension'] /= math.sqrt(2)
                g['end_extension'] /= math.sqrt(2)
            for side in ('begin', 'end'):
                if g.get(side + '_style') == 'extend':
                    g[side + '_extension'] = g['width'] / 2
        if kind == 'pathSeg' or g.get('style') == 'varExtendExtend':
            for idx, neighbor, ext in [(0, 1, g['begin_extension']), (-1, -2, g['end_extension'])]:
                dx = points[idx][0] - points[neighbor][0]
                dy = points[idx][1] - points[neighbor][1]
                length = math.hypot(dx, dy)
                if length:
                    points[idx][0] += ext * dx / length
                    points[idx][1] += ext * dy / length
        closed = points[0] == points[-1]
        for n, (x, y) in enumerate(points):
            (path.moveTo if n == 0 else path.lineTo)(x, -y)
        if closed:
            path.closeSubpath()
        if kind == 'line':
            return path
        style = g.get('style') or 'truncateExtend'
        styles = {
            'truncateExtend': (Qt.PenCapStyle.FlatCap, Qt.PenJoinStyle.MiterJoin),
            'extendExtend': (Qt.PenCapStyle.SquareCap, Qt.PenJoinStyle.MiterJoin),
            'varExtendExtend': (Qt.PenCapStyle.FlatCap, Qt.PenJoinStyle.MiterJoin),
            # IC618 roundRound is the native octagonal approximation, not a
            # circular Qt cap/join (verified against converted native polygons).
            'roundRound': (Qt.PenCapStyle.FlatCap, Qt.PenJoinStyle.BevelJoin),
        }
        if style not in styles:
            raise ValueError('Unsupported native path style: ' + style)
        cap, join = styles[style]
        stroke = QPainterPathStroker()
        stroke.setWidth(g['width'])
        stroke.setCapStyle(cap)
        stroke.setJoinStyle(join)
        stroke.setMiterLimit(20)
        # createStroke describes overlapping segment/join contours. Drawing
        # their outlines directly exposes internal square seams at bends.
        # Merge once during geometry construction; never alter the DBU model.
        path = stroke.createStroke(path).simplified()
        if style == 'roundRound' and not closed:
            radius = g['width'] / 2
            for idx, neighbor in [(0, 1), (-1, -2)]:
                x, y = points[idx]
                dx = x - points[neighbor][0]
                dy = y - points[neighbor][1]
                length = math.hypot(dx, dy)
                ux, uy = dx / length, dy / length
                nx, ny = -uy, ux
                vertices = [
                    (x + nx * radius, y + ny * radius),
                    (
                        x + ux * radius * 2 / 3 + nx * radius / 3,
                        y + uy * radius * 2 / 3 + ny * radius / 3,
                    ),
                    (
                        x + ux * radius * 2 / 3 - nx * radius / 3,
                        y + uy * radius * 2 / 3 - ny * radius / 3,
                    ),
                    (x - nx * radius, y - ny * radius),
                ]
                cap_path = QPainterPath()
                for i, (px, py) in enumerate(vertices):
                    (cap_path.moveTo if i == 0 else cap_path.lineTo)(px, -py)
                cap_path.closeSubpath()
                path = path.united(cap_path)
    else:
        # An explicitly reported proxy; do not pretend that it is exact geometry.
        path.addRect(box_rect(figure['bbox']))
    return path
