"""Guard net names projected as exact metal interfaces, never extra copper.

Native net assignment is authoritative after import; pending generation uses
its declared net. PINs are derived from their owner and follow its pose/lifetime.
No name-based physical union and no fictitious rectangular ring interior.
"""
from shapely.ops import unary_union
from .model import LiteError


def required_net(value):
    if not isinstance(value,str) or not value.strip() or any(c in value for c in '\r\n\x00'):
        raise LiteError('GUARD_NET_REQUIRED','请输入保护环的网络名，例如 VSS 或 VDD。')
    return value.strip()


def names(obj,profile=None):
    if not obj.mpp:return set()
    metals={r['layer'] for r in profile.layers if r.get('material')=='metal'} if profile else None
    values={obj.observed_net} if obj.observed_net else set()
    values.update(part.get('net_name') for part in obj.mpp.parts if isinstance(part,dict) and part.get('net_name')
        and (metals is None or (part.get('lpp') or [None])[0] in metals))
    return values


def pins(workspace,profile,objects,uids):
    from .mpp_geometry import rows
    metals={r['layer'] for r in profile.layers if r.get('material')=='metal'}
    pending={op.uid:op.guard.get('net_intent') for op in workspace.operations if op.action=='guard'}
    records=[];warnings=[]
    for uid in sorted(uids):
        obj=objects.get(uid)
        if obj is None or not obj.mpp:continue
        nets={pending[uid]} if pending.get(uid) else names(obj,profile)
        if not nets:continue
        if len(nets)!=1:
            warnings.append({'kind':'guard_pin_ambiguous','owner':uid,'nets':sorted(nets)});continue
        name=next(iter(nets))
        try:
            by_layer={}
            for layer,g in rows(workspace,profile,obj,layers=metals):by_layer.setdefault(layer,[]).append(g)
            figures=[(layer,unary_union(shapes)) for layer,shapes in sorted(by_layer.items())]
        except (LiteError,ValueError,KeyError,TypeError) as exc:
            warnings.append({'kind':'guard_pin_geometry_missing','owner':uid,'net':name,'message':str(exc)});continue
        if not figures:
            warnings.append({'kind':'guard_pin_geometry_missing','owner':uid,'net':name});continue
        records.append({'id':uid+':guard-pin','owner':uid,'name':name,'label':name,'net':name,
            'local':False,'guard':True,'existing_material':True,'owner_bbox':obj.bbox,'figures':figures})
    return records,warnings
