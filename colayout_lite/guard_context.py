"""Companion geometry for component qualification, never for layout generation."""
from math import ceil
from .model import Shape


def validation_context(recipe,technology,drc,bbox,*,closed):
    """Supply a continuous well for an evidenced N+ / N-well tap recipe.

    This is a test fixture for the intended use of a guard, not a waiver and
    not an automatic edit to a user's layout. Other/ambiguous device contexts
    are deliberately not inferred from template names or rule IDs.
    """
    roles={r['layer']:r.get('material') for r in technology.layers if r['purpose']=='drawing'}
    parts=recipe.parts if closed else recipe.open_parts
    materials={roles.get(p.lpp[0]) for p in parts}
    wells=[p for p in parts if roles.get(p.lpp[0])=='nwell']
    if (not wells or 'nplus' not in materials or materials & {'pplus','pwell'}
            or any(p.kind!='enclosurePath' for p in wells)):
        return {'kind':'standalone'},()
    lpps=sorted({p.lpp for p in wells})
    if len(lpps)!=1:
        return {'kind':'standalone'},()
    widths=[r.value*technology.dbu_per_micron for r in drc.rules
            if r.enabled and r.kind=='width' and (r.layer,'drawing') in lpps]
    depth=max(recipe.min_side_dbu,4*recipe.width,
              *(2*(recipe.width-2*p.enclosure) for p in wells),
              *(2*w for w in widths))
    depth=ceil(depth/technology.grid)*technology.grid
    (x,y),(xx,yy)=bbox
    if not closed:
        # Cover the well strip AND its end caps. Stopping at the master
        # centerline's ends would create artificial narrow well stubs.
        half=ceil(max((recipe.width-2*p.enclosure)/2 for p in wells)/technology.grid)*technology.grid
        cap=ceil(max(0,*(p.beginOffset for p in wells),*(p.endOffset for p in wells))/technology.grid)*technology.grid
        if x==xx:
            x-=half;xx+=depth;y-=cap;yy+=cap
        elif y==yy:
            y-=half;yy+=depth;x-=cap;xx+=cap
        else:
            padding=max(half,cap);x-=padding;y-=padding;xx+=padding;yy+=padding
    context={'kind':'nwell_region','layers':[list(lpp) for lpp in lpps],
             'ring':'filled_interior','path':'continuous_well_with_end_caps',
             'fixture_open_depth_um':depth/technology.dbu_per_micron}
    return context,tuple(Shape(kind='rect',lpp=lpp,bbox=((x,y),(xx,yy)),net_intent='MPP_TEST') for lpp in lpps)
