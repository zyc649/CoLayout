"""Narrow local-DRC guard for cross-device Poly contacts; not LVS."""
from collections import defaultdict
from math import floor,ceil
from shapely import STRtree
from shapely.geometry import box
from shapely.ops import unary_union
from ..materials import Physical
from .models import Marker
from ..model import digest
from ..physical_connectivity import _touches_conductively


def contacts(rows,leaf,gates,roi,checkpoint):
    by_owner=defaultdict(list)
    for r in rows:
        if r.owner in leaf and r.layer in gates:by_owner[(r.owner,r.layer)].append(r.geometry)
    material=[]
    for (owner,layer),geometries in sorted(by_owner.items()):
        merged=unary_union(geometries)
        material.extend(Physical(owner,layer,g) for g in ([merged] if merged.geom_type=='Polygon' else merged.geoms)
                        if g.geom_type=='Polygon')
    by_layer=defaultdict(list)
    for r in material:by_layer[r.layer].append(r)
    seen=set()
    for layer,items in by_layer.items():
        tree=STRtree([r.geometry for r in items])
        for i,a in enumerate(items):
            checkpoint()
            for j in tree.query(a.geometry,predicate='intersects'):
                if int(j)<=i:continue
                b=items[int(j)]
                if a.owner==b.owner:continue
                witness=a.geometry.intersection(b.geometry).intersection(roi)
                if witness.is_empty:continue
                owners=tuple(sorted((a.owner,b.owner)));key=(layer,owners,witness.wkb)
                if key in seen:continue
                seen.add(key);yield layer,owners,witness


def run(w,p,physical,objects,allowed,scope,roi,*,checkpoint=lambda:None,limit=10000):
    roles={r['layer']:r.get('material') for r in p.layers if r['purpose']=='drawing'}
    gates={l for l,role in roles.items() if role=='poly'}
    leaf={u for u in allowed if objects[u].kind in ('inst','mosaic')}
    coverage={'status':'not_applicable','poly_layers':sorted(gates),'contact_pairs':0,'safe_pairs':0,
              'short_pairs':0,'unresolved_pairs':0,'truncated':False,
              'meaning':'仅检查本层不同普通器件的 Poly 接触；不改变原有连通性、高亮和绘图权限，不是 LVS。'}
    if len(leaf)<2:return [],[],coverage
    if not gates:
        unknown=sorted({r.layer for r in physical if r.owner in leaf and roles.get(r.layer) in (None,'','unknown','other')})
        coverage['status']='unavailable' if unknown else 'no_poly_material'
        warning=[{'kind':'poly_layer_role_unavailable','layers':unknown,'message':'器件存在未分类图层；工艺未声明 Poly 材料角色，无法覆盖跨器件 Poly 接触检查。'}] if unknown else []
        return [],warning,coverage
    candidates=list(contacts(physical,leaf,gates,roi,checkpoint))
    coverage['status']='checked'
    if not candidates:return [],[],coverage
    from .poly_contact_graph import build
    graph=build(w,p,allowed,scope['region_id'],checkpoint)
    markers=[];warnings=[]
    for layer,owners,witness in candidates:
        checkpoint();coverage['contact_pairs']+=1;issues=[];roots=set()
        for owner in owners:
            matched=[d for d in graph['domains'].get(owner,[]) if d[0]==layer and d[1].intersects(witness)]
            if not matched:issues.append({'kind':'poly_access_missing','owner':owner})
            for _,g,safe,terminals,pins in matched:
                if not safe:
                    issues.append({'kind':'intrinsic_or_unresolved_terminal_domain','owner':owner,'terminal_domains':terminals,'pin_ids':pins})
            issues.extend(graph['problems'][owner])
        if witness.area==0 and witness.length==0:issues.append({'kind':'point_only_contact'})
        for i in graph['index'].hits(layer,witness):
            node=graph['nodes'][i]
            if node['owner'] in owners and _touches_conductively(node['geometry'],witness):
                roots.add(graph['uf'].find(i))
        nets=set();pins={}
        for root in roots:
            nets.update(graph['nets'][root]);pins.update(graph['pins'][root]);issues.extend(graph['unknown'][root])
        if not roots or not nets:issues.append({'kind':'no_resolved_pin_network'})
        # A multi-terminal device body is deliberately opaque to this patch.
        # Do not turn its internal resistor/capacitor semantics into a short.
        opaque=any(x['kind']=='intrinsic_or_unresolved_terminal_domain' for x in issues)
        if len(nets)>1 and not opaque:
            code='SHORT';severity='error';message='跨器件 Poly 接触导致 PIN 网络冲突：'+' / '.join(sorted(nets))
            coverage['short_pairs']+=1
        elif issues:
            code='UNRESOLVED';severity='warning';message='跨器件 Poly 接触无法确认安全：端子归属或接触证据不完整。'
            coverage['unresolved_pairs']+=1
            warnings.append({'kind':'poly_contact_unresolved','owners':list(owners),'layer':layer})
        else:
            coverage['safe_pairs']+=1;continue
        if len(markers)>=limit:
            coverage['truncated']=True;break
        bounds=witness.bounds
        if bounds[0]==bounds[2] or bounds[1]==bounds[3]:bounds=witness.buffer(.5).bounds
        bbox=((floor(bounds[0]),floor(bounds[1])),(ceil(bounds[2]),ceil(bounds[3])))
        ident=digest([code,layer,owners,witness.wkb_hex])[:24]
        markers.append(Marker(id=ident,rule_id='LOCAL.POLY_CONTACT_'+code,severity=severity,message=message,
            bbox=bbox,layers=(layer,),objects=tuple({'uid':u,'name':objects[u].attributes.get('name',u),'kind':objects[u].kind,'inside_instance':True} for u in owners),
            association='local_geometry',details={'category':'poly_contact','nets':sorted(nets),'pins':list(pins.values()),
                'issues':issues,'witness_bounds_um':[v/p.dbu_per_micron for v in witness.bounds],
                'method':'cross_device_poly_with_verified_contacts_and_native_terminal_boundaries'}))
    return markers,warnings,coverage
