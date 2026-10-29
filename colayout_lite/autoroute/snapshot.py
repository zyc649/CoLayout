"""Export a frozen, current-level physical problem. Never read Virtuoso."""
from collections import defaultdict
from math import ceil, lcm
from uuid import uuid4
from shapely.geometry import box, mapping
from shapely.ops import unary_union
from ..model import LiteError, digest
from ..editor import projected
from ..regions.query import owner_map, children, object_bounds, metals
from ..regions.constraints import _native_access
from ..region_analysis import scope_graph, connectivity
from ..materials import extract
from ..drc.models import Region
from .geometry import figure, parts
from .models import RoutingProblem, LayerRule, ViaRule, Material, Barrier, TerminalGroup








def prepare(w, p, drc, region_id, *, request_id=None, layer_pair=None, layers=None):
    region = w.local_data.regions.get(region_id)
    if region is None:raise LiteError('ROUTING_REGION_REQUIRED','请选择一个本地操作区。')
    if w.state in ('submitting','indeterminate','conflict'):raise LiteError('WORKSPACE_REQUIRES_RECOVERY')
    if w.layout_connectivity is None:raise LiteError('LAYOUT_CONNECTIVITY_MISSING','缺少原生 Layout 网络，不能用原理图或参数猜测。')
    objects = projected(w); owners = owner_map(w)
    device_ids = [u for u,o in objects.items() if owners.get(u)==region_id and o.kind in ('inst','mosaic')]
    if len(device_ids)+len(children(w,region_id))>64:
        raise LiteError('ROUTING_REGION_TOO_LARGE','当前支持最多 64 个当层器件/子模块；复杂区域建议分区。')
    from .layers import resolve
    rules,vias,cut_checked=resolve(p,drc,layers if layers is not None else layer_pair)
    pair=[r.name for r in rules];scale=p.dbu_per_micron
    cut_layers={v.cut_layer for v in vias}
    from ..regions.query import boundary
    external=boundary(w,region_id,include_reference=False)
    missing={r['net'] for r in external['nets']}-{pin.net for pin in region.pins.values()}
    if missing or external['unresolved']:
        raise LiteError('ROUTING_INTERFACE_INCOMPLETE','区域外部网络缺少本地接口，或 Layout 网络数据不完整。',missing_nets=sorted(missing),issues=external['unresolved'])
    graph = scope_graph(w,p,region_id); report = connectivity(graph)
    if graph['warnings']:raise LiteError('ROUTING_GEOMETRY_INCOMPLETE','当前层有缺失的几何。',warnings=graph['warnings'])
    unknown = [pin['id'] for pin in graph['pins'] if pin['net'] is None or not pin['figures']]
    if unknown:raise LiteError('ROUTING_PIN_UNRESOLVED','存在未归属网络或缺少接入几何的 PIN；请在 Virtuoso 补齐原生连接后重新导入。',pin_ids=unknown,
        pins=[{'id':pin['id'],'name':pin['label'],'net':pin['net'],'layers':sorted({l for l,g in pin['figures']})} for pin in graph['pins'] if pin['id'] in unknown])
    from ..conduction_rules import ConductionRules
    conduction=ConductionRules(p);all_metals=conduction.metals
    gate_pins=[{'name':pin['label'],'net':pin['net'],'layers':sorted({l for l,g in pin['figures']})}
        for pin in graph['pins'] if any(l in conduction.gates for l,g in pin['figures'])]
    if gate_pins:
        raise LiteError('ROUTING_GATE_PIN_UNSUPPORTED','当前本地规则不连接 Gate/GT 与金属。存在 Gate 层 PIN，自动布线无法完成；请在 Virtuoso 将端口定义在金属层后重新导入。',pins=gate_pins)
    metal_components={n['component_id'] for n in graph['nodes'] if n['layer'] in all_metals}
    missing_native=[{'id':pin['id'],'name':pin['label'],'net':pin['net'],'layers':sorted({l for l,g in pin['figures']}),
                     'unescaped_components':sorted(graph['pin_components'].get(pin['id'],set())-metal_components)}
                    for pin in graph['pins'] if not pin['local'] and
                    (not graph['pin_components'].get(pin['id']) or not graph['pin_components'][pin['id']]<=metal_components)]
    if missing_native:
        names='、'.join(row['name']+'（'+','.join(row['layers'])+'）' for row in missing_native[:8])
        if len(missing_native)>8:names+=f' 等 {len(missing_native)} 个端口'
        raise LiteError('ROUTING_NATIVE_ACCESS_REQUIRED',names+' 尚未通过有效接触孔连到金属层。请手动引出后重试；自动布线不会画 GT/NW 或代建 Gate/Body 接触孔。',pins=missing_native,selected_layers=pair)
    if report['shorts']:raise LiteError('ROUTING_EXISTING_SHORT','请先修复已有短路。',shorts=report['shorts'])
    if not graph['pins']:raise LiteError('ROUTING_NO_PINS')
    pins_by_id = {pin['id']:pin for pin in graph['pins']}
    groups = []
    for cid, ids in sorted(graph['component_pins'].items()):
        net = pins_by_id[next(iter(ids))]['net']
        figures = tuple(figure(n['layer'],n['geometry']) for n in graph['nodes'] if n['component_id']==cid and n['layer'] in pair)
        if not figures:raise LiteError('ROUTING_PIN_LAYER_UNSUPPORTED','PIN 所在分量没有所选金属层接入。',pin_ids=sorted(ids),selected_layers=pair,
            pins=[{'id':pid,'name':pins_by_id[pid]['label'],'net':pins_by_id[pid]['net'],'layers':sorted({l for l,g in pins_by_id[pid]['figures']})} for pid in sorted(ids)])
        groups.append(TerminalGroup(id=cid,net=net,pin_ids=tuple(sorted(ids)),figures=figures))
    for pin in graph['pins']:
        contacts = graph['pin_components'].get(pin['id'])
        if pin['local'] and (not contacts or pin['id'] in graph['partial_pin_ids']):
            fs = tuple(figure(layer,g) for layer,g in pin['figures'] if layer in pair)
            alternative=pin.get('layer_mode')=='any_metal'
            if not fs or not alternative and len(fs)!=len(pin['figures']):raise LiteError('ROUTING_PIN_LAYER_UNSUPPORTED',pin['label'])
            groups.append(TerminalGroup(id='landing:'+pin['id'],net=pin['net'],pin_ids=(pin['id'],),figures=fs,landing=True,alternative_layers=alternative))
    # Exact physical geometry provides conservative collision obstacles. Native
    # internal cuts are NOT interpreted as generic interconnect connectivity.
    halo = max([drc.local_halo_um]+[r.value for r in drc.rules if r.enabled and r.kind!='area'])*scale
    from ..hierarchy import is_hierarchical_instance
    native_blackboxes={uid for uid,obj in objects.items() if is_hierarchical_instance(w,obj)}
    # Native modules stay opaque even where a routing corridor is opened.
    # Their public PIN geometry is already present in the shared PIN graph.
    physical,_,warnings,_,_ = extract(w,p,Region(bbox=region.bbox),halo,owner_filter=set(objects)-native_blackboxes)
    if warnings:raise LiteError('ROUTING_GEOMETRY_INCOMPLETE','碰撞检查的几何不完整。',warnings=warnings)
    direct = {u for u in objects if owners.get(u)==region_id}
    # The shared graph is the only electrical authority. Do not rebuild a
    # second graph with arbitrary PCell metal: it can connect separate access
    # domains through a resistor body that the PIN projection correctly omits.
    # Exact internal geometry is still retained as collision obstacles below.
    from .scope_materials import routing_materials, hidden_net_proofs
    materials = routing_materials(graph, physical, pair, cut_layers, direct,
        hidden_net_proofs(w,p,region_id))
    barriers = []
    for keep in w.local_data.keepouts.values():
        if box(*keep.bbox[0],*keep.bbox[1]).intersects(box(*region.bbox[0],*region.bbox[1])):
            barriers.extend(Barrier(layer=l,geometry=mapping(box(*keep.bbox[0],*keep.bbox[1])),owner=keep.id) for l in keep.layers if l in pair)
    for child in children(w,region_id):
        for layer in child.blocked_layers:
            if layer not in pair:continue
            from ..interface_layers import layers as interface_layers
            access={pin.net:mapping(box(*pin.bbox[0],*pin.bbox[1])) for pin in child.pins.values() if layer in interface_layers(pin,p)}
            barriers.append(Barrier(layer=layer,geometry=mapping(box(*child.bbox[0],*child.bbox[1])),owner=child.id,access=access))
    for uid,inst in w.layout_connectivity.instances.items():
        if not inst.black_box or uid not in objects:continue
        bounds=object_bounds(w,objects[uid],p)
        if bounds is None:raise LiteError('ROUTING_BOUNDS_MISSING',uid)
        for layer in w.local_data.native_blocked_layers.get(uid,metals(p)):
            if layer not in pair:continue
            access={net:mapping(unary_union(fs)) for net in {pin['net'] for pin in graph['pins']}
                    if (fs:=_native_access(w,uid,layer,net))}
            from ..native_routing_windows import blocked_geometry
            obstacle=blocked_geometry(w,uid,layer,bounds,objects)
            if not obstacle.is_empty:
                barriers.append(Barrier(layer=layer,geometry=mapping(obstacle),owner=uid,access=access))
    if len(groups)>256 or len(materials)>20000:raise LiteError('ROUTING_COMPLEXITY_LIMIT','该区域几何较复杂，请先选择更小的测试区域。')
    bindings=[binding for binding in w.circuit.bindings if binding.layout_uid in device_ids] if w.circuit else []
    from ..circuit.hierarchy import reference_rows
    reference={'role':'reference only; connection targets always come from Layout pins',
        'source':w.circuit.source.model_dump(mode='json') if w.circuit else None,
        'instances':{row['qualified_name']:row for row in reference_rows(w.circuit,bindings)} if w.circuit else {},
        'bindings':[binding.model_dump(mode='json') for binding in bindings]}
    return RoutingProblem(request_id=request_id or uuid4().hex, source_digest=digest(w.model_dump(mode='json')),
        workspace_id=w.id,revision=w.revision,region_id=region_id,region_name=region.name,bounds=region.bbox,
        dbu_per_micron=scale,grid=p.grid,layers=rules,
        schema_version='colayout-routing-problem-2',vias=vias,via=vias[0] if len(vias)==1 else None,
        # Track combinations are implicit; memory is bounded by expanded search
        # states rather than by materializing this Cartesian product.
        limits={'grid_nodes':8000000,'search_states':500000,'shapes':3000,'candidates':3,'max_vias_per_branch':max(2,2*(len(pair)-1)),'heuristic_weight':1.4},
        pins=tuple({'id':pin['id'],'name':pin['label'],'net':pin['net'],'owner':pin['owner'],'local':pin['local'],'layer_mode':pin.get('layer_mode','single'),
                    'figures':[figure(layer,g).model_dump(mode='json') for layer,g in pin['figures']]} for pin in graph['pins']),
        groups=tuple(groups),materials=tuple(materials),barriers=tuple(barriers),
        devices=tuple({'id':u,'name':objects[u].attributes.get('name',u),'master':objects[u].attributes.get('master_key'),
            'bounds':object_bounds(w,objects[u],p),'placement':objects[u].placement.model_dump(mode='json') if objects[u].placement else None} for u in device_ids),reference=reference,
        coverage={'connectivity':report,'external_interfaces':external,'selected_layers':pair,'via_cut_width_rule_checked':cut_checked,
                  'limits':'Configured local rules only; no LVS, parasitic, EM, matching or signoff claim.'})
