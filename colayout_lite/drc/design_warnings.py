"""Configurable editing advice, separate from foundry errors and connectivity."""

from shapely.geometry import box, LineString
from ..model import digest
from ..editor import projected
from ..regions.query import object_bounds


def blocking(marker):
    details = marker.get('details', {}) if isinstance(marker, dict) else marker.details
    return details.get('category') != 'design_warning'


def straight_runs(points):
    """Collinear subdivision (including backtracking) cannot hide a long run."""
    run = []
    orientation = None
    for start, end in zip(points, points[1:]):
        kind = (
            'vertical'
            if start[0] == end[0] and start[1] != end[1]
            else 'horizontal'
            if start[1] == end[1] and start[0] != end[0]
            else None
        )
        if kind != orientation or kind is None:
            if run:
                yield orientation, run
            run = [start, end] if kind else []
            orientation = kind
        elif kind:
            run.append(end)
    if run:
        yield orientation, run


def run(w, technology, settings, region, *, checkpoint=lambda: None, owner_filter=None):
    from .models import Marker
    from .local import bounds

    roi = box(*region.bbox[0], *region.bbox[1])
    scale = technology.dbu_per_micron
    objects = projected(w)
    if owner_filter is None:
        from .scope import selection
        owner_filter, _ = selection(w, region)
    result = []

    def emit(uid, code, message, geometry, layers, details):
        clipped = geometry.intersection(roi)
        if clipped.is_empty:
            return
        detail = {
            'category': 'design_warning',
            'source': 'user DRC design-warning settings',
            **details,
        }
        ident = digest([code, uid, bounds(geometry), details])[:24]
        result.append(
            Marker(
                id=ident,
                rule_id='design.' + code,
                message=message,
                severity='warning',
                bbox=bounds(clipped),
                layers=tuple(layers),
                objects=({'uid': uid, 'kind': objects[uid].kind},),
                association='local_geometry',
                details=detail,
            )
        )

    for uid, obj in objects.items():
        checkpoint()
        if uid not in owner_filter or obj.read_only_reason or not obj.shape:
            continue
        shape = obj.shape
        extent = object_bounds(w, obj, technology)
        if extent is None or not box(*extent[0], *extent[1]).intersects(roi):
            continue
        if shape.kind in ('path', 'pathSeg'):
            layer = shape.lpp[0]
            direction = settings.directions.get(layer)
            if direction and direction.enabled:
                for kind, points in straight_runs(shape.points):
                    axis = 0 if kind == 'horizontal' else 1
                    length = (max(p[axis] for p in points) - min(p[axis] for p in points)) / scale
                    if kind != direction.preferred and length > direction.reverse_limit_um + 1e-12:
                        emit(
                            uid,
                            'reverse_direction',
                            f'{layer} 连续逆向段 {length:g} µm 超过 {direction.reverse_limit_um:g} µm',
                            LineString(points).buffer(shape.width / 2, cap_style='flat'),
                            [layer],
                            {
                                'actual_length_um': length,
                                'limit_um': direction.reverse_limit_um,
                                'preferred': direction.preferred,
                                'segment_points_um': [[x / scale, y / scale] for x, y in points],
                            },
                        )
        elif shape.kind == 'stdVia' and settings.via_enabled:
            definition = technology.vias[shape.via_definition]
            params = technology.effective_via(shape)
            roles = {
                row['layer']: row.get('material')
                for row in technology.layers
                if row['purpose'] == 'drawing'
            }
            pair = [definition['layer1'], definition['layer2']]
            if not all(roles.get(layer) == 'metal' for layer in pair):
                continue
            count = params['cutRows'] * params['cutColumns']
            if count < settings.minimum_cuts:
                emit(
                    uid,
                    'cut_count',
                    f'{pair[0]}–{pair[1]} 只有 {count} 个切孔。模拟部分通常应避免单孔，建议至少 {settings.minimum_cuts} 个；数字部分可按设计要求使用单孔。',
                    box(*extent[0], *extent[1]),
                    pair,
                    {
                        'definition': shape.via_definition,
                        'actual_cuts': count,
                        'minimum_cuts': settings.minimum_cuts,
                    },
                )
    return result
