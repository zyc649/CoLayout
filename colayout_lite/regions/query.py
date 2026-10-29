"""Pure local ownership and boundary queries. No bridge, no device matching."""
from collections import defaultdict
from ..editor import projected
from ..geometry import box,ORIENT,compose,transform,shape_figure,via_figures
from ..model import LiteError
from ..geometry_memo import GeometryMemo
from math import floor,ceil

_bounds_cache=GeometryMemo(entries=4096)


def object_bounds(w,obj,profile):
    """One outward DBU envelope shared by published bbox and ownership checks."""
    bounds=_object_bounds(w,obj,profile)
    if bounds is None:return None
    def snap(v,lower):
        nearest=round(v)
        return nearest if abs(v-nearest)<1e-6 else floor(v) if lower else ceil(v)
    return tuple(tuple(snap(v,i==0) for v in pt) for i,pt in enumerate(bounds))


def _object_bounds(w,obj,profile):
    if obj.shape:
        if obj.shape.kind=='rect':return obj.shape.bbox
        from ..geometry_paths import figure_path
        def calculate():
            figures=via_figures(obj.shape,profile) if obj.kind=='stdVia' else [shape_figure(obj.shape)]
            rects=[figure_path(f).boundingRect() for f in figures]
            bounds=[(r.left(),-r.bottom(),r.right(),-r.top()) for r in rects]
            return obj.shape,((min(b[0] for b in bounds),min(b[1] for b in bounds)),(max(b[2] for b in bounds),max(b[3] for b in bounds)))
        return _bounds_cache.get(profile,id(obj.shape),calculate)[1]
    old=w.baseline.objects.get(obj.uid)
    if old and old.bbox and old.placement and obj.placement:
        a,b,c,d=ORIENT[old.placement.orientation];x,y=old.placement.origin
        return box(old.bbox,compose(transform(obj.placement.origin,obj.placement.orientation),(a,c,b,d,-a*x-c*y,-b*x-d*y)))
    return obj.bbox


def owner_map(w):
    return {uid:r.id for r in w.local_data.regions.values() for uid in r.object_uids}


def children(w,region_id):
    return [r for r in w.local_data.regions.values() if r.parent_id==region_id]


def descendants(w,region_id):
    result={region_id}
    for child in children(w,region_id):result.update(descendants(w,child.id))
    return result


def members(w,region_id):
    return {uid for ident in descendants(w,region_id) for uid in w.local_data.regions[ident].object_uids}


def metals(profile):
    return tuple(dict.fromkeys(layer for layer,purpose in profile.writable_lpps if purpose=='drawing'
        and any(r['layer']==layer and r.get('material')=='metal' for r in profile.layers)))


def object_net(obj):
    return (obj.shape.net_intent if obj.shape else None) or obj.observed_net


def boundary(w,region_id,*,include_reference=True):
    """One interface candidate per actual Layout net. Reference evidence is labeled.

    Same-name reference top nets contribute tagged boundary candidates.
    Ambiguous names require a recorded human association. Never invent
    Layout endpoints, device matching, m/finger expansion or physical connectivity.
    """
    selected=members(w,region_id);layout=w.layout_connectivity
    if layout is None:return {'nets':[],'unresolved':[{'reason':'缺少 Layout 原生端口/网络，请先显式导入'}]}
    owners=defaultdict(set);endpoints=defaultdict(list);unresolved=[];outside_ports=set()
    for uid,inst in layout.instances.items():
        for terminal in inst.terminals.values():
            for name,net in (terminal.members or {terminal.name:terminal.net}).items():
                if net is None:
                    if uid in selected:unresolved.append({'reason':'器件端口未分配网络','endpoint':inst.name+'.'+name})
                    continue
                owners[net].add(uid);endpoints[net].append((uid,inst.name+'.'+name))
    for port in layout.ports.values():
        outside_ports.update(n for n in (port.members or {port.name:port.net}).values() if n is not None)
    for uid,obj in projected(w).items():
        if obj.kind in ('inst','mosaic'):continue
        net=object_net(obj)
        if net:owners[net].add(uid)
        if obj.mpp:
            from ..guard_ports import names
            declared=names(obj)
            pending=next((o.guard.get('net_intent') for o in w.operations if o.uid==uid and o.action=='guard'),None)
            if pending:declared={pending}
            for name in declared:
                owners[name].add(uid);endpoints[name].append((uid,'保护环.'+name))
    if w.local_data.regions[region_id].interface_policy=='reference_v2':
        # A child's declared interface is the parent's endpoint contract. Its
        # missing internal access belongs to the child, not the parent task.
        for child in children(w,region_id):
            selected.add(child.id)
            for pin in child.pins.values():
                owners[pin.net].add(child.id)
                endpoints[pin.net].append((child.id,child.name+'.'+pin.name))
    inside={net for net,uids in owners.items() if uids&selected}
    evidence={net:[] for net in inside}
    for net in inside:
        if owners[net]-selected:evidence[net].append('Layout 区外对象同网端口/导体')
        if net in outside_ports:evidence[net].append('Layout 原生顶层 PIN')
    for pin in w.local_data.pins.values():
        if pin.net in inside:evidence[pin.net].append('已声明的本地 PIN：'+pin.name)
    # A parent interface is an external obligation even while the parent is
    # internally being subdivided into smaller construction regions.
    parent=w.local_data.regions[region_id].parent_id
    while parent:
        for pin in w.local_data.regions[parent].pins.values():
            if pin.net in inside:evidence[pin.net].append('上层操作区接口：'+pin.name)
        parent=w.local_data.regions[parent].parent_id
    deferred={}
    if include_reference and w.circuit:
        from ..circuit.query import require_context
        try:require_context(w)
        except LiteError as exc:unresolved.append({'reason':str(exc)})
        else:
            from .reference_boundary import obligations,legacy_obligations
            planner=obligations if w.local_data.regions[region_id].interface_policy=='reference_v2' else legacy_obligations
            for requirement in planner(w,selected):
                target=requirement['target'];missing=requirement['missing_terminals']
                if target in inside:
                    evidence[target].append(requirement['evidence'])
                elif target is not None and missing and not requirement['has_native_member']:
                    # Explicit construction intent only. Do not add Layout
                    # instTerms, geometry, or physical component unions.
                    evidence.setdefault(target,[]).append(requirement['evidence']+'（待补实体接口）')
                else:
                    unresolved.append({'reason':'原理图外部网络无法明确关联到 Layout 网络',
                        'reference_net':requirement['reference_net'],'scope':requirement['scope'],
                        'layout_candidates':sorted(inside)})
                    continue
                if missing and not any(uid in selected for uid,_ in endpoints[target]):
                    deferred.setdefault(target,[]).extend(missing)
    elif include_reference:unresolved.append({'reason':'缺少原理图参考，无法核对只有顶层接口的网络'})
    return {'nets':[{'net':net,'evidence':list(dict.fromkeys(evidence[net])),
        'deferred':net in deferred,'missing_terminals':deferred.get(net,[]),
        'inside_endpoints':[label for uid,label in endpoints[net] if uid in selected]}
        for net in sorted(evidence) if evidence[net]],'unresolved':unresolved,
        'deferred':[{'net':net,'missing_terminals':rows,'reason':'原理图已声明；区内尚无原生 PIN 或保护环接口'} for net,rows in sorted(deferred.items())]}
