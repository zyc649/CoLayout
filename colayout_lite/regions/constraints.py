"""Scope and routing policy enforcement shared by all local geometry edits."""
from shapely.geometry import box
from shapely.ops import unary_union
from .query import owner_map,children,descendants,metals,object_bounds
from .models import contains,overlaps
from ..geometry import shape_figure,via_figures
from ..materials import polygon_from_figure,apply_delta,placement_delta
from ..model import LiteError
from ..interface_layers import layers as interface_layers


def _shape_rows(obj,profile):
    if not obj.shape:return []
    figures=via_figures(obj.shape,profile) if obj.kind=='stdVia' else [shape_figure(obj.shape)]
    # Rectangles and standard-via rectangles already carry exact axis-aligned
    # material bounds; no Qt path round trip is needed. Other caps/polygons
    # retain the shared exact geometry implementation.
    return [(f['lpp'][0],box(*f['bbox'][0],*f['bbox'][1])
             if f['kind']=='rect' and all(f['bbox'][0][i]<f['bbox'][1][i] for i in (0,1))
             else polygon_from_figure(f)) for f in figures]


def _native_access(w,uid,layer,net,objects=None,*,pin_rows=None):
    """Exact rectangles/polygons of cached native pins, never an inferred pin."""
    from ..pin_geometry import cached_pin_geometry
    from ..editor import projected
    current=projected(w) if objects is None else objects;result=[]
    instance=w.layout_connectivity.instances[uid]
    for pin in w.baseline.pins if pin_rows is None else pin_rows:
        if pin.get('instance_uid')!=uid or tuple(pin.get('lpp',()))[:1]!=(layer,):continue
        terminal=pin.get('terminal');nets=set()
        for term in instance.terminals.values():
            if terminal==term.name:nets.update((term.members or {term.name:term.net}).values())
            elif terminal in term.members:nets.add(term.members[terminal])
        if net is None or net not in nets:continue
        try:result.append(cached_pin_geometry(w.baseline,pin,w.baseline.objects[uid].placement,current[uid].placement))
        except (ValueError,KeyError,TypeError):continue  # No exemption without exact geometry.
    return result


class PolicyGeometry:
    """Geometry shared by one validation, never retained across workspace edits."""
    def __init__(self,w,profile,objects=None):
        from ..editor import projected
        self.w=w;self.profile=profile;self.objects=projected(w) if objects is None else objects
        self.obstacles={};self.native=[];default=metals(profile)
        self.native_base={};self.native_access={};self.pin_rows={};self.spatial={}
        for pin in w.baseline.pins:
            uid=pin.get('instance_uid')
            if isinstance(uid,str):self.pin_rows.setdefault(uid,[]).append(pin)
        if w.layout_connectivity:
            for uid,inst in w.layout_connectivity.instances.items():
                if inst.black_box and uid in self.objects:
                    self.native.append((uid,w.local_data.native_blocked_layers.get(uid,default),object_bounds(w,self.objects[uid],profile)))

    def for_net(self,scope,layer,net):
        key=(scope,layer,net)
        if key in self.obstacles:return self.obstacles[key]
        rows=[];missing=[];w=self.w
        from ..scope_state import ancestors
        applicable=ancestors(w,scope)|{scope}
        for keep in w.local_data.keepouts.values():
            if keep.scope_id not in applicable:continue
            if layer in keep.layers:rows.append((keep.id,box(*keep.bbox[0],*keep.bbox[1]),'禁布区'))
        for child in children(w,scope):
            if layer not in child.blocked_layers:continue
            g=box(*child.bbox[0],*child.bbox[1])
            access=[box(*p.bbox[0],*p.bbox[1]) for p in child.pins.values() if layer in interface_layers(p,self.profile) and p.fixed and net==p.net]
            if access:g=g.difference(unary_union(access))
            rows.append((child.id,g,'子操作区黑盒'))
        for uid,blocked,bounds in self.native:
            if layer not in blocked:continue
            if bounds is None:missing.append(uid);continue
            from ..native_routing_windows import blocked_geometry
            base_key=(uid,layer);access_key=(uid,layer,net)
            if base_key not in self.native_base:
                self.native_base[base_key]=blocked_geometry(w,uid,layer,bounds,self.objects)
            if access_key not in self.native_access:
                g=self.native_base[base_key]
                access=_native_access(w,uid,layer,net,self.objects,pin_rows=self.pin_rows.get(uid,()))
                self.native_access[access_key]=g.difference(unary_union(access)) if access else g
            g=self.native_access[access_key]
            rows.append((uid,g,'Virtuoso 黑盒模块'))
        self.obstacles[key]=(rows,missing);return rows,missing

    def candidates(self,scope,layer,net,geometry):
        """Broad phase only: exact intersections and their order stay unchanged."""
        from shapely import STRtree
        key=(scope,layer,net)
        rows,missing=self.for_net(scope,layer,net)
        if key not in self.spatial:self.spatial[key]=STRtree([row[1] for row in rows])
        indices=sorted(self.spatial[key].query(geometry))
        return [rows[i] for i in indices],missing


def violations(w,profile,obj,scope_id=None,*,context=None):
    """Return object IDs, layer and intersection bounds for local policy errors."""
    if not obj.shape and not obj.mpp:return []
    result=[];context=context or PolicyGeometry(w,profile)
    if context.w is not w or context.profile is not profile:raise ValueError('Policy geometry belongs to a different workspace or technology')
    if not context.native and not w.local_data.keepouts and not any(r.blocked_layers for r in children(w,scope_id)):
        return []
    if obj.mpp:
        from ..mpp_geometry import rows
        geometry_rows=rows(w,profile,obj)
    else:geometry_rows=_shape_rows(obj,profile)
    net=(obj.shape.net_intent if obj.shape else None) or obj.observed_net
    for layer,geometry in geometry_rows:
        obstacles,missing=context.candidates(scope_id,layer,net,geometry)
        result.extend({'object_id':obj.uid,'blocker_id':uid,'layer':layer,'reason':'原生模块缺少边界'} for uid in missing)
        for ident,obstacle,reason in obstacles:
            hit=geometry.intersection(obstacle)
            if not hit.is_empty and hit.area>1e-9:
                result.append({'object_id':obj.uid,'blocker_id':ident,'layer':layer,'reason':reason,'bbox':list(hit.bounds)})
    return result


def validate_edit(before,after,profile,scope_id,*,region_transforms=None):
    from ..editor import projected
    old=projected(before);new=projected(after);owners=owner_map(before);regions=dict(after.local_data.regions)
    moved=set()
    if region_transforms:
        from .transforms import verify_transforms
        moved=verify_transforms(before,after,profile,scope_id,region_transforms)
        validate_workspace(after,profile)
    if scope_id is not None and scope_id not in regions:raise LiteError('REGION_SCOPE_MISSING')
    changed={uid for uid in old.keys()|new.keys() if old.get(uid)!=new.get(uid)}
    context=PolicyGeometry(after,profile,new) if any(uid in new and (new[uid].shape or new[uid].mpp) for uid in changed) else None
    for uid in changed:
        # Associated native text follows its instance, it is not an independently
        # owned/editable object in the local construction hierarchy.
        if uid in before.baseline.text_owners:continue
        if uid in old and owners.get(uid)!=scope_id and uid not in moved:
            raise LiteError('REGION_SCOPE_VIOLATION','进入对象所属操作区后再编辑；上层不能修改黑盒内部。',uid=uid,owner=owners.get(uid))
        obj=new.get(uid)
        effective_scope=owners.get(uid) if uid in moved else scope_id
        if obj:
            bounds=object_bounds(after,obj,profile)
            if effective_scope:
                if bounds is None:raise LiteError('OBJECT_BOUNDS_MISSING',uid)
                if not contains(regions[effective_scope].bbox,bounds):
                    scale=profile.dbu_per_micron
                    raise LiteError('REGION_BOUNDARY_VIOLATION','编辑结果超出当前操作区。',uid=uid,region=scope_id,
                        proposed_bounds_um=[v/scale for point in bounds for v in point],
                        region_bounds_um=[v/scale for point in regions[effective_scope].bbox for v in point],
                        outside_sides=[side for i,side in enumerate(('left','bottom','right','top'))
                            if (bounds[0][i] < regions[effective_scope].bbox[0][i] if i<2
                                else bounds[1][i-2] > regions[effective_scope].bbox[1][i-2])])
            if obj.kind in ('inst','mosaic'):
                for child in children(after,effective_scope):
                    if bounds and overlaps(bounds,child.bbox):raise LiteError('OBJECT_OVERLAPS_CHILD_REGION',child.id)
            problems=violations(after,profile,obj,effective_scope,context=context)
            if problems:raise LiteError('LOCAL_ROUTING_BLOCKED','图形进入禁止布线的层/范围。',violations=problems)
        if scope_id:
            region=regions[scope_id];uids=list(region.object_uids)
            if uid not in moved:
                if uid not in old and obj and uid not in uids:uids.append(uid)
                elif obj is None and uid in uids:uids.remove(uid)
            regions[scope_id]=region.model_copy(update={'object_uids':tuple(uids),'revision':before.local_data.regions[scope_id].revision+1})
    return after.model_copy(update={'local_data':after.local_data.model_copy(update={'regions':regions})})


def check_workspace(w,profile):
    from ..editor import projected
    owners=owner_map(w);issues=[];context=PolicyGeometry(w,profile)
    for uid,obj in context.objects.items():issues.extend(violations(w,profile,obj,owners.get(uid),context=context))
    return {'revision':w.revision,'violations':issues,'passed':not issues,
            'scope':'本地禁布区和黑盒整层策略；不是工艺 DRC 或电气连通检查'}


def validate_workspace(w,profile):
    """Loaded/refreshed native geometry must still fit its local ownership."""
    from ..editor import projected
    from .query import boundary
    from ..native_routing_windows import validate
    validate(w,profile)
    objects=projected(w)
    for region in w.local_data.regions.values():
        for uid in region.object_uids:
            obj=objects.get(uid);bounds=object_bounds(w,obj,profile) if obj else None
            if bounds is None or not contains(region.bbox,bounds):
                name=obj.attributes.get('name',uid) if obj else uid
                raise LiteError('REGION_MEMBERSHIP_STALE',f'“{region.name}”中的 {name} 在读回状态中已不存在或超出区域。当前工作区保留；若要从服务器重新开始，请使用“重新导入”。',
                    region=region.id,region_name=region.name,uid=uid,object_name=name,region_bounds=region.bbox,object_bounds=bounds)
        for pin in region.pins.values():
            if not interface_layers(pin,profile) or set(interface_layers(pin,profile))-set(metals(profile)):raise LiteError('REGION_PIN_LAYER_UNAVAILABLE',pin.id)
        report=boundary(w,region.id)
        missing={r['net'] for r in report['nets']}-{p.net for p in region.pins.values()}
        if report['unresolved'] or missing:raise LiteError('REGION_INTERFACE_STALE','已固定接口需要重新核对；不会静默改变 PIN。',region=region.id,missing=sorted(missing),issues=report['unresolved'])


def validate_pending(w,profile):
    from ..editor import projected
    validate_workspace(w,profile);owners=owner_map(w);objects=projected(w);context=PolicyGeometry(w,profile,objects)
    for op in w.operations:
        if op.uid in objects and op.action not in ('delete','delete_guard'):
            problems=violations(w,profile,objects[op.uid],owners.get(op.uid),context=context)
            if problems:raise LiteError('LOCAL_ROUTING_BLOCKED','待提交图形违反本地禁布策略。',violations=problems)
