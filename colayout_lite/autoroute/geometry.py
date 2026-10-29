"""Geometry helpers for the public routing snapshot, independent of Editor."""
from shapely.geometry import shape, mapping, box, Point, LineString
from shapely.ops import unary_union
from shapely import affinity
from .models import Figure


def decode(value):
    geometry = shape(value)
    if geometry.geom_type not in ('Polygon', 'MultiPolygon') or geometry.is_empty or not geometry.is_valid:
        raise ValueError('Expected nonempty valid polygonal geometry')
    import math
    if not all(math.isfinite(v) for v in geometry.bounds):raise ValueError('Non-finite geometry')
    return geometry


def figure(layer, geometry):
    return Figure(layer=layer, geometry=mapping(geometry))


def parts(geometry):
    return [geometry] if geometry.geom_type == 'Polygon' else [p for p in geometry.geoms if p.geom_type == 'Polygon' and p.area]


def shape_figures(value, problem):
    if value.kind == 'stdVia':
        via=next((v for v in problem.via_rules if v.name==value.via_definition),None)
        if via is None:raise ValueError('Via is outside selected layer graph')
        return [(f.layer, affinity.translate(decode(f.geometry), *value.origin)) for f in via.footprints]
    if value.kind == 'rect':return [(value.lpp[0], box(*value.bbox[0], *value.bbox[1]))]
    return [(value.lpp[0], LineString(value.points).buffer(value.width / 2, cap_style='square', join_style='mitre'))]


def layer_union(figures):
    layers = {}
    for layer, geometry in figures:layers.setdefault(layer, []).append(geometry)
    return {layer: unary_union(values) for layer, values in layers.items()}


def landing_box(geometry, width, grid, bounds=None):
    from math import floor,ceil
    from ..model import LiteError
    a,b,c,d=geometry.bounds;dx=max(0,(width-(c-a))/2);dy=max(0,(width-(d-b))/2)
    lo=[floor((a-dx)/grid)*grid,floor((b-dy)/grid)*grid]
    hi=[ceil((c+dx)/grid)*grid,ceil((d+dy)/grid)*grid]
    if bounds is not None:
        # A boundary PIN's half-access may be narrower than the configured
        # wire. Grow copper inward, keeping the fixed PIN fully covered; do
        # not shrink the route or symmetrically spill outside the work area.
        for axis in (0,1):
            low=ceil(bounds[0][axis]/grid)*grid;high=floor(bounds[1][axis]/grid)*grid
            if lo[axis]<low:hi[axis]+=low-lo[axis];lo[axis]=low
            if hi[axis]>high:lo[axis]-=hi[axis]-high;hi[axis]=high
        pad=box(*lo,*hi)
        if not box(*bounds[0],*bounds[1]).covers(pad) or not pad.covers(geometry):
            raise LiteError('PIN_ACCESS_BLOCKED','区域边界无法容纳配置线宽的接口落点；请调整区域或接口。',width_dbu=width)
    return (tuple(lo),tuple(hi))


def anchors(geometry, grid, toward=None):
    """Snap several access points, always test against actual polygon material."""
    from shapely.ops import nearest_points
    a,b,c,d = geometry.bounds
    points = [geometry.representative_point(), geometry.centroid]
    if toward is not None:points.insert(0, nearest_points(geometry, Point(toward))[0])
    points += [Point(x,y) for x in (a+grid,(a+c)/2,c-grid) for y in (b+grid,(b+d)/2,d-grid)]
    result = []
    for p in points:
        pt = (round(p.x/grid)*grid, round(p.y/grid)*grid)
        if geometry.covers(Point(pt)) and pt not in result:result.append(pt)
    return result
