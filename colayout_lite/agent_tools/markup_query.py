"""Resolve a current-level guidance box once for inspect and capture."""
from ..model import LiteError

def resolve(w,p,rid,ident,padding_um=0,clip_to_region=False):
    row=w.local_data.markups.get(ident)
    if row is None or row.scope_id!=rid:
        raise LiteError('MARKUP_UNKNOWN_OR_OUTSIDE_REGION','定位框不存在或不属于当前接入层；需使用所属层的接入。')
    scale=p.dbu_per_micron;pad=padding_um*scale
    (x,y),(xx,yy)=row.bbox;(a,b),(c,d)=w.local_data.regions[rid].bbox
    requested=(x-pad,y-pad,xx+pad,yy+pad)
    clipped=(max(a,requested[0]),max(b,requested[1]),min(c,requested[2]),min(d,requested[3]))
    cropped=clipped!=requested
    if cropped and not clip_to_region:
        raise LiteError('MARKUP_VIEW_OUTSIDE_REGION','周边范围超出接入区；可显式设置 clip_to_region=true。',requested_bounds_um=[v/scale for v in requested])
    if clipped[0]>=clipped[2] or clipped[1]>=clipped[3]:raise LiteError('MARKUP_VIEW_EMPTY')
    bounds=clipped if clip_to_region else requested
    return {'markup_id':ident,'region_id':rid,'document_id':w.id,'revision':w.revision,'text':row.text,
        'markup_bounds_um':[x/scale,y/scale,xx/scale,yy/scale],
        'requested_bounds_um':[v/scale for v in requested],'bounds_um':[v/scale for v in bounds],
        'clipped':cropped,'padding_um':padding_um,'coordinates':'workspace_um'}
