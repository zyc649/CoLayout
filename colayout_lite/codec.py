"""Decode native snapshots, shared-master display graph and portable technology."""
from __future__ import annotations
from copy import deepcopy
from pydantic import ValidationError
from .model import Snapshot, Object, Shape, Placement, LiteError, digest, VIA_PAIRS, VIA_LENGTHS, VIA_COUNTS
from .technology import TechnologyProfile
from .geometry import transform, point, box


def prop(props,name):
    return next((p[2][1] for p in props or [] if p[0]==name and p[2] and p[2][0]=='string'),None)


def params(rows):
    out={}
    for key,value in rows or []:
        if key in VIA_COUNTS|VIA_LENGTHS:out[key]=int(value)
        elif key in VIA_PAIRS:out[key]=[int(v) if v is not None else None for v in value]
    return out


def decode_technology(raw):
    tech,dbu,grid,layers,via_rows,templates=raw
    layers=sorted([dict(layer=p[0],purpose=p[1],material=p[2]) for p in layers],key=lambda p:(p['layer'],p['purpose']))
    vias={}
    for name,kind,l1,l2,i1,i2,rows in via_rows or []:
        defaults=params(rows);r=dict(rows or [])
        vias[name]=dict(kind=kind,layer1=l1,layer2=l2,implant1=i1,implant2=i2,
                        cut_layer=r.get('cutLayer'),defaults=defaults,cut_pattern=r.get('cutPattern'))
    templates=[dict(library=t[0],name=t[1],definition=t[2]) for t in templates or []]
    # Optional factory discovery must not change process identity when a cell
    # contains modules instead of direct PDK instances (or contains no devices).
    canonical=dict(dbu=int(dbu),grid=int(grid),layers=layers,vias=vias)
    fp=digest(canonical)
    return TechnologyProfile(id='discovered-'+fp[:12],label=tech,native_fingerprint=fp,native_technology_name=tech,
        dbu_per_micron=int(dbu),grid=int(grid),writable_lpps=tuple((p['layer'],p['purpose']) for p in layers if p['material']=='metal' and p['purpose']=='drawing'),
        layers=layers,vias=vias,guard_templates=templates,validation={'status':'discovered','note':'Review writable layers; native generation is not DRC sign-off'})


def native_shape(row,meta,profile):
    ident,kind,bounds,lpp,net,props,geometry=row;g=dict(geometry or [])
    common=dict(kind=kind,net_intent=prop(props,'colayoutNetIntent') or None)
    if kind=='rect':common.update(lpp=lpp,bbox=[[int(v) for v in p] for p in bounds])
    elif kind=='polygon':common.update(lpp=lpp,points=[[int(v) for v in p] for p in g['points']])
    elif kind=='path':
        common.update(lpp=lpp,points=[[int(v) for v in p] for p in g['points']],width=int(g['width']),style=g['style'])
        if g['style']=='varExtendExtend':common.update(begin_extension=int(g['begin_extension']),end_extension=int(g['end_extension']))
    elif kind=='pathSeg':
        pts=[[int(v) for v in g[k]] for k in ('begin','end')]
        common.update(lpp=lpp,points=pts,width=int(g['width']),begin_style=meta[5][0],end_style=meta[5][1],
                      begin_extension=int(g['begin_extension']),end_extension=int(g['end_extension']),
                      width_basis='oa_diagonal' if all(a!=b for a,b in zip(*pts)) else 'perpendicular')
        from .pathseg import CUSTOM_FIELDS
        for side in ('begin','end'):
            if common[side+'_style']=='custom':
                values=g[side+'_custom']
                if len(values)!=3:raise ValueError('Missing native custom end parameters')
                common[side+'_custom']=dict(zip(CUSTOM_FIELDS,map(int,values)))
    elif kind=='stdVia':
        vd=profile.vias[g['definition']]
        if {p[0] for p in meta[6] or []}-(VIA_COUNTS|VIA_LENGTHS|VIA_PAIRS):
            raise ValueError('Unmodelled native via overrides: read-only to preserve them')
        overrides=params(meta[6]);effective=deepcopy(vd['defaults'])
        for name,value in overrides.items():
            if isinstance(value,list):value=[v if v is not None else effective[name][i] for i,v in enumerate(value)]
            effective[name]=value
        if vd.get('cut_pattern'):raise ValueError('Patterned via editing is not verified')
        common.update(origin=[int(v) for v in g['origin']],orientation=g['orientation'],via_definition=g['definition'],via_parameters=effective)
    else:return None
    shape=Shape.model_validate(common)
    if kind=='pathSeg' and any(s in ('custom','chamfer') for s in (shape.begin_style,shape.end_style)):
        from .pathseg import outline,canonical_boundary
        # Same cyclic polygon, independent of OA's first vertex/winding.
        if canonical_boundary(outline(shape))!=canonical_boundary([tuple(map(int,p)) for p in g['boundary']]):
            raise ValueError('Native cap boundary differs from supported custom geometry')
    return shape


def check_native_masters(graph):
    failures=[]
    for node in graph[1]:
        for row in node[6] or []:
            if row[1]=='label' and row[3]==['marker','error'] and dict(row[6] or []).get('text')=='pcellEvalFailed':
                failures.append({'master':node[1:4],'error':prop(row[5],'errorDesc')})
    if failures:
        raise LiteError('PCELL_EVALUATION_FAILED','Virtuoso 器件生成失败，不能把错误标记当作正常器件导入。请先修复对应工艺环境。',failures=failures)


def decode(raw):
    if raw[0] not in ('colayout-lite-native-1','colayout-lite-native-2','colayout-lite-native-3','colayout-lite-native-4','colayout-lite-native-5','colayout-lite-native-6'):raise ValueError('Unsupported native protocol')
    snap,meta,deps,tech,graph=raw[1:6];check_native_masters(graph);profile=decode_technology(tech)
    session,handle,root,libpath,lib,cell,counter,dirty,ts,dbu,grid,rows,terms,nets,opaque=snap
    metas={p[0]:p for p in meta};objects={};id_to_uid={}
    for row in rows or []:
        ident,kind,bounds,lpp,net,props,geometry=row;m=metas[ident];g=dict(geometry or [])
        uid=m[1] or 'session:'+ident;id_to_uid[ident]=uid
        reason='missing_persistent_identity' if not m[1] else None
        shape=None;placement=None
        try:shape=native_shape(row,m,profile)
        except (ValueError,ValidationError,KeyError,TypeError) as exc:reason='unsupported_geometry: '+str(exc)
        if kind=='inst':
            placement=Placement(origin=[int(v) for v in g['xy']],orientation=g['orientation'])
            if not m[4]:reason='master_unresolved'
            if g.get('magnification')!='1':reason='unsupported_magnification'
            if any(p[0] in ('leftAbut','rightAbut') and p[2] and p[2][0]=='number' and float(p[2][1])!=0 for p in g.get('parameters') or []):reason='shared_diffusion'
        elif shape is None:reason=reason or 'unsupported_object'
        if m[2]:reason='protected_group'
        if m[3]:reason='pin_geometry'
        if len(m)>7 and m[7]:reason=m[7]
        attrs=g if kind=='inst' or shape is None else {}
        if len(m)>11 and m[11]:
            relationships=dict(m[11]);relationships['children']=sorted(relationships.get('children') or [])
            attrs={**attrs,'native_relationships':relationships}
        route_uid=m[9] if len(m)>9 and isinstance(m[9],str) else None
        if len(m)>9 and m[9] and not route_uid:attrs={**attrs,'native_route':dict(m[9])}
        if kind in ('inst','mosaic'):attrs={**attrs,'master_key':m[4]}
        if kind=='inst':attrs.pop('xy',None);attrs.pop('orientation',None)
        objects[uid]=Object(uid=uid,native_id=ident,native_row=row,kind=kind,bbox=bounds,shape=shape,placement=placement,
            attributes=attrs,properties=props or [],observed_net=net,group_uid=m[2],route_uid=route_uid,read_only_reason=reason,
            deletion_allowed=bool(m[10]) if len(m)>10 else False)
    node_map={n[0]:n for n in graph[1]}
    def normalized_row(row):
        d=deepcopy(row[1:]);geo=dict(d[-1] or []);geo.pop('master_counter',None)
        d[-1]=sorted(geo.items());d[4]=sorted(d[4] or [],key=lambda p:p[0]);return d
    cache={}
    def node_hash(key,stack=()):
        if key in stack:raise ValueError('Cyclic hierarchy')
        if key in cache:return cache[key]
        n=node_map[key]
        child_hashes={c[0]:node_hash(c[1],stack+(key,)) for c in n[10] or []}
        content=[(normalized_row(r),child_hashes.get(r[0])) for r in n[6] or []]
        content.sort(key=lambda v:digest(v))
        terminal_data=[[t[0],t[1],t[2],[[normalized_row(f) for f in p] for p in t[3] or []]] for t in n[8] or []]
        cache[key]=digest([n[1:5],content,terminal_data]);return cache[key]
    compact=raw[0] in ('colayout-lite-native-2','colayout-lite-native-3','colayout-lite-native-4','colayout-lite-native-5')
    instance_dependencies={} if compact else {uid:node_hash(o.attributes['master_key']) for uid,o in objects.items() if o.kind in ('inst','mosaic') and o.attributes['master_key'] in node_map}
    pins=[]
    for child in node_map[graph[0]][10] or []:
        if child[2] not in ('inst','mosaic'):continue
        uid=id_to_uid[child[0]];n=node_map[child[1]]
        tr=transform(tuple(map(int,child[3])),child[4],int(dbu)/int(n[4])*float(child[5]))
        for name,direction,localnet,groups in n[8] or []:
            for pi,figs in enumerate(groups or []):
                for fi,figure in enumerate(figs or []):
                    geom=dict(figure[6] or [])
                    pins.append(dict(instance_uid=uid,terminal=name,pin_index=pi,figure_index=fi,lpp=figure[3],kind=figure[1],
                        bbox=box([[float(v) for v in p] for p in figure[2]],tr),
                        local_geometry=geom,local_bbox=figure[2],transform=tr,master_ref=n[1:4],
                        array_index=list(map(int,child[6])) if len(child)>6 else None))
    terminals=[[t[0],t[1],t[2],[[p[1],p[2],[id_to_uid.get(f,'unresolved') for f in p[3] or []]] for p in t[3] or []]] for t in terms or []]
    if len(raw)>8:
        from .mpp import collapse
        objects=collapse(objects,raw[8])
    snapshot=Snapshot(library=lib,cell=cell,library_path=libpath,session=session,counter=counter,dirty=bool(dirty),
        dbu_per_micron=int(dbu),grid=int(grid),objects=objects,dependencies=deps,dependency_digest=digest(sorted(graph[4] or [])) if compact else digest(instance_dependencies),
        dependency_scheme='native_versions' if compact else 'geometry',protected_dependencies=(graph[4] or []) if compact else None,
        pins=pins,terminals=terminals,opaque_counts=dict(zip(['mosaics','figGroups','routes','blockages','groups'],map(int,opaque))),
        display={'root':graph[0],'nodes':node_map,'styles':graph[2],'unsupported':graph[3] or []},technology_fingerprint=profile.native_fingerprint,
        text_owners={id_to_uid[m[0]]:m[8] for m in meta if len(m)>8 and m[8] and id_to_uid[m[0]] in objects and m[8] in objects})
    from .routing import decode_routes,validate_membership
    if len(raw)>6:snapshot=snapshot.model_copy(update={'routes':decode_routes(raw[6])})
    if len(raw)>7:
        from .groups import decode_groups
        snapshot=snapshot.model_copy(update={'fig_groups':decode_groups(raw[7])})
    validate_membership(snapshot)
    return snapshot,profile


def shape_payload(s):
    d={'kind':s.kind,'net_intent':s.net_intent}
    if s.kind=='stdVia':
        d.update(origin=list(map(str,s.origin)),orientation=s.orientation,via_definition=s.via_definition,
                 via_parameters={k:(v if k in VIA_COUNTS else [str(n) for n in v] if isinstance(v,(list,tuple)) else str(v)) for k,v in s.via_parameters.items()})
    else:
        d['lpp']=s.lpp
        if s.bbox:d['bbox']=[[str(v) for v in p] for p in s.bbox]
        if s.points:d['points']=[[str(v) for v in p] for p in s.points]
        if s.width is not None:d['width']=str(s.width)
        if s.kind=='path':
            d['style']=s.style
            if s.style=='varExtendExtend':d.update(begin_extension=str(s.begin_extension),end_extension=str(s.end_extension))
        if s.kind=='pathSeg':
            d.update(begin_style=s.begin_style,end_style=s.end_style,begin_extension=str(s.begin_extension),end_extension=str(s.end_extension))
            for side in ('begin','end'):
                cap=getattr(s,side+'_custom')
                if cap:d[side+'_custom']=[str(v) for v in cap.model_dump().values()]
    return d
