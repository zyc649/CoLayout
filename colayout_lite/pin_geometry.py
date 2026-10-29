"""Exact cached Layout pin geometry shared by local workspace services."""
from math import isfinite
from shapely.geometry import box
from .materials import apply_delta,placement_delta,polygon_from_figure
from .geometry_memo import GeometryMemo

_projection_cache=GeometryMemo(entries=6000)


def cached_pin_geometry(snapshot,pin,before,after):
    key=(id(pin),before.origin if before else None,before.orientation if before else None,
         after.origin if after else None,after.orientation if after else None)
    # The source snapshot retains pin records, so identity cannot be reused.
    return _projection_cache.get(snapshot,key,lambda:pin_geometry(pin,before,after))

def _number(value):
    number = float(value)
    if not isfinite(number):
        raise ValueError('Non-finite pin coordinate')
    return int(number) if number.is_integer() else number


def _points(values):
    return [[_number(v) for v in p] for p in values]


def pin_geometry(pin, before, after):
    """Decode exact local pin geometry and project through its occurrence transform."""
    kind = pin.get('kind')
    if kind not in ('rect', 'polygon', 'path', 'pathSeg'):
        raise ValueError('Unsupported pin geometry: ' + str(kind))
    geometry = dict(pin.get('local_geometry') or {})
    for field in ('points', 'boundary'):
        if field in geometry:
            geometry[field] = _points(geometry[field])
    for field in ('width', 'begin_extension', 'end_extension'):
        if field in geometry:
            geometry[field] = _number(geometry[field])
    if kind in ('path', 'pathSeg'):
        geometry.setdefault('begin_extension', 0)
        geometry.setdefault('end_extension', 0)
        geometry.setdefault('style', 'truncateExtend')
    if pin.get('local_bbox') is not None and pin.get('transform') is not None:
        figure = dict(kind=kind, bbox=_points(pin['local_bbox']), geometry=geometry)
        matrix=tuple(_number(v) for v in pin['transform'])
        if kind=='rect' and (matrix[1]==0 and matrix[2]==0 or matrix[0]==0 and matrix[3]==0):
            from .geometry import box as transform_box
            bounds=transform_box(figure['bbox'],matrix);g=box(*bounds[0],*bounds[1])
        else:g = apply_delta(polygon_from_figure(figure),matrix)
    elif kind == 'rect' and pin.get('bbox') is not None:
        # Legacy rectangular pins have an exact axis-aligned occurrence box.
        g = box(*pin['bbox'][0], *pin['bbox'][1])
    else:
        raise ValueError('Exact pin geometry/transform missing; bounding box is insufficient')
    if before and after and before!=after:
        g = apply_delta(g, placement_delta(before, after))
    if g.is_empty or not g.is_valid or g.area <= 0:
        raise ValueError('Empty or invalid pin geometry')
    return g
