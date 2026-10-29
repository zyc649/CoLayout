"""Prove hidden conductor nets without flattening the parent routing interface.

Each child level is traced independently from actual metal and cached PINs.
Only fully covered conductor geometry with one proven net may be labelled.
The parent still targets its child's fixed port, never the child's internals.
"""
from collections import defaultdict
from shapely.ops import unary_union
from ..regions.query import children,descendants
from ..inspection_data import build_scope_graph


def hidden_net_proofs(workspace,profile,scope):
    proofs=defaultdict(list)
    scopes={ident for child in children(workspace,scope) for ident in descendants(workspace,child.id)}
    for ident in scopes:
        graph=build_scope_graph(workspace,profile,ident,False)
        if graph['warnings']:continue
        pins={p['id']:p for p in graph['pins']}
        nets={cid:{pins[pid]['net'] for pid in ids} for cid,ids in graph['component_pins'].items()}
        for node in graph['nodes']:
            names=nets.get(node['component_id'],set())
            if len(names)!=1 or None in names:continue
            proofs[(node['owner_uid'],node['layer'],next(iter(names)))].append(node['geometry'])
    result=defaultdict(list)
    for (owner,layer,net),geometry in proofs.items():result[(owner,layer)].append((net,unary_union(geometry)))
    return result


def proven_net(proofs,row):
    names={net for net,g in proofs.get((row.owner,row.layer),()) if g.covers(row.geometry)}
    return next(iter(names)) if len(names)==1 else None


def routing_materials(graph, physical, layers, cut_layers, direct, hidden):
    """Use one PIN graph for nets; preserve all other copper as obstacles.

    Native-device geometry outside proven access is collision-only. Subtract
    already represented access from its obstacle copy so a PIN remains usable
    without labelling the rest of a device's intrinsic metal as the same net.
    """
    from shapely.geometry import mapping
    from .models import Material
    pins={pin['id']:pin for pin in graph['pins']}
    nets={cid:{pins[pid]['net'] for pid in ids} for cid,ids in graph['component_pins'].items()}
    covered=defaultdict(list);materials=[]
    for node in graph['nodes']:
        if node['layer'] not in layers:continue
        names=nets.get(node['component_id'],set())
        net=next(iter(names)) if len(names)==1 else None
        materials.append(Material(layer=node['layer'],geometry=mapping(node['geometry']),owner=node['owner_uid'] or '',net=net))
        covered[(node['owner_uid'],node['layer'])].append(node['geometry'])
    covered={key:unary_union(gs) for key,gs in covered.items()}
    for row in physical:
        if row.layer not in (*layers,*cut_layers):continue
        geometry=row.geometry
        if row.owner in direct and (access:=covered.get((row.owner,row.layer))) is not None:
            geometry=geometry.difference(access)
        if geometry.is_empty:continue
        materials.append(Material(layer=row.layer,geometry=mapping(geometry),owner=row.owner,
            net=proven_net(hidden,row) if row.layer in layers else None))
    return materials
