"""Shared rigid subtree transforms and proofs, independent of input modality."""
from ..editor import projected
from ..model import LiteError, Placement
from ..geometry import rigid_matrix, point, box, orientation_after, transform_shape
from ..local_models import LocalData
from .query import members

def transform_local(local,region_id,matrix):
    # Descendant identity and ownership stay intact; only the rigid pose changes.
    ids={region_id}
    while True:
        more={r.id for r in local.regions.values() if r.parent_id in ids}
        if more<=ids:break
        ids.update(more)
    regions=dict(local.regions)
    for ident in ids:
        r=regions[ident]
        regions[ident]=r.model_copy(update={'bbox':box(r.bbox,matrix),'revision':r.revision+1,
            'interface_revision':r.interface_revision+1,'pins':{k:p.model_copy(update={'bbox':box(p.bbox,matrix)}) for k,p in r.pins.items()}})
    return local.model_copy(update={'regions':regions,
        'markups':{k:m.model_copy(update={'bbox':box(m.bbox,matrix)}) if m.scope_id in ids else m for k,m in local.markups.items()},
        'keepouts':{k:m.model_copy(update={'bbox':box(m.bbox,matrix)}) if m.scope_id in ids else m for k,m in local.keepouts.items()}})


def verify_transforms(before,after,profile,scope,transforms):
    """Check rigid subtree proofs before the Editor permits ancestor-level edits."""
    if before.baseline is not after.baseline:raise LiteError('INVALID_REGION_TRANSFORM_BASELINE')
    old=projected(before);new=projected(after);allowed=set();expected=before.local_data
    for ident,spec in transforms.items():
        region=before.local_data.regions.get(ident)
        if region is None or region.parent_id!=scope:raise LiteError('REGION_SCOPE_VIOLATION')
        delta,orientation,pivot=spec;matrix=rigid_matrix(delta,orientation,pivot)
        expected=transform_local(expected,ident,matrix)
        for uid in members(before,ident):
            if uid in before.baseline.text_owners:continue
            allowed.add(uid);a=old[uid];b=new.get(uid)
            if b is None or a.kind!=b.kind:raise LiteError('INVALID_REGION_TRANSFORM')
            if a.kind in ('inst','mpp'):
                want=Placement(origin=point(a.placement.origin,matrix),orientation=orientation_after(a.placement.orientation,orientation))
                if b.placement!=want:raise LiteError('INVALID_REGION_TRANSFORM')
                if a.mpp:
                    from ..mpp import placed
                    if placed(a,want).semantic()!=b.semantic():raise LiteError('INVALID_REGION_TRANSFORM')
            elif a.shape:
                want=transform_shape(a.shape,delta=delta,orientation=orientation,pivot=pivot)
                if want.kind=='stdVia':want=want.model_copy(update={'via_parameters':profile.effective_via(want)})
                if b.shape!=want:raise LiteError('INVALID_REGION_TRANSFORM')
            else:raise LiteError('UNSUPPORTED_REGION_MEMBER',uid)
    if scope in expected.regions:
        # A shared atomic batch may also add/delete direct-scope geometry.
        # Only that scope's membership counters may differ; every moved
        # region, interface and other metadata must still match the proof.
        row=expected.regions[scope];actual=after.local_data.regions[scope]
        expected=expected.model_copy(update={'regions':{**expected.regions,scope:row.model_copy(
            update={'object_uids':actual.object_uids,'revision':actual.revision})}})
    # A parent owns its direct children's frames and interfaces. An atomic
    # transform may therefore be followed by resize/PIN/property edits. Keep
    # membership, parentage and every deeper region strictly tied to the rigid
    # proof; WorkSessions still enforces the current actor's one-level lock.
    editable=('bbox','pins','name','note','blocked_layers','pin_mode','revision','interface_revision')
    regions=dict(expected.regions)
    for ident,row in regions.items():
        actual=after.local_data.regions.get(ident)
        if row.parent_id==scope and actual is not None:
            regions[ident]=row.model_copy(update={key:getattr(actual,key) for key in editable})
    expected=expected.model_copy(update={'regions':regions})
    if LocalData.model_validate(expected.model_dump())!=after.local_data:raise LiteError('INVALID_REGION_TRANSFORM_METADATA')
    return allowed
