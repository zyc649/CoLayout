"""Current-level whole-object selection; never selects contents through a box."""
from shapely.geometry import box
from shapely.ops import unary_union
from .editor import projected
from .regions.query import owner_map,object_bounds,children
from .geometry import shape_figure,via_figures
from .materials import polygon_from_figure


def object_entry(workspace, profile, obj):
    bounds = object_bounds(workspace, obj, profile)
    if not bounds:
        return None
    geometry = box(*bounds[0], *bounds[1])
    outline = bool(obj.shape)
    if obj.shape:
        figures = via_figures(obj.shape, profile) if obj.kind == 'stdVia' else [shape_figure(obj.shape)]
        geometry = unary_union([polygon_from_figure(f) for f in figures])
    elif obj.mpp:
        from .mpp_geometry import rows
        from .model import LiteError
        try:
            geometry = unary_union([shape for _, shape in rows(workspace, profile, obj)])
            outline = True
        except LiteError:
            pass  # Older incomplete caches retain the explicit whole-object bounds.
    return {'bbox': bounds, 'geometry': geometry, 'shape_outline': outline}


def entries(editor):
    w=editor.w;owners=owner_map(w);result={}
    for uid,obj in projected(w).items():
        if uid in w.baseline.text_owners or owners.get(uid)!=editor.scope_id:continue
        row = object_entry(w, editor.profile, obj)
        if row:
            result[uid] = row
    for row in (*children(w,editor.scope_id),*(r for r in (*w.local_data.markups.values(),*w.local_data.keepouts.values()) if r.scope_id==editor.scope_id)):
        result[row.id]={'bbox':row.bbox,'geometry':box(*row.bbox[0],*row.bbox[1])}
    return result


def in_box(rows,bounds,mode):
    region=box(*bounds[0],*bounds[1])
    predicate=region.covers if mode=='contains' else region.intersects
    return {uid for uid,row in rows.items() if predicate(row['geometry'])}
