"""Snapshot-only readable layers, physical highlights and non-overlapping callouts."""

from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QColor, QPen, QBrush, QFontMetricsF
from PySide6.QtWidgets import QGraphicsSimpleTextItem
from ..render import NativeFigureItem
from ..inspection_view import polygon_path
from ..circuit.net_names import display_net, pin_signal_names
from ..editor import projected
from ..regions.query import object_bounds
from .capture_annotations import colors_for, labels, REASONS, font_for


def install(view, args, data):
    # The real-time batch renderer intentionally uses native style packets.
    # Snapshot styling must use these same vector items through their painter.
    view.canvas.set_preview_enabled(False)
    tr = view.canvas.viewportTransform()
    scale = view.editor.profile.dbu_per_micron
    x, y, xx, yy = (v * scale for v in data['bounds'])
    captured = tr.mapRect(QRectF(x, -yy, xx - x, yy - y))
    unit = max(0.8, captured.width() / 1600)
    layers = data['layers']
    selected = data['mode'] != 'none'
    metals = {r['layer'] for r in view.editor.profile.layers if r.get('material') == 'metal'}
    for group in view.groups.values():
        for item in group.childItems():
            if isinstance(item, NativeFigureItem):
                layer = item.style['lpp'][0]
                if layers is not None and layer not in layers:
                    item.setVisible(False)
                    continue
                color = QColor(*item.style['outline_rgb'])
                if layer in metals:
                    hue = color.hue() if color.hue() >= 0 else 190
                    color = QColor.fromHsv(
                        hue, min(190, max(100, color.saturation())), max(215, color.value())
                    )
                elif not item.style['is_cut']:
                    color.setAlpha(95 if selected else 150)
                pen = QPen(color, (1.8 if args.style == 'outline' else 1.2) * unit)
                pen.setCosmetic(True)
                fill = QColor(color)
                fill.setAlpha(145 if layer in metals else 60)
                brush = QBrush(fill) if args.style == 'native' else QBrush(Qt.BrushStyle.NoBrush)
                item.snapshot_style = (pen, brush)
                item.update()
            elif isinstance(item, QGraphicsSimpleTextItem):
                item.setVisible(False)
    colors = colors_for(data['components'])
    names = pin_signal_names(data['pins'])
    conflicts = {pid for row in data['summary']['shorts'] for pid in row['pin_ids']}
    issues = {row['pin_id']: row['reason'] for row in data['summary']['pin_issues']}
    node_paths = [
        (node, polygon_path(node['geometry']))
        for node in data['nodes']
        if layers is None or node['layer'] in layers
    ]
    via_paths = [
        polygon_path(via['geometry'])
        for via in data['vias']
        if layers is None or via['cut_layer'] in layers
    ]
    objects = projected(view.editor.w)
    display = {
        'rendering': 'native vector geometry; strokes clipped inside copper; preview-scaled labels',
        'style': args.style,
        'layers': args.layers,
        'labels': {
            'pins': args.pin_names,
            'instances': args.instance_names,
            'nets': args.net_names,
        },
        'dbu_per_micron': scale,
        'annotations': [],
        'legend': 'separate footer outside geometry' if selected else None,
    }

    def paint(painter):
        painter.save()
        try:
            painter.resetTransform()
            if selected:
                painter.fillRect(captured, QColor(16, 20, 27, 195))
            painter.setClipRect(captured)
            painter.setTransform(tr)
            for node, path in node_paths:
                color = colors[node['component_id']]
                fill = QColor(color)
                fill.setAlpha(238 if args.style == 'native' else 110)
                pen = QPen(color, 3.2 * unit)
                pen.setCosmetic(True)
                painter.save()
                painter.setClipPath(path, Qt.ClipOperation.IntersectClip)
                painter.setPen(pen)
                painter.setBrush(fill)
                painter.drawPath(path)
                painter.restore()
            for path in via_paths:
                painter.save()
                painter.setClipPath(path, Qt.ClipOperation.IntersectClip)
                pen = QPen(QColor('#fff0a0'), 2.3 * unit)
                pen.setCosmetic(True)
                painter.setPen(pen)
                painter.setBrush(QColor(255, 214, 94, 210))
                painter.drawPath(path)
                painter.restore()
            painter.resetTransform()
            entries = []
            requested_pins={}
            requested_instances={}
            owners={pin['owner']:pin for pin in data['pins'] if pin.get('public_interface')
                    and pin.get('owner_bbox') and pin['owner']!=view.editor.scope_id}
            owner_tags={uid:'B'+str(i+1) for i,uid in enumerate(sorted(owners))} if args.instance_names else {}
            display['module_labels']=[]
            painter.setFont(font_for(unit))
            module_headers=[]
            metrics=QFontMetricsF(painter.font())
            for uid,tag in owner_tags.items():
                pin=owners[uid];(a,b),(c,d)=pin['owner_bbox'];r=tr.mapRect(QRectF(a,-d,c-a,d-b))
                if not captured.intersects(r):continue
                caption=tag+' · '+pin.get('owner_name',uid[:8])
                width=min(metrics.horizontalAdvance(caption)+10*unit,max(20*unit,r.width()-10*unit))
                header=QRectF(r.left()+5*unit,r.top()+4*unit,width,metrics.height()+4*unit)
                module_headers.append(header)
                painter.fillRect(header,QColor(17,21,27,238))
                painter.setPen(QColor('#9fcaff'))
                painter.drawText(header,Qt.AlignmentFlag.AlignLeft,metrics.elidedText(caption,Qt.TextElideMode.ElideRight,int(width)))
                display['module_labels'].append({'tag':tag,'owner':uid,'name':pin.get('owner_name')})
            for pin in data['pins']:
                visible = [
                    tr.map(polygon_path(g))
                    for layer, g in pin['figures']
                    if layers is None or layer in layers
                ]
                candidates = [path for path in visible if path.boundingRect().intersects(captured)]
                if not candidates:
                    continue
                extent = QRectF(candidates[0].boundingRect())
                for path in candidates[1:]:
                    extent = extent.united(path.boundingRect())
                extent = extent.intersected(captured)
                active = pin['id'] in data['pin_ids']
                error = pin['id'] in conflicts or pin['id'] in issues
                color = '#ff998e' if error else '#f0f5fc' if active else '#8594a5'
                pen = QPen(QColor(color), (1.2 if active else 0.7) * unit)
                if pin['local']:
                    pen.setStyle(Qt.PenStyle.DashLine)
                painter.setPen(pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                seen = set()
                for path in candidates:
                    key = (
                        path.boundingRect().x(),
                        path.boundingRect().y(),
                        path.boundingRect().width(),
                        path.boundingRect().height(),
                    )
                    if key in seen:
                        continue
                    seen.add(key)
                    painter.drawPath(path)
                anchor = extent.center()
                label = (
                    (pin.get('display_name',pin['label']) if args.instance_names else pin['name']) if args.pin_names else ''
                )
                if args.net_names and pin['net'] is not None:
                    net_label = display_net(pin['net'], names)
                    if net_label != label:
                        label += (' · ' if label else '') + net_label
                if selected and not active and not pin['local']:
                    label = ''
                if active and label:
                    if pin['id'] in conflicts:
                        label += ' · 短接'
                    elif pin['id'] in issues:
                        label += ' · ' + REASONS.get(issues[pin['id']], issues[pin['id']])
                    if pin.get('layer_mode') == 'any_metal':
                        label += ' · 任意金属'
                if pin['id'] in conflicts:
                    # Keep the full symbol inside the legal picture, with a leader to its real position.
                    spot = QPointF(
                        max(
                            captured.left() + 8 * unit, min(anchor.x(), captured.right() - 8 * unit)
                        ),
                        max(
                            captured.top() + 8 * unit, min(anchor.y(), captured.bottom() - 8 * unit)
                        ),
                    )
                    painter.setPen(QPen(QColor('#ff776f'), 2 * unit))
                    painter.drawLine(spot, anchor)
                    for dy in (-1, 1):
                        painter.drawLine(
                            spot + QPointF(-5 * unit, dy * 5 * unit),
                            spot + QPointF(5 * unit, -dy * 5 * unit),
                        )
                if label:requested_pins[pin['id']]={'pin_id':pin['id'],'owner':pin['owner'],'display_name':pin.get('display_name',pin['label'])}
                if label and (active or pin.get('public_interface') or extent.width() > 14 * unit or extent.height() > 14 * unit):
                    owner_rect=None
                    if pin.get('public_interface') and pin.get('owner_bbox'):
                        (a,b),(c,d)=pin['owner_bbox'];owner_rect=tr.mapRect(QRectF(a,-d,c-a,d-b))
                    short=label
                    if pin['owner'] in owner_tags:short=owner_tags[pin['owner']]+' · '+pin['name']
                    elif pin.get('guard'):short='保护环 '+pin['owner'][-4:]+' · '+pin['name']
                    entries.append(
                        {
                            'id': pin['id'],
                            'active': active,
                            'public_interface':pin.get('public_interface',False),
                            'anchor': anchor,
                            'extent': extent,
                            'text': label,
                            'short_text':short,
                            'role':'pin','owner':pin['owner'],'owner_extent':owner_rect,
                            'side':pin.get('side') if pin.get('public_interface') else None,
                            'color': color,
                        }
                    )
            if args.instance_names:
                for uid, group in view.groups.items():
                    obj = objects.get(uid)
                    if (
                        not obj
                        or obj.kind not in ('inst', 'mpp', 'mosaic')
                        or not any(part.isVisible() for part in group.parts.values())
                    ):
                        continue
                    bounds = object_bounds(view.editor.w, obj, view.editor.profile)
                    if not bounds:
                        continue
                    (a, b), (c, d) = bounds
                    rect = tr.mapRect(QRectF(a, -d, c - a, d - b))
                    if not captured.intersects(rect):
                        continue
                    name=obj.attributes.get('name',obj.mpp.name if obj.mpp else uid[:8])
                    requested_instances[uid]={'id':uid,'name':name,
                                              'bounds_um':[v/scale for point in bounds for v in point]}
                    # Register visible requested instances before zoom/density rejection.
                    if rect.width() < 60 * unit:
                        requested_instances[uid]['reason']='below_label_minimum_width'
                        continue
                    rect = rect.intersected(captured)
                    entries.append(
                        {
                            'id': uid,
                            'active': False,
                            'context': True,
                            'anchor': rect.center(),
                            'extent': rect,
                            'text': obj.attributes.get(
                                'name', obj.mpp.name if obj.mpp else uid[:8]
                            ),
                            'color': '#a2afbe',
                            'short_text':'保护环 '+uid[-4:] if obj.mpp and len(name)>18 else name,
                            'role':'instance','owner':uid,'owner_extent':rect,
                        }
                    )
            blocked = [tr.map(path) for _, path in node_paths] + [
                tr.map(path) for path in via_paths
            ] + module_headers
            display['annotations'] = labels(painter, captured, entries, blocked, unit)
            shown={row['id'] for row in display['annotations']}
            display['omitted_pin_labels']=[{**row,'reason':'label_density_or_zoom','next':'capture target object or PIN, or a smaller bounds_um'} for pid,row in requested_pins.items() if pid not in shown]
            display['pin_label_counts']={'visible_requested':len(requested_pins),'shown':len(set(requested_pins)&shown),'omitted':len(set(requested_pins)-shown)}
            display['omitted_instance_labels']=[{'reason':'row_band_density_or_zoom',**row,'next':'capture this object or a smaller bounds_um at a higher resolution'} for uid,row in requested_instances.items() if uid not in shown]
            display['instance_label_counts']={'visible_requested':len(requested_instances),'shown':len(set(requested_instances)&shown),'omitted':len(set(requested_instances)-shown)}
        finally:
            painter.restore()

    view.canvas.inspection_overlay = paint
    view.canvas.invalidate_preview()
    return display
