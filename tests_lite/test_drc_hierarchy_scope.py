"""Ordinary leaf devices are checked; only genuine hierarchy is opaque."""

from copy import deepcopy

import pytest

from colayout_lite.circuit.models import LayoutConnectivity, LayoutInstance, ViewRef
from colayout_lite.drc.blackboxes import server_scope
from colayout_lite.drc.local import run
from colayout_lite.drc.models import DrcProfile, Region, Rule
from colayout_lite.drc.scope import selection
from colayout_lite.hierarchy import is_hierarchical_instance
from colayout_lite.model import Object, Placement
from colayout_lite.scene import figures_by_owner
from tests_lite.test_agent_connectivity import tech, workspace


def with_native_module(w, uid='native'):
    """Imported connectivity evidence for a module with an opaque cache."""
    return w.model_copy(
        update={
            'layout_connectivity': LayoutConnectivity(
                source=ViewRef(library='L', cell='C', view='layout', session='s', counter='1'),
                instances={
                    uid: LayoutInstance(
                        uid=uid,
                        name='wrapped_device',
                        master=('L', 'wrapped_n18', 'layout'),
                        terminals={},
                        black_box=True,
                    )
                },
                ports={},
            )
        }
    )


def device_fixture(p, kind='inst', nested=False):
    def node(key, figures=(), children=()):
        return [
            key,
            'PDK',
            'n18_ckt',
            'layout',
            '1000',
            [[0, 0], [1000, 1000]],
            [],
            [],
            [],
            list(figures),
            list(children),
        ]

    def figure(uid, layer, bounds):
        return [uid, uid, False, None, 'rect', layer + '/drawing', bounds, None]

    leaf = node(
        'leaf',
        [
            figure('a', 'M1', [[0, 0], [80, 1000]]),
            figure('b', 'M1', [[160, 0], [240, 1000]]),
            figure('cut', 'V1', [[500, 500], [540, 540]]),
        ],
    )
    master = 'module' if nested else 'leaf'
    nodes = {
        'leaf': leaf,
        'module': node('module', children=[['child', 'leaf', 'inst', [0, 0], 'R0', '1']]),
        'root': node('root', children=[['i', master, kind, [0, 0], 'R0', '1']]),
    }
    styles = [
        [
            layer + '/drawing',
            [[layer, 'drawing'], layer, 1, True, material, None, None, None, None, None],
        ]
        for layer, material in [('M1', 'metal'), ('V1', 'cut')]
    ]
    obj = Object(
        uid='i',
        native_id='i',
        kind=kind,
        bbox=((0, 0), (1000, 1000)),
        placement=Placement(origin=(0, 0)),
        attributes={'master_key': master},
    )
    return workspace(
        p, objects={'i': obj}, display={'root': 'root', 'nodes': nodes, 'styles': styles}
    )


@pytest.mark.parametrize('kind', ['inst', 'mosaic'])
@pytest.mark.parametrize('nested', [False, True])
def test_server_scope_matches_automatic_canvas_hierarchy(tech, kind, nested):
    w = device_fixture(tech, kind, nested)
    roi = Region(bbox=((-100, -100), (1500, 1500)))
    figures, _ = figures_by_owner(w.baseline)
    assert any(f.get('interface') for f in figures['i']) is nested
    assert is_hierarchical_instance(w, w.baseline.objects['i']) is nested
    windows, scope = server_scope(w, tech, roi, None)
    assert windows == ([[0, 0, 1, 1]] if nested else [])
    assert scope['native_instances_excluded'] == int(nested)
    assert scope['ordinary_instances_included'] == int(not nested)
    # Presentation overrides do not turn an ordinary PCell into hierarchy.
    w = w.model_copy(update={'instance_display': {'i': 'full' if nested else 'box_pins'}})
    assert server_scope(w, tech, roi, None)[0] == windows


def test_leaf_width_spacing_and_cut_enclosure_are_checked(tech):
    roi = Region(bbox=((-100, -100), (1500, 1500)))
    rules = DrcProfile(
        id='test',
        technology_fingerprint=tech.native_fingerprint,
        rules=(
            Rule(id='width', kind='width', layer='M1', value=0.2),
            Rule(id='spacing', kind='spacing', layer='M1', value=0.2),
            Rule(id='enclosure', kind='enclosure', layer='V1', other_layer='M1', value=0.02),
        ),
    )
    result = run(device_fixture(tech), tech, rules, roi, scope_id=None)
    assert {m.rule_id for m in result.markers} == {'width', 'spacing', 'enclosure'}
    assert result.coverage['complete_for_configured_subset']
    opaque = run(device_fixture(tech, nested=True), tech, rules, roi, scope_id=None)
    assert not opaque.markers and not opaque.coverage['warnings']


def test_missing_cache_never_becomes_an_automatic_waiver(tech):
    w = device_fixture(tech)
    w = w.model_copy(update={'baseline': w.baseline.model_copy(update={'display': {}})})
    roi = Region(bbox=((-100, -100), (1500, 1500)))
    assert server_scope(w, tech, roi, None)[0] == []
    result = run(
        w,
        tech,
        DrcProfile(
            id='t',
            technology_fingerprint=tech.native_fingerprint,
            rules=(Rule(id='width', kind='width', layer='M1', value=0.2),),
        ),
        roi,
    )
    assert result.coverage['warnings'] and not result.coverage['complete_for_configured_subset']
    # An opaque cache may still have explicit imported connectivity evidence.
    assert selection(with_native_module(w, 'i'), roi)[1]['native_instance_ids'] == ['i']


def test_hierarchy_classification_changes_invalidate_result_but_peeking_does_not(tech):
    w = device_fixture(tech)
    roi = Region(bbox=((-100, -100), (1500, 1500)))
    p = DrcProfile(id='t', technology_fingerprint=tech.native_fingerprint)
    result = run(w, tech, p, roi)
    assert result.is_current(w, p)
    assert result.is_current(w.model_copy(update={'instance_display': {'i': 'box_pins'}}), p)
    display = deepcopy(w.baseline.display)
    display['nodes']['leaf'].append([['child_count', 1], ['collapsed', True]])
    changed = w.model_copy(update={'baseline': w.baseline.model_copy(update={'display': display})})
    assert not result.is_current(changed, p)
    old_scope = dict(result.coverage['scope'])
    old_scope.pop('selection_policy')
    old = result.model_copy(update={'coverage': {**result.coverage, 'scope': old_scope}})
    assert not old.is_current(w, p)
