"""Shared tightening reserves a small PIN-sized channel without moving content."""
import pytest

from colayout_lite.editor import Editor
from colayout_lite.frame_edit import FrameEdit
from colayout_lite.agent_tools.session import AgentSession
from colayout_lite.regions.actions import RegionActions
from tests_lite.test_regions import region_editor, profile


def setup_region(e,mode='fixed',width=200,height=400):
    rid=RegionActions(e).create((-1000,-1000,7000,7000),'region')
    row=e.w.local_data.regions[rid]
    pins={}
    for i,(pid,p) in enumerate(row.pins.items()):
        cy=1000+i*1000
        pins[pid]=p.model_copy(update={'bbox':((-1000-width//2,cy-height//2),(-1000+width//2,cy+height//2))})
    local=e.w.local_data.model_copy(update={'regions':{**e.w.local_data.regions,rid:row.model_copy(update={'pins':pins,'pin_mode':mode})}})
    e.w=e.w.model_copy(update={'local_data':local})
    return rid


@pytest.mark.parametrize('mode',['fixed','directional'])
def test_clearance_scales_per_axis_and_preserves_content_and_undo(region_editor,mode):
    e=region_editor;rid=setup_region(e,mode);before=e.w
    result=FrameEdit(e).tighten(rid)
    row=e.w.local_data.regions[rid]
    assert row.bbox==((-120,-240),(6120,2240))
    assert result['pin_clearance_um']==[120/e.profile.dbu_per_micron,240/e.profile.dbu_per_micron]
    assert row.pin_mode==mode and row.object_uids==before.local_data.regions[rid].object_uids
    assert set(row.pins)==set(before.local_data.regions[rid].pins)
    assert e.w.operations==before.operations and e.w.baseline is before.baseline
    assert all(v%e.profile.grid==0 for point in row.bbox for v in point)
    e.undo();assert e.w.local_data==before.local_data
    e.redo();assert e.w.local_data.regions[rid].bbox==row.bbox


def test_api_and_human_tighten_use_identical_geometry(region_editor,tmp_path):
    human=region_editor;rid=setup_region(human)
    agent=Editor(human.w,human.profile)
    FrameEdit(human).tighten(rid,padding=100)
    session=AgentSession(agent,None,tmp_path/'agent')
    try:
        token=session.invoke('claim_region',{'region_id':rid,'agent_name':'agent'},client_id='agent')['result']['session_token']
        result=session.invoke('edit_region',{'session_token':token,'expected_revision':agent.w.revision,
            'operations':[{'action':'tighten_region','params':{'padding_um':100/agent.profile.dbu_per_micron}}]},client_id='agent')
        assert result['ok'],result
        assert agent.w.local_data==human.w.local_data
        assert agent.w.operations==human.w.operations
    finally:session.close()


def test_already_tight_frame_never_expands_or_adds_a_warning(region_editor):
    e=region_editor;rid=setup_region(e,width=20000,height=20000)
    before=e.w
    result=FrameEdit(e).tighten(rid)
    assert not result['changed'] and e.w is before
    assert 'warnings' not in result and 'clearance_limited' not in result


def test_direct_child_pin_outer_half_is_included(region_editor):
    e=region_editor;child=setup_region(e)
    parent=RegionActions(e).create((-3000,-3000,10000,10000),'parent')
    old_child=e.w.local_data.regions[child]
    result=FrameEdit(e).tighten(parent)
    box=e.w.local_data.regions[parent].bbox
    assert box[0][0]<min(p.bbox[0][0] for p in old_child.pins.values())
    assert e.w.local_data.regions[child]==old_child
    assert not result['native_geometry_changed']


def test_small_pin_extra_is_at_least_one_grid_and_explicit_padding_adds(region_editor):
    e=region_editor;rid=setup_region(e,width=4,height=4)
    FrameEdit(e).tighten(rid,padding=6)
    assert e.w.local_data.regions[rid].bbox==((-10,-10),(6010,2010))


def test_no_pins_keeps_content_only_tightening(region_editor):
    e=region_editor
    e.w=e.w.model_copy(update={'circuit':e.w.circuit.model_copy(update={'ports':{}})})
    rid=RegionActions(e).create((-1000,-1000,20000,7000),'all objects')
    assert not e.w.local_data.regions[rid].pins
    result=FrameEdit(e).tighten(rid)
    assert result['pin_clearance_um']==[0,0]
    assert e.w.local_data.regions[rid].bbox==((0,0),(18000,2000))
