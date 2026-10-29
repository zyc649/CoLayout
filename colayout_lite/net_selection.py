"""Network display queries. Intent selects islands; it never electrically joins them."""
from collections import defaultdict
from shapely import STRtree
from shapely.ops import unary_union
from .inspection_data import trace_at
from .circuit.net_names import display_net,pin_signal_names


def index_contacts(graph):
    layers=defaultdict(list)
    for node in graph['nodes']:layers[node['layer']].append(node)
    trees={layer:STRtree([n['geometry'] for n in nodes]) for layer,nodes in layers.items()}
    contacts=defaultdict(set);pins_by_component=defaultdict(set);partial=set()
    for pin in graph['pins']:
        if pin.get('physical_required') is False:continue
        coverage=[]
        for layer,geometry in pin.get('contact_figures',pin['figures']):
            if layer not in trees:coverage.append(False);continue
            material=[]
            for index in trees[layer].query(geometry,predicate='intersects'):
                node=layers[layer][index];touch=geometry.intersection(node['geometry'])
                if touch.area>0 or touch.length>0:
                    material.append(node['geometry'])
                    contacts[pin['id']].add(node['component_id'])
                    pins_by_component[node['component_id']].add(pin['id'])
            coverage.append(unary_union(material).covers(geometry))
        from .interface_layers import covered
        complete=covered(pin,coverage)
        if pin['local'] and contacts[pin['id']] and not complete:partial.add(pin['id'])
    graph['pin_components']=dict(contacts);graph['component_pins']=dict(pins_by_component)
    graph['partial_pin_ids']=partial
    from .interface_contacts import groups
    graph['interface_contact_groups'],graph['optional_pin_ids']=groups(graph)


def select_net(graph,*,pin_id=None,point=None):
    """Return physical islands, intended targets and seed contacts separately.

    A virtual interface marker may touch several islands; the marker does not
    connect them. A net name on an unconnected route is not electrical proof.
    """
    pins={p['id']:p for p in graph['pins']};seed_components=set();nets=set();seed_trace=None
    if pin_id in pins:
        pin=pins[pin_id]
        if pin['net'] is not None:nets.add(pin['net'])
        seed_components.update(graph['pin_components'].get(pin_id,()))
    elif point:
        uid,x,y,layer,tolerance=point
        seed_trace=trace_at(graph,uid,x,y,layer=layer,tolerance=tolerance)
        if 'component_id' in seed_trace:seed_components.add(seed_trace['component_id'])
        nets.update(seed_trace['nets'])
    targets={pid for pid,p in pins.items() if p['net'] is not None and p['net'] in nets}
    # Gate is a separate local electrical domain. Logical net names must not
    # visually rejoin it to metal after the physical contact edge was removed.
    gates=set(graph.get('report',{}).get('coverage',{}).get('conduction',{}).get('gate_layers',()))
    seed_layers={n['layer'] for n in graph['nodes'] if n['component_id'] in seed_components}
    if gates and seed_layers:
        gate_only=seed_layers<=gates
        if gate_only or not seed_layers & gates:
            targets={pid for pid in targets if any((layer in gates)==gate_only for layer,g in pins[pid]['figures'])}
    if pin_id in pins:targets.add(pin_id)
    components=set(seed_components)
    for pid in targets:components.update(graph['pin_components'].get(pid,()))
    nodes=[n for n in graph['nodes'] if n['component_id'] in components];node_ids={n['id'] for n in nodes}
    vias=list({(e.get('via_owner_uid'),e['cut_layer'],e['geometry'].wkb):e for e in graph['edges']
        if e['kind']=='via' and set(e['node_ids'])<=node_ids}.values())
    contacts=set();seed_contacts=set();short_nets=set();conflicts=[]
    for component in components:
        ids=graph['component_pins'].get(component,set());contacts.update(ids)
        if component in seed_components:seed_contacts.update(ids)
        actual={pins[pid]['net'] for pid in ids if pins[pid]['net'] is not None}
        if len(actual)>1:
            short_nets.update(actual)
            conflicts.append({'component':component,'nets':sorted(actual),'pin_ids':sorted(ids)})
    unattached={pid for pid in targets if pins[pid].get('physical_required') is not False and not graph['pin_components'].get(pid)}
    partial=targets & graph['partial_pin_ids']
    names=pin_signal_names(graph['pins'])
    if nets:
        message='NET：'+' / '.join(display_net(net,names) for net in sorted(nets))+f' · {len(targets)} 个目标 · {len(components)} 个物理分量'
        if unattached:message+=f' · {len(unattached)} 个接口未接金属'
    else:message=(seed_trace or {}).get('message','未接到当前层次的已知 PIN，NET 未知')
    if short_nets:message+=' · 网络冲突（短接候选）：'+' / '.join(sorted(short_nets))
    if partial:message+=f' · {len(partial)} 个本地接口仅部分覆盖'
    if graph['warnings'] and '缺失' not in message:message+=' · 存在未覆盖/缺失的几何数据'
    return {'nodes':nodes,'vias':vias,'nets':sorted(nets),'pin_ids':contacts,'target_pin_ids':targets,
        'seed_pin_ids':seed_contacts,'component_ids':components,'unattached_pin_ids':unattached,'partial_pin_ids':partial,
        'short_nets':short_nets,'conflicts':conflicts,'message':message}
