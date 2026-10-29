"""Read actual MPP member material for local policy checks, without bridge I/O."""
from .model import Object,LiteError
from .scene import figures_by_owner
from .materials import polygon_from_figure,placement_delta,apply_delta
from .geometry_memo import GeometryMemo

_rows_cache=GeometryMemo(entries=48)


def rows(workspace,profile,obj,*,layers=None):
    preview=workspace.guard_previews.get(obj.uid)
    # Pending guards share the document bucket. A per-guard source exhausts
    # the small source LRU after three guards and reparses every ring forever.
    # Each entry retains its preview too, so an identity key cannot be reused.
    source=workspace.baseline;version=id(preview) if preview else None
    selected=None if layers is None else tuple(sorted(layers))
    _,(original,base)=_rows_cache.get(source,(obj.uid,version,'base',selected),
        lambda:(preview,_base_rows(workspace,obj.uid,preview,selected)))
    key=(obj.uid,version,obj.placement.origin,obj.placement.orientation,selected)
    def place():
        if original.placement==obj.placement:return base
        delta=placement_delta(original.placement,obj.placement)
        return tuple((layer,apply_delta(g,delta)) for layer,g in base)
    _,result=_rows_cache.get(source,key,lambda:(preview,place()))
    chosen=[(layer,g) for layer,g in result if layers is None or layer in layers]
    if not chosen:raise LiteError('MPP_GEOMETRY_MISSING',obj.uid)
    return chosen


def _base_rows(workspace,uid,preview,layers=None):
    original=Object.model_validate(preview['objects'][uid]) if preview else workspace.baseline.objects.get(uid)
    if original is None:raise LiteError('MPP_GEOMETRY_MISSING',uid)
    figures,_=figures_by_owner(workspace.baseline,display=preview['display'] if preview else None,
        objects={uid:original},owner_filter={uid},modes={uid:'full'},include_styles=False)
    result=[]
    for f in figures.get(uid,[]):
        if f['kind'] not in ('rect','polygon','path','pathSeg'):continue
        if f.get('interface') or f.get('geometry',{}).get('opaque_type'):raise LiteError('MPP_GEOMETRY_MISSING',uid)
        layer=(f.get('lpp') or [f['style'].split('/')[0]])[0]
        if layers is None or layer in layers:result.append((layer,polygon_from_figure(f)))
    if not result:raise LiteError('MPP_GEOMETRY_MISSING',uid)
    return original,tuple(result)
