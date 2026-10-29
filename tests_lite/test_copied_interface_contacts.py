from shapely.geometry import box
from colayout_lite.net_selection import index_contacts
from colayout_lite.region_analysis import connectivity


def graph(*, parent=True, two_branches=False, wire=True):
    def pin(pid, x, owner, group=None):
        return {
            'id': pid,
            'name': pid,
            'label': pid,
            'owner': owner,
            'owner_name': owner,
            'net': 'N',
            'local': True,
            'figures': [('M1', box(x, 0, x + 1, 1))],
            'interface_group': group,
        }

    group = 'child:copied-terminal' if parent else None
    pins = [pin('a', 0, 'child', group), pin('b', 10, 'child', group), pin('out', 1, 'top')]
    nodes = (
        [
            {
                'id': 'n0',
                'owner_uid': 'wire0',
                'layer': 'M1',
                'geometry': box(0, 0, 2, 1),
                'component_id': 0,
            }
        ]
        if wire
        else []
    )
    if two_branches:
        pins.append(pin('out2', 11, 'top'))
        nodes.append(
            {
                'id': 'n1',
                'owner_uid': 'wire1',
                'layer': 'M1',
                'geometry': box(10, 0, 12, 1),
                'component_id': 1,
            }
        )
    g = {
        'pins': pins,
        'nodes': nodes,
        'edges': [],
        'warnings': [],
        'dbu_per_micron': 1000,
        'report': {'coverage': {'conduction': {'metal_layers': ['M1']}}},
    }
    index_contacts(g)
    return g


def test_parent_can_use_one_explicit_copy_but_child_requires_both_ports():
    parent = connectivity(graph())
    assert parent['complete'] and parent['nets'][0]['unattached'] == []
    child = connectivity(graph(parent=False))
    assert not child['complete'] and child['nets'][0]['unattached'] == ['b']


def test_using_two_copied_ports_records_logical_link_not_fake_physical_merge():
    g = graph(two_branches=True)
    report = connectivity(g)
    assert report['complete']
    assert report['nets'][0]['components'] == [0, 1]
    assert report['nets'][0]['logical_component_count'] == 1
    assert [n['component_id'] for n in g['nodes']] == [0, 1]
    assert not connectivity(graph(parent=False, two_branches=True))['complete']


def test_copied_ports_never_pass_without_any_actual_landing():
    assert not connectivity(graph(wire=False))['complete']


def test_partial_only_contact_does_not_satisfy_the_group():
    g = graph()
    g['nodes'][0]['geometry'] = box(0, 0, 0.4, 1)
    index_contacts(g)
    assert not connectivity(g)['complete']
