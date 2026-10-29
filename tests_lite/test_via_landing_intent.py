from copy import deepcopy
import pytest
from colayout_lite.editor import Editor, projected
from colayout_lite.local_models import LocalData, LocalPin
from colayout_lite.layout_helpers.service import execute
from colayout_lite.model import LiteError
from tests_lite.test_agent_connectivity import tech, workspace, rect
from tests_lite.test_auto_vias import via_rules


def equivalent(p):
    via = deepcopy(p.vias['V12'])
    via['defaults'].update(
        cutWidth=260, cutHeight=260, cutSpacing=[260, 260], layer1Enc=[60, 60], layer2Enc=[60, 60]
    )
    p = p.model_copy(update={'grid': 1, 'vias': {**p.vias, 'V12': via}})
    w = workspace(p, [rect(0, 0, 230, 920, 'M1', 'N'), rect(-2000, -10, 2000, 370, 'M2', 'N')])
    proof = LocalPin(id='proof', name='N', net='N', lpp=('M1', 'drawing'), bbox=((0, 0), (80, 80)))
    w = w.model_copy(update={'local_data': LocalData(pins={'proof': proof})})
    return Editor(w, p), via_rules(p)


def request(**extra):
    return {
        'bounds_um': [-0.075, -0.53, 0.305, 0.91],
        'start_layer': 'M1',
        'end_layer': 'M2',
        'net_intent': 'N',
        'targets': ['0', '1'],
        'allow_landing': True,
        **extra,
    }


def test_fit_target_keeps_two_cuts_and_reports_each_layer_extension(tech):
    e, rules = equivalent(tech)
    result = execute(e, 'create_auto_vias', request(), rules=rules)
    assert result['total_cuts'] == 2 and result['net_confirmed'] and result['used_landing']
    assert result['landing_reference']['target_id'] == '0'
    m1 = next(r for r in result['landing_changes'] if r['layer'] == 'M1')
    assert m1['extension_um'] == {'left': 0.075, 'right': 0.075, 'bottom': 0, 'top': 0}
    m2 = next(r for r in result['landing_changes'] if r['layer'] == 'M2')
    assert m2['basis_bounds_um'] == [-2, -0.01, 2, 0.37] and m2['extension_um']['top'] > 0
    again = execute(e, 'create_auto_vias', request(), rules=rules)
    assert again['reused_only'] and not again['used_landing'] and not again['created_uids']


def test_explicit_window_expansion_retains_dense_search_and_discloses_it(tech):
    e, rules = equivalent(tech)
    result = execute(e, 'create_auto_vias', request(landing_policy='expand_window'), rules=rules)
    assert result['total_cuts'] == 3
    m1 = next(r for r in result['landing_changes'] if r['layer'] == 'M1')
    assert m1['extension_um']['bottom'] > 0.5 and m1['physical_metal_basis']


def test_requested_count_never_overrides_fit_reference(tech):
    e, rules = equivalent(tech)
    before = e.w
    with pytest.raises(LiteError, match='AUTOVIA_NO_LEGAL_ARRAY'):
        execute(e, 'create_auto_vias', request(minimum_cuts=3), rules=rules)
    assert e.w is before


def test_virtual_port_is_not_existing_metal_and_new_layer_is_disclosed(tech):
    w = workspace(tech, [rect(0, 0, 1000, 200, 'M1', 'N')])
    pins = {
        layer: LocalPin(
            id='port-' + layer,
            name=layer,
            net='N',
            lpp=(layer, 'drawing'),
            bbox=((0, 0), (1000, 200)),
        )
        for layer in ('M1', 'M2')
    }
    w = w.model_copy(update={'local_data': LocalData(pins={p.id: p for p in pins.values()})})
    e = Editor(w, tech)
    args = {'bounds_um': [0, 0, 1, 0.2], 'start_layer': 'M1', 'end_layer': 'M2', 'net_intent': 'N'}
    with pytest.raises(LiteError, match='AUTOVIA_NET_UNRESOLVED'):
        execute(e, 'create_auto_vias', args, rules=via_rules(tech))
    assert e.w is w
    result = execute(
        e,
        'create_auto_vias',
        {**args, 'allow_landing': True, 'landing_policy': 'expand_window'},
        rules=via_rules(tech),
    )
    new_layer = next(r for r in result['added_metal_by_layer'] if r['layer'] == 'M2')
    assert result['used_landing'] and new_layer['added_outside_visible_metal_um2'] > 0
