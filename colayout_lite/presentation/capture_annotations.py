"""Snapshot annotations placed inside the image, with a separate legend footer."""

from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QColor, QPen, QFont, QFontMetricsF

REASONS = {
    'unattached': '未接',
    'partial_coverage': '部分覆盖',
    'net_unknown': '网络未知',
    'geometry_missing': '缺接入几何',
    'gate_requires_metal': '需金属引出',
}


def colors_for(components):
    return {
        cid: QColor.fromHsv((i * 137 + 145) % 360, 160, 250)
        for i, cid in enumerate(sorted(components))
    }


def font_for(unit):
    font = QFont('Microsoft YaHei UI')
    font.setPixelSize(max(12, round(15 * unit)))
    return font


def clamp(rect, inside):
    result = QRectF(rect)
    result.moveLeft(max(inside.left(), min(result.left(), inside.right() - result.width())))
    result.moveTop(max(inside.top(), min(result.top(), inside.bottom() - result.height())))
    return result


def labels(painter, viewport, entries, blocked, unit):
    """Prioritize targets; labels avoid each other and visible target copper."""
    painter.resetTransform()
    font = font_for(unit)
    painter.setFont(font)
    metrics = QFontMetricsF(font)
    safe = viewport.adjusted(8 * unit, 8 * unit, -8 * unit, -8 * unit)
    occupied = []
    result = []
    owner_boxes={e['owner']:e['owner_extent'] for e in entries if e.get('owner_extent') is not None}
    for entry in sorted(entries, key=lambda r: (not r['active'], not r.get('public_interface',False), r.get('context', False), r['id'])):
        anchor = entry['anchor']
        text = entry['text']
        display_text=entry.get('short_text',text)
        if not text:
            continue
        if not entry['active'] and len(occupied) >= 80:
            continue
        width = min(metrics.horizontalAdvance(display_text) + 12 * unit, safe.width())
        height = metrics.height() + 8 * unit
        if safe.height() < height:
            continue
        choices = []
        extent = entry['extent']
        owner=entry.get('owner_extent')
        band=safe
        if entry.get('role')=='instance':
            band=QRectF(safe.left(),max(safe.top(),extent.top()),safe.width(),
                        min(safe.bottom(),extent.bottom())-max(safe.top(),extent.top()))
            if band.height()<height:continue  # Explicit omission is preferable to a false row association.
        for step in range(1, 7):
            gap = step * (height + 4 * unit)
            locations=[
                (anchor.x() - width / 2, extent.top() - gap),
                (anchor.x() - width / 2, extent.bottom() + gap - height),
                (extent.right() + step * 10 * unit, anchor.y() - height / 2),
                (extent.left() - width - step * 10 * unit, anchor.y() - height / 2),
                (anchor.x() - width - gap, extent.top() - gap),
                (anchor.x() + gap, extent.bottom() + gap - height),
            ]
            if entry.get('role')=='instance':
                locations=[(anchor.x()-width/2,extent.top()+step*3*unit),
                           (extent.left()+step*3*unit,anchor.y()-height/2),
                           (extent.right()+step*5*unit,anchor.y()-height/2),
                           (extent.left()-width-step*5*unit,anchor.y()-height/2)]
            side=entry.get('side')
            if owner is not None and side:
                if side in ('left','right'):
                    edge=owner.left() if side=='left' else owner.right()
                    inward=edge+8*unit+step*width/2 if side=='left' else edge-width-8*unit-step*width/2
                    locations=[(x,anchor.y()-height/2+offset) for x in (edge-width-8*unit,edge+8*unit,inward)
                               for offset in (0,-gap,gap)]
                else:
                    edge=owner.top() if side=='top' else owner.bottom()
                    locations=[(anchor.x()-width/2+offset,y) for y in (edge-height-8*unit,edge+8*unit)
                               for offset in (0,-gap,gap)]
            for x, y in locations:
                rect = clamp(QRectF(x, y, width, height), band)
                overlap = sum(rect.intersects(old) for old in occupied)
                copper = sum(path.intersects(rect) for path in blocked)
                foreign=sum(rect.intersects(b) for uid,b in owner_boxes.items() if uid!=entry.get('owner'))
                score = overlap * 1e7 + foreign*1e6 + copper * 1e5 + (rect.center() - anchor).manhattanLength()
                choices.append((score, overlap, copper, rect))
        score, overlap, copper, rect = min(choices, key=lambda r: r[0])
        if not entry['active'] and (overlap or copper):
            continue
        color = QColor(entry['color'])
        painter.setPen(QPen(color, unit))
        endpoint = QPointF(
            max(rect.left(), min(anchor.x(), rect.right())),
            max(rect.top(), min(anchor.y(), rect.bottom())),
        )
        painter.drawLine(anchor, endpoint)
        painter.setBrush(color);painter.drawEllipse(anchor,2*unit,2*unit)
        painter.fillRect(rect, QColor(17, 21, 27, 238))
        painter.setPen(color)
        shown = metrics.elidedText(display_text, Qt.TextElideMode.ElideRight, int(width - 10 * unit))
        painter.drawText(
            rect.adjusted(5 * unit, 0, -5 * unit, 0),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            shown,
        )
        occupied.append(rect.adjusted(-2 * unit, -2 * unit, 2 * unit, 2 * unit))
        result.append(
            {
                'id': entry['id'],
                'text': text,
                'shown_text': shown,
                'active': entry['active'],
                'owner':entry.get('owner'),
                'side':entry.get('side'),
                'role':entry.get('role'),
                'anchor_fraction':[(anchor.x()-viewport.x())/viewport.width(),(anchor.y()-viewport.y())/viewport.height()],
                'owner_rect_fraction':[(owner.x()-viewport.x())/viewport.width(),(owner.y()-viewport.y())/viewport.height(),owner.width()/viewport.width(),owner.height()/viewport.height()] if owner is not None else None,
                'rect_fraction': [
                    (rect.x() - viewport.x()) / viewport.width(),
                    (rect.y() - viewport.y()) / viewport.height(),
                    rect.width() / viewport.width(),
                    rect.height() / viewport.height(),
                ],
                'overlaps_target': bool(copper),
                'overlaps_label': bool(overlap),
            }
        )
    return result
