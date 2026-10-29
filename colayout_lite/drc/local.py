"""Fast geometric screening with explicit coverage, not a sign-off rule engine."""
from collections import defaultdict
from time import perf_counter
from math import floor,ceil
from uuid import uuid4
from shapely.geometry import Polygon,box
from shapely.ops import unary_union,nearest_points
from shapely.strtree import STRtree
from ..model import digest
from .models import Marker,Result,stamp,validate_context
from ..materials import extract,associate,AssociationIndex


def bounds(g):
    x,y,xx,yy=g.bounds;return ((floor(x),floor(y)),(ceil(xx),ceil(yy)))


def coordinates(g):
    if g.geom_type=='Polygon':return tuple((float(x),float(y)) for x,y in g.exterior.coords[:-1])
    return ()


def run(w,technology,profile,region,*,job_id=None,checkpoint=lambda:None,scope_id=...):
    started=perf_counter();validate_context(w,technology,profile);scale=technology.dbu_per_micron
    rules=[r for r in profile.rules if r.enabled]
    halo=max([profile.local_halo_um]+[r.value for r in rules if r.kind!='area'])*scale
    from .scope import selection
    allowed,scope=selection(w,region,scope_id)
    from ..scope_state import fingerprint
    scope['fingerprint']=fingerprint(w,scope['region_id'])
    physical,objects,warnings,roi,context=extract(w,technology,region,halo,checkpoint,owner_filter=allowed)
    from .scope import pin_context
    interfaces=pin_context(w,scope['native_instance_ids'],context,checkpoint)
    scope['interface_context_primitives']=len(interfaces)
    direct_layers=defaultdict(list)
    for row in physical:direct_layers[row.layer].append(row.geometry)
    # Patch checks consume the original Physical rows. Only the enabled
    # primitive rules need these expensive, workspace-wide layer unions.
    needed={name for rule in rules for name in (rule.layer,rule.other_layer) if name}
    direct_unions={layer:unary_union(gs) for layer,gs in direct_layers.items() if layer in needed}
    physical+=interfaces
    index=AssociationIndex(physical)
    layers=defaultdict(list)
    for row in physical:layers[row.layer].append(row)
    context_layers={row.layer for row in interfaces}
    # Preserve the original union input/order for layers with PIN context;
    # every other layer already has exactly the required union.
    unions={name:(unary_union([r.geometry for r in rows]) if name in context_layers else direct_unions[name])
            for name,rows in layers.items() if name in needed}
    markers=[];seen=set();truncated=False
    def emit(rule,g,measured=None,details=None):
        nonlocal truncated
        clipped=g.intersection(roi)
        if clipped.is_empty:return
        components=list(clipped.geoms) if hasattr(clipped,'geoms') else [clipped]
        for part in components:
            if part.is_empty:continue
            key=digest([rule.id,bounds(part),coordinates(part)])
            if key in seen:continue
            seen.add(key)
            if len(markers)>=profile.max_markers:truncated=True;return
            nearby=part.buffer(max(rule.value*scale if rule.kind!='area' else 1,1))
            refs=associate(index,objects,nearby)
            markers.append(Marker(id=key[:24],rule_id=rule.id,message=rule.note or rule.kind,severity=rule.severity,
                kind='polygon' if coordinates(part) else 'box',points=coordinates(part),bbox=bounds(part),
                layers=tuple(x for x in [rule.layer,rule.other_layer] if x),objects=refs,association='local_geometry',
                measured_um=measured,required_um=rule.value if rule.kind!='area' else None,
                details={'source':rule.source,**(details or {})}))
    for rule in rules:
        checkpoint()
        material=unions.get(rule.layer,Polygon());limit=rule.value*scale
        if rule.kind=='width':
            for row in layers.get(rule.layer,[]):
                checkpoint()
                if row.owner not in allowed:continue
                if row.width is None:
                    # Unsupported width geometry is outside this lightweight check.
                    # Keep the material in unions for every other supported rule.
                    continue
                if row.width+1e-6>=limit:continue
                band=row.skeleton.buffer(limit/2,cap_style='flat',join_style='mitre')
                missing=band.difference(material)
                if not missing.is_empty:
                    zone=missing.buffer(limit/2,join_style='mitre').intersection(row.geometry)
                    emit(rule,zone,row.width/scale,{'owner':row.owner,'method':'primitive_width_with_union_coverage'})
        elif rule.kind=='spacing':
            from .notches import orthogonal_notches
            for zone,gap in orthogonal_notches(material,limit,direct_unions.get(rule.layer,Polygon()),roi,checkpoint):
                emit(rule,zone,gap/scale,{'method':'orthogonal_notch','same_material_component':True})
            parts=list(material.geoms) if hasattr(material,'geoms') else ([] if material.is_empty else [material])
            tree=STRtree(parts)
            for i,a in enumerate(parts):
                checkpoint()
                for j in tree.query(a.buffer(limit)):
                    if j<=i:continue
                    b=parts[j];distance=a.distance(b)
                    direct=direct_unions.get(rule.layer,Polygon())
                    if not a.intersects(direct) and not b.intersects(direct):continue
                    if distance<=1e-6 or distance+1e-6>=limit:continue
                    zone=a.buffer(limit/2).intersection(b.buffer(limit/2)).intersection(roi)
                    if zone.is_empty:continue
                    centre=zone.representative_point();pa=nearest_points(a,centre)[0];pb=nearest_points(b,centre)[0]
                    emit(rule,zone,pa.distance(pb)/scale,{'witness_dbu':[[pa.x,pa.y],[pb.x,pb.y]],'method':'disjoint_material_components'})
        elif rule.kind=='area':
            parts=list(material.geoms) if hasattr(material,'geoms') else [material]
            for part in parts:
                if not part.is_empty and part.intersects(direct_unions.get(rule.layer,Polygon())) and part.area+1e-6<rule.value*scale*scale:
                    emit(rule,part,details={'area_um2':part.area/(scale*scale),'required_um2':rule.value})
        elif rule.kind=='enclosure':
            enclosing=unions.get(rule.other_layer,Polygon())
            for row in layers.get(rule.layer,[]):
                if row.owner not in allowed:continue
                if not row.geometry.intersects(roi):continue
                missing=row.geometry.buffer(limit,join_style='mitre').difference(enclosing)
                if missing.area>1e-6:
                    distance=row.geometry.distance(enclosing.boundary)/scale if enclosing.covers(row.geometry) else 0
                    emit(rule,row.geometry,distance,{'missing_enclosure_area_um2':missing.area/(scale*scale)})
    if not rules:warnings.append({'kind':'no_enabled_rules','message':'没有启用本地规则，不能据此判为通过。'})
    from .design_warnings import run as design_warnings
    advice=design_warnings(w,technology,profile.design_warnings,region,checkpoint=checkpoint,owner_filter=allowed)
    remaining=max(0,profile.max_markers-len(markers))
    if len(advice)>remaining:truncated=True
    markers.extend(advice[:remaining])
    from .poly_contacts import run as poly_contacts
    poly,poly_warnings,poly_coverage=poly_contacts(w,technology,physical,objects,allowed,scope,roi,
        checkpoint=checkpoint,limit=max(0,profile.max_markers-len(markers)))
    markers.extend(poly);warnings.extend(poly_warnings);truncated=truncated or poly_coverage['truncated']
    from .mim_vias import run as mim_vias
    mim,mim_coverage=mim_vias(w,technology,profile.mim_capacitor,physical,objects,allowed,roi,
        checkpoint=checkpoint,limit=max(0,profile.max_markers-len(markers)))
    markers.extend(mim);truncated=truncated or mim_coverage['truncated']
    from .internal_metal_contacts import run as internal_metal_contacts
    contacts,contact_coverage=internal_metal_contacts(w,technology,physical,objects,allowed,roi,context,
        checkpoint=checkpoint,limit=max(0,profile.max_markers-len(markers)))
    # Advice cannot consume error-check capacity or make a completed error
    # check fail solely because additional warning markers were omitted.
    markers.extend(contacts)
    return Result(job_id=job_id or uuid4().hex,engine='local',**stamp(w),profile_digest=profile.fingerprint(),
        technology_fingerprint=technology.native_fingerprint,configuration_id=technology.configuration_id,dbu_per_micron=scale,region=region,context_bbox=bounds(context),markers=tuple(markers),
        coverage={'scope':scope,'rule_ids':[r.id for r in rules],'warnings':warnings,'truncated':truncated,
                  'complete_for_configured_subset':bool(rules) and not warnings and not truncated,
                  'poly_contact_check':poly_coverage,
                  'mim_via_check':mim_coverage,
                  'internal_metal_contacts':contact_coverage,
                  'design_warnings':{'count':len(advice),'scope':'editable paths and standard metal-via arrays at this level',
                                     'limitations':['不合并分散单孔；不分析器件内部过孔、特殊过孔或载流/压降。']},
                  'limitations':['简化几何筛查，不是 DRC/LVS 签核','仅补查跨器件 Poly 接触引起的 PIN 冲突；不覆盖完整电气提取、全局密度、天线或所有工艺条件例外','同层接触/重叠先合并；已检查轴对齐的平行边窄槽，斜边和复杂凹槽规则仍需服务器验证']},
        metrics={'seconds':perf_counter()-started,'physical_primitives':len(physical),'owners':len({r.owner for r in physical}),'markers':len(markers)})
