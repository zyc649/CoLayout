import pytest
from colayout_lite.drc.local import run
from colayout_lite.drc.models import Region, Rule, DrcProfile
from tests_lite.test_agent_connectivity import tech, workspace, rect


@pytest.mark.parametrize(
    'layer,limit,gap', [('M1', 0.23, 180), ('M2', 0.28, 110), ('M3', 0.28, 97)]
)
def test_same_net_connected_fingers_have_local_notch_markers(tech, layer, limit, gap):
    tech = tech.model_copy(
        update={'layers': tech.layers + [dict(layer='M3', purpose='drawing', material='metal')]}
    )
    shapes = [
        rect(0, 0, 400, 2000, layer, 'N'),
        rect(400 + gap, 0, 800 + gap, 2000, layer, 'N'),
        rect(0, 0, 800 + gap, 400, layer, 'N'),
    ]
    roi = Region(bbox=((-100, -100), (3000, 3000)))
    rules = DrcProfile(
        id='test',
        technology_fingerprint=tech.native_fingerprint,
        rules=(Rule(id='space', kind='spacing', layer=layer, value=limit),),
    )
    result = run(workspace(tech, shapes), tech, rules, roi)
    assert len(result.markers) == 1
    marker = result.markers[0]
    assert marker.details['method'] == 'orthogonal_notch'
    assert marker.measured_um == pytest.approx(gap / 1000) and marker.required_um == limit
    fixed = workspace(tech, shapes + [rect(400, 400, 400 + gap, 2000, layer, 'N')])
    assert not run(fixed, tech, rules, roi).markers


@pytest.mark.parametrize('gap', [230, 280, 400])
def test_legal_connected_fingers_and_overlaps_do_not_report(tech, gap):
    shapes = [
        rect(0, 0, 400, 2000),
        rect(400 + gap, 0, 800 + gap, 2000),
        rect(0, 0, 800 + gap, 400),
        rect(200, 0, 400, 600),
    ]
    rules = DrcProfile(
        id='t',
        technology_fingerprint=tech.native_fingerprint,
        rules=(Rule(id='space', kind='spacing', layer='M1', value=0.23),),
    )
    assert not run(
        workspace(tech, shapes), tech, rules, Region(bbox=((-100, -100), (3000, 3000)))
    ).markers
