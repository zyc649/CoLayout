"""Electrical outcomes from geometry, independent of route labels and GUI mode."""
import json

import pytest
from shapely.geometry import Polygon, box

from colayout_lite.physical_connectivity import check_connectivity, endpoint_geometries
from colayout_lite.drc.geometry import apply_delta
from colayout_lite.editor import Editor
from colayout_lite.geometry import ORIENT
from colayout_lite.model import Object, Operation, Placement, Shape, Snapshot, Workspace, digest
from colayout_lite.technology import TechnologyProfile


@pytest.fixture
def tech():
    return TechnologyProfile(id='agent-test', label='Connectivity fixture', native_fingerprint='fp',
        dbu_per_micron=1000, grid=2,
        layers=[dict(layer=name, purpose='drawing', material=material) for name, material in
                [('M1', 'metal'), ('M2', 'metal'), ('V1', 'cut'), ('AA', 'diff'), ('PO', 'poly'), ('CO', 'cut')]],
        writable_lpps=(('M1', 'drawing'), ('M2', 'drawing'), ('V1', 'drawing'), ('AA', 'drawing'), ('PO', 'drawing')),
        vias={'V12': dict(kind='stdViaDef', layer1='M1', layer2='M2', cut_layer='V1',
                         defaults=dict(cutWidth=40, cutHeight=40, cutRows=1, cutColumns=1,
                                       cutSpacing=[40, 40], layer1Enc=[20, 20], layer2Enc=[20, 20])),
              'contact': dict(kind='stdViaDef', layer1='AA', layer2='M1', cut_layer='CO',
                              defaults=dict(cutWidth=40, cutHeight=40, cutRows=1, cutColumns=1,
                                            cutSpacing=[40, 40], layer1Enc=[20, 20], layer2Enc=[20, 20]))})


def rect(x, y, xx, yy, layer='M1', net=None):
    return Shape(kind='rect', lpp=(layer, 'drawing'), bbox=((x, y), (xx, yy)), net_intent=net)


def workspace(tech, shapes=(), pins=(), objects=None, display=None):
    rows = {str(i): Object(uid=str(i), native_id=str(i), kind=s.kind, shape=s, bbox=s.bbox)
            for i, s in enumerate(shapes)}
    rows.update(objects or {})
    baseline = Snapshot(library='L', cell='C', library_path='/L', session='s', counter='1',
                        dirty=False, dbu_per_micron=1000, grid=2, technology_fingerprint='fp',
                        objects=rows, pins=list(pins), display=display or {})
    return Workspace(baseline=baseline, profile_id=tech.id)


def local(x, y, xx, yy, layer='M1', net='N'):
    return dict(net=net, lpp=[layer, 'drawing'], bbox=[[x, y], [xx, yy]])


def intent(nets=None, instances=None):
    return dict(schema_version='colayout-agent-intent-1', instance_map=instances or {},
                nets=nets if nets is not None else {'N': ['$A', '$B']})


def test_true_metal_overlap_and_json_contract(tech):
    w = workspace(tech, [rect(0, 0, 100, 40), rect(80, 0, 180, 40)])
    pins = {'A': local(0, 0, 20, 20), 'B': local(160, 0, 180, 20)}
    report = check_connectivity(w, tech, intent(), pins)
    assert report['status'] == 'pass'
    assert report['summary']['components'] == 1
    assert report['components'][0]['endpoint_names'] == ['$A', '$B']
    assert report['components'][0]['owner_uids'] == ['0', '1']
    assert json.loads(json.dumps(report))['revision'] == w.revision


@pytest.mark.parametrize('x,y,connected', [(100, 0, True), (100, 40, False), (102, 0, False)])
def test_shared_edge_but_not_corner_or_gap(tech, x, y, connected):
    w = workspace(tech, [rect(0, 0, 100, 40), rect(x, y, x+100, y+40)])
    r = check_connectivity(w, tech, intent(), {'A': local(0, 0, 20, 20), 'B': local(x+80, y, x+100, y+20)})
    assert (r['status'] == 'pass') is connected
    assert bool(r['opens']) is not connected


def test_net_labels_do_not_join_disconnected_shapes(tech):
    w = workspace(tech, [rect(0, 0, 100, 40, net='same'), rect(200, 0, 300, 40, net='same')])
    r = check_connectivity(w, tech, intent(), {'A': local(0, 0, 20, 20), 'B': local(280, 0, 300, 20)})
    assert r['status'] == 'fail'
    assert len(r['opens'][0]['groups']) == 2
    assert not r['coverage']['net_intent_used_as_connection']


def test_overlapping_different_metals_need_via(tech):
    shapes = [rect(-100, -40, 100, 40), rect(-40, -100, 40, 100, 'M2')]
    pins = {'A': local(-100, -20, -80, 20), 'B': local(-20, 80, 20, 100, 'M2')}
    assert check_connectivity(workspace(tech, shapes), tech, intent(), pins)['status'] == 'fail'
    shapes.append(Shape(kind='stdVia', via_definition='V12', origin=(0, 0)))
    r = check_connectivity(workspace(tech, shapes), tech, intent(), pins)
    assert r['status'] == 'pass'
    assert r['coverage']['via_link_count'] == 1
    assert r['components'][0]['layers'] == ['M1', 'M2']


def test_real_cut_layer_with_covering_metals_connects(tech):
    shapes = [rect(-100, -40, 100, 40), rect(-40, -100, 40, 100, 'M2'), rect(-20, -20, 20, 20, 'V1')]
    pins = {'A': local(-100, -20, -80, 20), 'B': local(-20, 80, 20, 100, 'M2')}
    assert check_connectivity(workspace(tech, shapes), tech, intent(), pins)['status'] == 'pass'


def test_partial_via_overlap_is_not_complete_connection(tech):
    shapes = [rect(-100, -40, 100, 40), rect(0, -100, 40, 100, 'M2'), rect(-20, -20, 20, 20, 'V1')]
    pins = {'A': local(-100, -20, -80, 20), 'B': local(0, 80, 20, 100, 'M2')}
    r = check_connectivity(workspace(tech, shapes), tech, intent(), pins)
    assert r['status'] == 'fail' and r['opens']
    assert not r['coverage']['complete']
    assert any(w['kind'] == 'uncovered_via_cut' for w in r['coverage']['warnings'])


def test_short_comes_from_distinct_intended_nets_on_one_component(tech):
    w = workspace(tech, [rect(0, 0, 200, 40)])
    pins = {'A': local(0, 0, 20, 20, net='VDD'), 'B': local(180, 0, 200, 20, net='VSS')}
    r = check_connectivity(w, tech, intent({'VDD': ['$A'], 'VSS': ['$B']}), pins)
    assert r['status'] == 'fail'
    assert r['shorts'][0]['nets'] == ['VDD', 'VSS']


@pytest.mark.parametrize('metal', [[], [rect(0, 0, 10, 20)]])
def test_local_pin_annotation_does_not_create_metal(tech, metal):
    r = check_connectivity(workspace(tech, metal), tech, intent({'N': ['$A']}), {'A': local(0, 0, 20, 20)})
    assert r['status'] == 'fail'
    assert r['opens'][0]['unconnected_endpoints'] == ['$A']
    assert not r['coverage']['local_pins_generate_metal']


def test_mos_active_or_poly_never_shorts_source_drain(tech):
    shapes = [rect(0, 0, 40, 40), rect(160, 0, 200, 40), rect(0, 0, 200, 40, 'AA'),
              rect(0, 0, 200, 40, 'PO'), rect(0, 0, 40, 40, 'CO'), rect(160, 0, 200, 40, 'CO')]
    pins = {'A': local(0, 0, 20, 20, net='D'), 'B': local(180, 0, 200, 20, net='S')}
    r = check_connectivity(workspace(tech, shapes), tech, intent({'D': ['$A'], 'S': ['$B']}), pins)
    assert r['status'] == 'pass' and not r['shorts']
    assert r['summary']['components'] == 3  # Two metal islands plus the isolated poly conductor.
    assert sorted(len(c['endpoint_names']) for c in r['components'])==[0,1,1]


def instance_workspace(tech, pin_layer='M1', kind='rect', polygon=None, second_pin=False):
    master_bbox = [[0, 0], [100, 80]]
    geometry = {'points': polygon} if polygon else {}
    raw = ['fig', 'fig', False, None, kind, pin_layer+'/drawing', master_bbox, list(geometry.items())]
    master = ['master', 'L', 'mos', 'layout', 1000, master_bbox, [], [], [], [raw], [], [['child_count', 0]]]
    root = ['root', 'L', 'C', 'layout', 1000, master_bbox, [], [], [], [],
            [['native', 'master', 'inst', [1000, 2000], 'R0', 1]], []]
    obj = Object(uid='mos', native_id='native', kind='inst', bbox=((1000, 2000), (1100, 2080)),
                 placement=Placement(origin=(1000, 2000)), attributes={'name': 'M.1', 'master_key': 'master'})
    pin = dict(instance_uid='mos', terminal='D', pin_index=0, figure_index=0,
               lpp=[pin_layer, 'drawing'], kind=kind, local_bbox=master_bbox,
               bbox=[[1000, 2000], [1100, 2080]], local_geometry=geometry, transform=[1, 0, 0, 1, 1000, 2000])
    pins = [pin]
    if second_pin:
        master[9].append(['fig2', 'fig2', False, None, 'rect', pin_layer+'/drawing', [[200, 0], [300, 80]], []])
        pins.append({**pin, 'pin_index': 1, 'local_bbox': [[200, 0], [300, 80]], 'bbox': [[1200, 2000], [1300, 2080]]})
    style = [[pin_layer, 'drawing'], None, 1, True, 'metal', None, None, None, None, None]
    return workspace(tech, pins=pins, objects={'mos': obj},
                     display={'root': 'root', 'nodes': {'root': root, 'master': master}, 'styles': [[pin_layer+'/drawing', style]], 'unsupported': []})


@pytest.mark.parametrize('orientation', list(ORIENT))
def test_instance_pin_exactly_follows_local_translation_rotation_mirror(tech, orientation):
    w = instance_workspace(tech)
    e = Editor(w, tech)
    e.apply([Operation(action='transform', uid='mos', before=digest(w.baseline.objects['mos'].semantic()),
                       placement=Placement(origin=(-2000, 3000), orientation=orientation))])
    i = intent({'N': ['M.1.D']}, {'M.1': 'mos'})
    rows = endpoint_geometries(e.w, tech, i, {})['M.1.D']
    expected = apply_delta(box(0, 0, 100, 80), (*ORIENT[orientation], -2000, 3000))
    assert Polygon(rows[0]['polygons'][0]['exterior']).equals(expected)
    r = check_connectivity(e.w, tech, i, {})
    assert r['status'] == 'pass'
    assert r['revision'] == 1


def test_polygon_pin_never_uses_bbox_as_conductor(tech):
    points = [[0, 0], [100, 0], [0, 80]]
    w = instance_workspace(tech, kind='polygon', polygon=points)
    i = intent({'N': ['M.1.D', '$A']}, {'M.1': 'mos'})
    # Inside bounding box but outside triangular pin.
    r = check_connectivity(w, tech, i, {'A': local(1080, 2060, 1100, 2080)})
    assert r['status'] == 'fail'
    assert r['opens'][0]['unconnected_endpoints'] == ['$A']
    g = endpoint_geometries(w, tech, i, {})['M.1.D'][0]
    assert Polygon(g['polygons'][0]['exterior']).area == 4000


def test_metal_pin_must_exist_in_physical_cache(tech):
    w = instance_workspace(tech)
    display = json.loads(json.dumps(w.baseline.display))
    display['nodes']['master'][9] = []
    w = w.model_copy(update={'baseline': w.baseline.model_copy(update={'display': display})})
    r = check_connectivity(w, tech, intent({'N': ['M.D']}, {'M': 'mos'}), {})
    assert r['status'] == 'incomplete'
    assert r['unresolved'][0]['reason'] == 'pin_physical_geometry_missing'


def test_missing_cache_and_unknown_pin_cannot_pass(tech):
    w = instance_workspace(tech)
    w = w.model_copy(update={'baseline': w.baseline.model_copy(update={'display': {}})})
    r = check_connectivity(w, tech, intent({'N': ['M.D', 'M.unknown']}, {'M': 'mos'}), {})
    assert r['status'] == 'incomplete'
    assert any(u['reason'] == 'terminal_missing' for u in r['unresolved'])
    assert not r['coverage']['complete']


def test_body_only_nonmetal_is_unresolved(tech):
    w = instance_workspace(tech, pin_layer='AA')
    r = check_connectivity(w, tech, intent({'BODY': ['M.D']}, {'M': 'mos'}), {})
    assert r['status'] == 'incomplete'
    assert r['unresolved'][0]['reason'] == 'nonmetal_endpoint'


def test_split_same_terminal_figures_are_not_implicitly_joined(tech):
    w = instance_workspace(tech, second_pin=True)
    r = check_connectivity(w, tech, intent({'N': ['M.D']}, {'M': 'mos'}), {})
    assert r['status'] == 'fail'
    assert len(r['opens'][0]['groups']) == 2


def test_projected_create_delete_changes_connectivity(tech):
    w = workspace(tech, [rect(0, 0, 40, 40), rect(160, 0, 200, 40)])
    pins = {'A': local(0, 0, 20, 20), 'B': local(180, 0, 200, 20)}
    e = Editor(w, tech)
    e.apply([Operation(action='create', uid='wire', shape=rect(20, 0, 180, 40))])
    assert check_connectivity(e.w, tech, intent(), pins)['status'] == 'pass'
    e.undo()
    assert check_connectivity(e.w, tech, intent(), pins)['status'] == 'fail'


def test_empty_intent_and_mismatched_process_are_incomplete(tech):
    w = workspace(tech, [rect(0, 0, 40, 40)])
    assert check_connectivity(w, tech, intent({}), {})['status'] == 'incomplete'
    altered = tech.model_copy(update={'native_fingerprint': 'other'})
    r = check_connectivity(w, altered, intent({'N': ['$A']}), {'A': local(0, 0, 20, 20)})
    assert r['status'] == 'incomplete'


def test_unmapped_instance_without_bbox_still_blocks_complete_coverage(tech):
    extra = Object(uid='missing', native_id='missing', kind='inst', placement=Placement(origin=(5000, 0)))
    w = workspace(tech, [rect(0, 0, 40, 40)], objects={'missing': extra})
    r = check_connectivity(w, tech, intent({'N': ['$A']}), {'A': local(0, 0, 20, 20)})
    assert r['status'] == 'incomplete'
    assert any(x['kind'] == 'incomplete_instance_cache' for x in r['coverage']['warnings'])


def test_collapsed_instance_cache_cannot_pass_from_pin_display(tech):
    w = instance_workspace(tech)
    display = json.loads(json.dumps(w.baseline.display))
    display['nodes']['master'][11].append(['collapsed', True])
    w = w.model_copy(update={'baseline': w.baseline.model_copy(update={'display': display})})
    r = check_connectivity(w, tech, intent({'N': ['M.D']}, {'M': 'mos'}), {})
    assert r['status'] == 'incomplete'


def test_unknown_cut_mapping_cannot_bridge_layers(tech):
    unknown = tech.model_copy(update={'vias': {'contact': tech.vias['contact']}})
    shapes = [rect(-100, -40, 100, 40), rect(-40, -100, 40, 100, 'M2'), rect(-20, -20, 20, 20, 'V1')]
    pins = {'A': local(-100, -20, -80, 20), 'B': local(-20, 80, 20, 100, 'M2')}
    r = check_connectivity(workspace(tech, shapes), unknown, intent(), pins)
    assert r['status'] == 'fail' and r['opens']
    assert any(x['kind'] == 'unknown_via_cut_mapping' for x in r['coverage']['warnings'])


def test_shape_net_intent_does_not_create_a_short(tech):
    w = workspace(tech, [rect(0, 0, 40, 40, net='VSS')])
    r = check_connectivity(w, tech, intent({'VDD': ['$A']}), {'A': local(0, 0, 20, 20, net='VDD')})
    assert r['status'] == 'pass'
    assert r['components'][0]['nets'] == ['VDD']


def test_local_pin_net_mismatch_disclosed(tech):
    w = workspace(tech, [rect(0, 0, 40, 40)])
    r = check_connectivity(w, tech, intent({'N': ['$A']}), {'A': local(0, 0, 20, 20, net='other')})
    assert r['status'] == 'incomplete'
    assert r['unresolved'][0]['reason'] == 'local_pin_net_mismatch'


def test_annotation_cannot_bridge_two_disconnected_metals(tech):
    w = workspace(tech, [rect(0, 0, 40, 40), rect(60, 0, 100, 40)])
    r = check_connectivity(w, tech, intent({'N': ['$A']}), {'A': local(0, 0, 100, 40)})
    assert r['status'] == 'fail'
    assert r['summary']['components'] == 2


def test_partial_pin_attachment_explains_contact_without_full_coverage(tech):
    # A 0.23 um wire crosses a 0.5 um square local port marker. The endpoint
    # touches the physical component, but still requires a full landing pad.
    w = workspace(tech, [rect(-100, 0, 600, 230)])
    pins = {'A': local(0, 0, 500, 500)}
    r = check_connectivity(w, tech, intent({'N': ['$A']}), pins)
    assert r['status'] == 'fail'
    assert r['opens'][0]['groups'][0]['endpoints'] == ['$A']
    assert r['opens'][0]['unconnected_endpoints'] == ['$A']
    issue = r['partial_attachments'][0]
    assert issue == dict(endpoint='$A', reason='partial_metal_coverage', covered_fraction=0.46,
                         missing_area_dbu2=135000.0, required_bbox=[[0, 0], [500, 500]],
                         layer='M1', lpp=['M1', 'drawing'])
    assert r['opens'][0]['partial_attachments'] == [issue]
    assert json.loads(json.dumps(r, allow_nan=False))['partial_attachments'] == [issue]
    # An actual physical pad completes the same endpoint without changing the
    # marker, net, or checker rules.
    e = Editor(w, tech)
    e.apply([Operation(action='create', uid='pad', shape=rect(0, 0, 500, 500))])
    complete = check_connectivity(e.w, tech, intent({'N': ['$A']}), pins)
    assert complete['status'] == 'pass' and complete['partial_attachments'] == []


def test_no_metal_attachment_reports_zero_coverage(tech):
    r = check_connectivity(workspace(tech), tech, intent({'N': ['$A']}), {'A': local(0, 0, 500, 500)})
    issue = r['partial_attachments'][0]
    assert r['status'] == 'fail'
    assert issue['reason'] == 'no_metal_contact'
    assert issue['covered_fraction'] == 0.0
    assert issue['missing_area_dbu2'] == 250000.0


def test_partial_attachment_ratio_is_not_rounded_to_a_pass(tech):
    # Keep the actual fraction rather than percentage rounding; even a small
    # missing edge remains a failure until it is physically covered.
    w = workspace(tech, [rect(0, 0, 1000000, 999998)])
    r = check_connectivity(w, tech, intent({'N': ['$A']}), {'A': local(0, 0, 1000000, 1000000)})
    issue = r['partial_attachments'][0]
    assert r['status'] == 'fail'
    assert issue['covered_fraction'] == 0.999998
    assert issue['missing_area_dbu2'] == 2000000.0
