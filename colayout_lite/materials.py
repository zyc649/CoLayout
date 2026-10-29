"""Physical material extraction shared by DRC, connectivity and policies.

Uses native vector data; never reads graphics items or screen pixels.
"""

from dataclasses import dataclass
from math import sqrt,isfinite
from shapely.geometry import Polygon, box, LineString
from shapely import affinity
from shapely.strtree import STRtree
from .editor import projected
from .geometry import shape_figure, via_figures, transform, compose, ORIENT
from .geometry_paths import figure_path
from .scene import figures_by_owner
from .hierarchy import node_info


@dataclass
class Physical:
    owner: str
    layer: str
    geometry: object
    inside_instance: bool = False
    path: tuple = ()
    width: float | None = None
    skeleton: object = None
    purpose: str = 'drawing'


def polygon_from_figure(figure):
    if figure['kind']=='rect':
        (x,y),(xx,yy)=figure['bbox']
        x,y,xx,yy=map(float,(x,y,xx,yy))
        if all(isfinite(v) and v.is_integer() for v in (x,y,xx,yy)) and x<xx and y<yy:
            # Same contour/start point as the existing Qt rectangle path.
            # Restrict the shortcut to integer DBU rectangles. Keep Qt's
            # endpoint arithmetic; other kinds still use its exact
            # path stroker/odd-even contours, including native holes/caps.
            right=x+(xx-x);bottom=-(-yy+(yy-y))
            return Polygon([(right,yy),(right,bottom),(x,bottom),(x,yy)])
    path = figure_path(figure).simplified()
    geometry = Polygon()
    for ring in path.toSubpathPolygons():
        points = [(p.x(), p.y()) for p in ring]
        # figure_path uses layout coordinates (Qt y is inverted there).
        points = [(x, -y) for x, y in points]
        if len(points) >= 3:
            p = Polygon(points)
            if not p.is_valid:
                raise ValueError('Invalid physical display polygon')
            geometry = geometry.symmetric_difference(p)
    return geometry


def placement_delta(before, after):
    a, b, c, d = ORIENT[before.orientation]
    x, y = before.origin
    return compose(
        transform(after.origin, after.orientation), (a, c, b, d, -a * x - c * y, -b * x - d * y)
    )


def apply_delta(g, t):
    if tuple(t)==(1,0,0,1,0,0):
        return g
    return affinity.affine_transform(g, [t[0], t[1], t[2], t[3], t[4], t[5]])


def extract(w, p, region, halo, checkpoint=lambda: None, *, owner_filter=None):
    objects = projected(w)
    roi = box(*region.bbox[0], *region.bbox[1])
    context = roi.buffer(halo, join_style='mitre')
    chosen = set()
    warnings = []
    deltas = {}
    from .model import Object

    generated = {
        uid: Object.model_validate(raw)
        for preview in w.guard_previews.values()
        for uid, raw in preview['objects'].items()
    }
    for uid, o in objects.items():
        checkpoint()
        if owner_filter is not None and uid not in owner_filter:
            continue
        if o.placement and uid in w.baseline.objects:
            original = w.baseline.objects[uid].placement
            if original:
                deltas[uid] = placement_delta(original, o.placement)
        elif o.mpp and uid in generated:
            deltas[uid] = placement_delta(generated[uid].placement, o.placement)
        bounds = box(*o.bbox[0], *o.bbox[1]) if o.bbox else None
        if o.shape:
            if o.shape.kind == 'stdVia':
                boxes = [box(*f['bbox'][0], *f['bbox'][1]) for f in via_figures(o.shape, p)]
                from shapely.ops import unary_union

                bounds = unary_union(boxes)
            elif o.shape.bbox:
                bounds = box(*o.shape.bbox[0], *o.shape.bbox[1])
            elif o.shape.points:
                xs, ys = zip(*o.shape.points)
                margin = max(o.shape.width or 0, o.shape.begin_extension, o.shape.end_extension) * 2
                for cap in (o.shape.begin_custom, o.shape.end_custom):
                    if cap:
                        margin = max(margin, sum(cap.model_dump().values()) * 2)
                bounds = box(min(xs) - margin, min(ys) - margin, max(xs) + margin, max(ys) + margin)
        elif bounds is not None and uid in deltas and not o.mpp:
            bounds = apply_delta(bounds, deltas[uid])
        if bounds is None or not bounds.intersects(context):
            continue
        chosen.add(uid)
        node = w.baseline.display.get('nodes', {}).get(o.attributes.get('master_key'))
        if o.kind in ('inst', 'mosaic') and (node is None or node_info(node).get('collapsed')):
            warnings.append(
                {
                    'kind': 'unexpanded_instance',
                    'uid': uid,
                    'name': o.attributes.get('name'),
                    'message': '内部几何缓存不完整，本地检查不能覆盖模块内部。',
                }
            )
    modes = {u: 'full' for u in chosen}
    if w.baseline.display.get('nodes'):
        imported, styles = figures_by_owner(w.baseline, owner_filter=chosen, modes=modes)
    else:
        imported, styles = {}, {}
        if any(not objects[u].shape for u in chosen):
            warnings.append({'kind': 'missing_display_cache'})
    for preview in w.guard_previews.values():
        from .model import Object

        members = {
            k: Object.model_validate(v) for k, v in preview['objects'].items() if k in chosen
        }
        if members:
            extra, extra_styles = figures_by_owner(
                w.baseline, display=preview['display'], objects=members, owner_filter=set(members)
            )
            imported.update(extra)
            styles.update(extra_styles)
    physical = []
    for uid in sorted(chosen):
        checkpoint()
        o = objects[uid]
        if o.shape:
            figures = (
                via_figures(o.shape, p) if o.shape.kind == 'stdVia' else [shape_figure(o.shape)]
            )
        else:
            figures = imported.get(uid, [])
        for f in figures:
            layer = (f.get('lpp') or [f.get('style', '').split('/')[0]])[0]
            lpp=f.get('lpp') or f.get('style','').split('/')
            purpose=lpp[1] if len(lpp)>1 else 'drawing'
            if f.get('geometry', {}).get('opaque_type') or f.get('interface'):
                warnings.append({'kind': 'unavailable_physical_geometry', 'uid': uid})
                continue
            if layer.startswith('__') or f['kind'] not in ('rect', 'polygon', 'path', 'pathSeg'):
                continue
            g = polygon_from_figure(f)
            if not o.shape and uid in deltas:
                g = apply_delta(g, deltas[uid])
            if g.is_empty or not g.intersects(context):
                continue
            skeleton = None
            width = None
            if f['kind'] == 'rect':
                x, y, xx, yy = g.bounds
                if g.equals(box(x, y, xx, yy)):
                    width = min(xx - x, yy - y)
                    skeleton = (
                        LineString([(x, (y + yy) / 2), (xx, (y + yy) / 2)])
                        if xx - x >= yy - y
                        else LineString([((x + xx) / 2, y), ((x + xx) / 2, yy)])
                    )
            elif o.shape and o.shape.kind in ('path', 'pathSeg'):
                width = o.shape.width / (sqrt(2) if o.shape.width_basis == 'oa_diagonal' else 1)
                skeleton = LineString(o.shape.points)
            elif o.mpp and f['kind'] in ('path', 'pathSeg'):
                width = f.get('geometry', {}).get('width')
                points = f.get('geometry', {}).get('points')
                if width and points:
                    skeleton = LineString(points)
                    if uid in deltas:
                        skeleton = apply_delta(skeleton, deltas[uid])
            physical.append(
                Physical(
                    uid,
                    layer,
                    g,
                    o.kind in ('inst', 'mosaic'),
                    tuple(f.get('occurrence_path', [])),
                    width,
                    skeleton,
                    purpose,
                )
            )
    return physical, objects, warnings, roi, context


class AssociationIndex:
    def __init__(self, physical):
        self.rows = physical
        self.tree = STRtree([r.geometry for r in physical])

    def query(self, geometry):
        return (self.rows[int(i)] for i in self.tree.query(geometry, predicate='intersects'))


def associate(physical, objects, geometry, *, limit=32):
    matches = {}
    near = geometry.buffer(0.001)
    indexed=isinstance(physical, AssociationIndex)
    for row in physical.query(near) if indexed else physical:
        # STRtree.query(predicate='intersects') already performed this exact
        # predicate on the same geometry. The list fallback still needs it.
        if row.owner in matches or (not indexed and not row.geometry.intersects(near)):
            continue
        o = objects[row.owner]
        matches[row.owner] = {
            'uid': row.owner,
            'name': o.attributes.get('name'),
            'kind': o.kind,
            'inside_instance': row.inside_instance,
            'inside_mpp': bool(o.mpp),
            'read_only_reason': o.read_only_reason,
            'group_uid': o.group_uid,
            'occurrence_path': row.path,
        }
        if len(matches) >= limit:
            break
    return tuple(matches.values())
