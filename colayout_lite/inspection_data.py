"""Read-only local PIN and physical-component projections for the human viewer."""
from collections import defaultdict
from shapely.geometry import box,Point
from .editor import projected
from .pin_geometry import cached_pin_geometry
from .geometry import shape_figure,via_figures
from .materials import polygon_from_figure,extract,Physical
from .drc.models import Region
from .model import MAX_DBU
from .regions.query import object_bounds


def terminal_net(w,uid,name):
    inst=w.layout_connectivity.instances.get(uid) if w.layout_connectivity else None
    if inst:
        for term in inst.terminals.values():
            if name in term.members:return term.members[name]
            if name==term.name:return term.net
    return None


def pins_for_view(w,p,uids,region_ids,*,include_top=True):
    """Preserve all exact pin figures; one label per terminal, not per finger polygon."""
    objects=projected(w);records={};warnings=[]
    for row in w.baseline.pins:
        uid=row.get('instance_uid');name=row.get('terminal')
        if uid not in uids or uid not in objects:continue
        key=uid+':'+name
        try:g=cached_pin_geometry(w.baseline,row,w.baseline.objects[uid].placement,objects[uid].placement)
        except (KeyError,ValueError,TypeError) as exc:
            warnings.append({'kind':'pin_geometry_missing','owner':uid,'terminal':name,'error':str(exc)});continue
        inst=objects[uid].attributes.get('name',uid[:8])
        record=records.setdefault(key,{'id':key,'owner':uid,'name':name,'label':inst+'.'+name,
            'net':terminal_net(w,uid,name),'local':False,'owner_bbox':object_bounds(w,objects[uid],p),'figures':[]})
        record['figures'].append((row['lpp'][0],g))
    if w.layout_connectivity:
        for uid in uids:
            inst=w.layout_connectivity.instances.get(uid)
            if not inst:continue
            for name in inst.terminals:
                if not any(r['owner']==uid and (r['name']==name or r['name'] in inst.terminals[name].members) for r in records.values()):
                    warnings.append({'kind':'pin_geometry_missing','owner':uid,'terminal':name})
    from .guard_ports import pins as guard_pins
    guards,guard_warnings=guard_pins(w,p,objects,uids)
    records.update({pin['id']:pin for pin in guards});warnings+=guard_warnings
    if include_top:
        for row in w.baseline.terminals:
            figures=[]
            for pin in row[3] or []:
                for uid in pin[2] or []:
                    obj=objects.get(uid)
                    if obj and obj.shape:
                        fs=via_figures(obj.shape,p) if obj.kind=='stdVia' else [shape_figure(obj.shape)]
                        figures.extend((f['lpp'][0],polygon_from_figure(f)) for f in fs)
            if figures:records['top:'+row[0]]={'id':'top:'+row[0],'owner':None,'name':row[0],
                'label':'顶层.'+row[0],'net':row[2],'local':False,'figures':figures}
    for ident in region_ids:
        from .interface_layers import layers as interface_layers
        r=w.local_data.regions[ident]
        for pin in r.pins.values():
            records[pin.id]={'id':pin.id,'owner':ident,'name':pin.name,'label':pin.name,
                'net':pin.net,'local':True,'owner_bbox':r.bbox,'boundary_bbox':r.bbox,'layer_mode':pin.layer_mode,
                'figures':[(layer,box(*pin.bbox[0],*pin.bbox[1])) for layer in interface_layers(pin,p)]}
    if include_top:
        for pin in w.local_data.pins.values():
            records[pin.id]={'id':pin.id,'owner':None,'name':pin.name,'label':'本地.'+pin.name,
                'net':pin.net,'local':True,'figures':[(pin.lpp[0],box(*pin.bbox[0],*pin.bbox[1]))]}
    from .circuit.net_names import signal_names
    signals=signal_names(w.layout_connectivity)
    from collections import Counter
    names=Counter(pin['label'] for pin in records.values())
    owner_names={r.id:r.name for r in w.local_data.regions.values()}
    owner_names.update({uid:o.attributes.get('name',uid[:8]) for uid,o in objects.items()})
    duplicates=Counter(owner_names[uid] for uid in {p['owner'] for p in records.values()} if uid in owner_names)
    for pin in records.values():
        pin['signal']=signals.get(pin['net'])
        owner=pin['owner'];pin['owner_name']=owner_names.get(owner,'顶层')
        instance=w.layout_connectivity.instances.get(owner) if w.layout_connectivity else None
        pin['public_interface']=bool(owner in w.local_data.regions or instance and instance.black_box)
        label=pin['label']
        if names[label]>1:
            owner_label=pin['owner_name']+((' ['+owner[-8:]+']') if owner and duplicates[pin['owner_name']]>1 else '')
            label=owner_label+' / '+pin['name']
        pin['display_name']=label
    return list(records.values()),warnings


def pin_view_signature(w,p,scope,peek=False):
    """Display-only dependency key; never reused as physical/check evidence.

    A hidden child's internal edit does not alter the public PINs of its frame.
    Keep the source workspace alive with each cache entry to prevent ID reuse.
    """
    from .view_scope import view_scope
    view=view_scope(w,scope,peek);objects=projected(w)
    # Conductors do not define native PIN presentation. Projected objects may
    # be recreated after an unrelated edit, so identity alone is not a PIN
    # dependency. Physical graphs still invalidate on every workspace change.
    from .guard_ports import names as guard_names
    native_owners={row.get('instance_uid') for row in w.baseline.pins}
    if w.layout_connectivity:native_owners.update(w.layout_connectivity.instances)
    visible=[];guard_ids=set()
    for uid,obj in objects.items():
        if not view.visible(uid,w.baseline.text_owners):continue
        if obj.mpp:
            guard_ids.add(uid)
            visible.append((uid,obj.placement,obj.bbox,obj.observed_net,obj.attributes.get('name',uid[:8]),
                            tuple(sorted(guard_names(obj,p)))))
        elif uid in native_owners:
            visible.append((uid,obj.placement,obj.bbox,obj.shape,obj.attributes.get('name',uid[:8])))
    top_figures=tuple((uid,objects.get(uid).shape if uid in objects else None)
        for term in w.baseline.terminals for pin in term[3] or [] for uid in pin[2] or []) if scope is None else ()
    regions=(*view.direct_regions,*view.nested_regions,*([w.local_data.regions[scope]] if scope else []))
    interfaces=tuple((r.id,r.name,r.bbox,r.parent_id,r.pin_mode,tuple(r.pins.items())) for r in regions)
    return (id(w.baseline),id(w.layout_connectivity),id(p),tuple(visible),interfaces,top_figures,
        tuple(w.local_data.pins.items()) if scope is None else (),
        tuple((key,id(value)) for key,value in w.guard_previews.items() if key in guard_ids),
        tuple((op.uid,op.guard.get('net_intent')) for op in w.operations if op.action=='guard' and op.uid in guard_ids))


def scope_pins(w,p,scope,peek=False):
    """Current level, optionally exposing exactly one local module level."""
    from .view_scope import view_scope
    view=view_scope(w,scope,peek)
    uids={u for u in projected(w) if view.visible(u,w.baseline.text_owners)}
    regions=[r.id for r in (*view.direct_regions,*view.nested_regions)]+([scope] if scope else [])
    pins,warnings=pins_for_view(w,p,uids,regions,include_top=scope is None)
    nested={r.id for r in view.nested_regions}
    for pin in pins:
        pin['preview']=pin['owner'] in nested or pin['owner'] in uids and view.owners.get(pin['owner'])!=scope
        region=w.local_data.regions.get(pin['owner']) if pin['local'] else None
        if region and pin['id'] in region.pins:
            from .pin_placement import center
            port=region.pins[pin['id']]
            x,y=center(port);(a,b),(c,d)=region.bbox
            pin['side']=min(((abs(x-a),'left'),(abs(x-c),'right'),(abs(y-b),'bottom'),(abs(y-d),'top')))[1]
            pin['directional']=region.pin_mode=='directional'
            pin['physical_required']=not (region.id==scope and pin['directional'])
            group=port.access_group or port.id
            related=[v.id for v in region.pins.values() if (v.access_group or v.id)==group]
            pin['copied_port_group']=group
            pin['interface_group']=(region.id+':'+group) if region.parent_id==scope and len(related)>1 else None
            pin['alternative_pin_ids']=related if pin['interface_group'] else []
    return pins,warnings



def build_scope_graph(w,p,scope,peek=False):
    """Shared current-level graph: external conductors and native PIN access.

    Leaf poly/well/contact evidence extends PIN access; arbitrary internal
    metal, native modules and transistor channels remain outside this view.
    """
    from .physical_connectivity import physical_graph
    from .view_scope import view_scope
    objects=projected(w);view_scope_data=view_scope(w,scope,peek)
    uids={u for u in objects if view_scope_data.visible(u,w.baseline.text_owners)}
    # Parent overflight may be drawn as context, but is not this level's net.
    pins,pin_warnings=scope_pins(w,p,scope,peek)
    native_devices={uid for uid in uids if objects[uid].kind in ('inst','mosaic')}
    external=uids-native_devices
    view=w.model_copy(update={'baseline':w.baseline.model_copy(update={'objects':{u:o for u,o in w.baseline.objects.items() if u in external}}),
        'operations':tuple(op for op in w.operations if op.uid in external)})
    physical,_,warnings,_,_=extract(view,p,Region(bbox=((-MAX_DBU,-MAX_DBU),(MAX_DBU,MAX_DBU))),0)
    warnings+=pin_warnings
    from .conduction_access import leaf_access_material
    access,access_warnings=leaf_access_material(w,p,native_devices,pins)
    physical+=access;warnings+=access_warnings
    # A native PIN is real cached material. Local interface markers are not.
    for pin in pins:
        if not pin['local'] and not pin.get('existing_material'):
            for layer,g in pin['figures']:physical.append(Physical(pin['owner'] or pin['id'],layer,g,True,(),None,None))
    graph=physical_graph(view,p,{'schema_version':'colayout-agent-intent-1','instance_map':{},'nets':{}},{},physical_override=(physical,warnings))
    graph['pins']=pins;graph['scope']=scope;graph['peek']=peek
    graph['blackbox_ids']={uid for uid in uids if w.layout_connectivity and uid in w.layout_connectivity.instances and w.layout_connectivity.instances[uid].black_box}
    graph['access_materials']=access
    from .interface_access import scoped_figures
    for pin in pins:pin['contact_figures']=scoped_figures(w,scope,pin)
    graph['warnings']=[r for r in graph['report']['coverage']['warnings'] if r.get('kind')!='empty_intent_net']
    from .net_selection import index_contacts
    index_contacts(graph)
    return graph


def trace_at(graph,uid,x,y,*,layer=None,tolerance=0):
    from shapely.ops import unary_union
    pt=Point(x,y)
    candidates=[n for n in graph['nodes'] if n['owner_uid']==uid and n['geometry'].distance(pt)<=tolerance]
    if not candidates:return {'nodes':[],'vias':[],'nets':[],'pin_ids':[],'message':'此处没有可追踪的金属；黑盒内部需先进入对应层次。'}
    seed=min(candidates,key=lambda n:(n['layer']!=layer,n['geometry'].distance(pt),n['id']))
    nodes=[n for n in graph['nodes'] if n['component_id']==seed['component_id']];ids={n['id'] for n in nodes}
    via_edges=[e for e in graph['edges'] if e['kind']=='via' and set(e['node_ids'])<=ids]
    vias=list({(e.get('via_owner_uid'),e['cut_layer'],e['geometry'].wkb):e for e in via_edges}.values())
    layers=defaultdict(list)
    for node in nodes:layers[node['layer']].append(node['geometry'])
    material={k:unary_union(v) for k,v in layers.items()};nets=set();contacts=[];partial=[]
    for pin in graph['pins']:
        if pin.get('physical_required') is False:continue
        hit=False;coverage=[]
        for pl,g in pin.get('contact_figures',pin['figures']):
            conductor=material.get(pl)
            if conductor is None:coverage.append(False);continue
            touch=conductor.intersection(g)
            if touch.area>0 or touch.length>0:hit=True
            coverage.append(conductor.covers(g))
        from .interface_layers import covered
        complete=covered(pin,coverage)
        if hit:
            contacts.append(pin['id'])
            if pin['net'] is not None:nets.add(pin['net'])
            if pin['local'] and not complete:partial.append(pin['id'])
    if len(nets)>1:message='短接候选：'+' / '.join(sorted(nets))
    elif nets:message='NET：'+next(iter(nets))
    else:message='未接到当前层次的已知 PIN，NET 未知'
    if partial:message+=' · 本地 PIN 尚未完整覆盖'
    if graph['warnings']:message+=' · 存在未覆盖/缺失的几何数据'
    return {'component_id':seed['component_id'],'nodes':nodes,'vias':vias,'nets':sorted(nets),
        'pin_ids':contacts,'partial_pins':partial,'message':message}


def prime_pin_geometry(w,p):
    """Bounded load-time preparation of immutable geometry, with no evidence change.

    Unsupported data still produces the normal warnings on query. Avoid a
    cache-thrashing warm-up for documents larger than the geometry cache.
    """
    from .model import LiteError
    from .mpp_geometry import rows
    objects=projected(w)
    if len(w.baseline.pins)<=6000:
        for pin in w.baseline.pins:
            uid=pin.get('instance_uid')
            if uid not in objects or uid not in w.baseline.objects:continue
            try:cached_pin_geometry(w.baseline,pin,w.baseline.objects[uid].placement,objects[uid].placement)
            except (KeyError,ValueError,TypeError):pass
    guards=[obj for obj in objects.values() if obj.mpp]
    if len(guards)<=24:
        metals={r['layer'] for r in p.layers if r.get('material')=='metal'}
        for obj in guards:
            try:rows(w,p,obj,layers=metals)
            except (LiteError,ValueError,KeyError,TypeError):pass
