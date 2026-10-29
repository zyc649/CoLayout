"""Explicit copied child ports are alternative accesses to one module terminal.

Keep physical component IDs and geometry untouched. The parent may use the
child's declared interface link; inside the child all fixed ports remain real
landing obligations. Net-name equality alone never creates such a link.
"""

from collections import defaultdict


def groups(graph):
    grouped = defaultdict(list)
    for pin in graph['pins']:
        if pin.get('interface_group') and pin.get('net') is not None:
            grouped[(pin['interface_group'], pin['net'])].append(pin)
    links = []
    optional = set()
    for (group, net), pins in grouped.items():
        complete = [
            p['id']
            for p in pins
            if graph['pin_components'].get(p['id']) and p['id'] not in graph['partial_pin_ids']
        ]
        ids = [p['id'] for p in pins]
        components = set().union(*(graph['pin_components'].get(pid, set()) for pid in ids))
        if complete:
            optional.update(ids)
        links.append(
            {
                'group_id': group,
                'owner': pins[0]['owner'],
                'net': net,
                'pin_ids': ids,
                'accessed_pin_ids': complete,
                'physical_components': sorted(components),
                'satisfied': bool(complete),
                'basis': 'explicit copied child-module terminal; internal wiring checked in child scope',
            }
        )
    return links, optional


def component_count(components, links):
    roots = {c: c for c in components}

    def root(value):
        while roots[value] != value:
            roots[value] = roots[roots[value]]
            value = roots[value]
        return value

    for link in links:
        if not link['satisfied']:
            continue
        joined = [c for c in link['physical_components'] if c in roots]
        for c in joined[1:]:
            roots[root(c)] = root(joined[0])
    return len({root(c) for c in roots})
