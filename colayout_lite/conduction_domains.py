"""Keep leaf access extensions inside native electrical terminal boundaries.

A poly resistor must not turn into a wire when poly conduction is enabled.
Use the master's native terminal-net identity, never the instance's assigned
net name or a device/cell naming convention, to bound each access domain.
"""
from collections import defaultdict
from shapely import STRtree


def access_domains(nodes,links,used,pins,master,rules):
    from .physical_connectivity import _UnionFind,_touches_conductively
    active={i for i,n in enumerate(nodes) if n['layer'] in rules.gates|rules.wells}|set(used)
    uf=_UnionFind(len(nodes));layers=defaultdict(list)
    for i in active:layers[nodes[i]['layer']].append(i)
    trees={l:STRtree([nodes[i]['geometry'] for i in ids]) for l,ids in layers.items()}
    for layer,ids in layers.items():
        for i in ids:
            for index in trees[layer].query(nodes[i]['geometry'],predicate='intersects'):
                other=ids[int(index)]
                if other>i and _touches_conductively(nodes[i]['geometry'],nodes[other]['geometry']):uf.join(i,other)
    for a,b,g,details in links:uf.join(a,b)
    local_nets={row[0]:row[2] for row in master[8] or []}
    labels=defaultdict(set)
    for pin in pins:
        terminal=local_nets.get(pin['name']) or pin['name']
        for layer,g in pin['figures']:
            if layer not in trees:continue
            for index in trees[layer].query(g,predicate='intersects'):
                i=layers[layer][int(index)]
                if _touches_conductively(g,nodes[i]['geometry']):labels[uf.find(i)].add(terminal)
    # Only extend a known interface, never traverse an intrinsic element
    # between distinct native terminal nets (even if tied together outside).
    allowed={i for i in active if len(labels.get(uf.find(i),()))==1}
    by_layer=defaultdict(list)
    for i in allowed:
        if nodes[i]['layer'] in rules.gates|rules.wells:by_layer[nodes[i]['layer']].append(nodes[i]['geometry'])
    special_trees={l:STRtree(gs) for l,gs in by_layer.items()}
    def touches_access(g):
        return any(any(by_layer[l][int(i)].intersection(g).area>0 for i in tree.query(g,predicate='intersects')) for l,tree in special_trees.items())
    return allowed,touches_access
