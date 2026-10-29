import pytest
from colayout_lite.human_edit import HumanEdit,rigid_matrix
from colayout_lite.editor import projected
from colayout_lite.geometry import box,point
from colayout_lite.model import Shape,LiteError
from colayout_lite.regions.actions import RegionActions
from colayout_lite.document import save_document,load_document
from colayout_lite.routing_policy import blocked_layers,set_blocked_layers
from tests_lite.test_regions import region_editor,profile


def hierarchy(e):
    api=RegionActions(e);left=api.create((-1000,-1000,7000,7000));api.seal(left)
    right=api.create((11000,-1000,19000,7000));api.seal(right)
    parent=api.create((-2000,-2000,21000,9000));api.seal(parent)
    return left,right,parent


def test_rigid_nested_module_move_rotate_mirror_undo(region_editor,tmp_path):
    e=region_editor;left,right,parent=hierarchy(e);api=HumanEdit(e);before=e.w
    api.transform([parent],delta=(2000,1000))
    assert projected(e.w)['object-A'].placement.origin==(2000,1000)
    assert e.w.local_data.regions[left].bbox==box(before.local_data.regions[left].bbox,(1,0,0,1,2000,1000))
    for pid,pin in before.local_data.regions[left].pins.items():
        assert e.w.local_data.regions[left].pins[pid].bbox==box(pin.bbox,(1,0,0,1,2000,1000))
    e.undo();assert e.w.local_data==before.local_data and e.w.operations==before.operations
    api.transform([parent],orientation='R90');assert projected(e.w)['object-A'].placement.orientation=='R90'
    assert projected(e.w)['object-A'].attributes==before.baseline.objects['object-A'].attributes
    save_document(tmp_path/'rotated.json',e.w,e.profile);loaded,p=load_document(tmp_path/'rotated.json');assert loaded.local_data==e.w.local_data
    e.undo();api.transform([parent],orientation='MY');assert projected(e.w)['object-A'].placement.orientation=='MY'
    e.undo();assert e.w.local_data==before.local_data


def test_gui_permissions_and_atomic_refusal(region_editor):
    e=region_editor;left,right,parent=hierarchy(e);before=e.w
    with pytest.raises(LiteError,match='SCOPE'):HumanEdit(e).transform(['object-A'],delta=(100,0))
    with pytest.raises(LiteError,match='DELETE_NOT_ALLOWED'):HumanEdit(e).delete([parent])
    e.scope_id=left
    with pytest.raises(LiteError,match='DELETE_NOT_ALLOWED'):HumanEdit(e).delete(['object-A'])
    uid=e.create(Shape(kind='rect',lpp=('wire_a','drawing'),bbox=((2000,3000),(3000,4000)),net_intent='N'))
    with pytest.raises(LiteError,match='TRANSFORM_NOT_ALLOWED'):HumanEdit(e).transform([uid],orientation='R90')
    HumanEdit(e).transform([uid],delta=(100,0));HumanEdit(e).delete([uid]);assert uid not in projected(e.w)
    e.scope_id=None;e.w=before
    objects={**before.baseline.objects,'object-B':before.baseline.objects['object-B'].model_copy(update={'read_only_reason':'locked'})}
    e.w=e.w.model_copy(update={'baseline':before.baseline.model_copy(update={'objects':objects})});snapshot=e.w
    with pytest.raises(LiteError,match='READ_ONLY'):HumanEdit(e).transform([parent],delta=(1000,0))
    assert e.w==snapshot


def test_human_can_adjust_sealed_local_pin_from_parent_or_inside(region_editor):
    e=region_editor;left,right,parent=hierarchy(e);r=e.w.local_data.regions[left];pin=next(iter(r.pins.values()))
    e.scope_id=parent;HumanEdit(e).adjust_pin(left,pin.id,0,5000)
    moved=e.w.local_data.regions[left];assert moved.state=='sealed' and moved.interface_revision==1
    assert sum(v[1] for v in moved.pins[pin.id].bbox)/2==5000
    e.scope_id=left;HumanEdit(e).adjust_pin(left,pin.id,-1000,4500)
    assert sum(v[0] for v in e.w.local_data.regions[left].pins[pin.id].bbox)/2==-1000
    e.scope_id=None
    with pytest.raises(LiteError,match='SCOPE'):HumanEdit(e).adjust_pin(left,pin.id,0,0)
    with pytest.raises(LiteError):HumanEdit(e).adjust_pin('object-A','D',0,0)


def test_three_policy_kinds_persist_independently(region_editor,tmp_path):
    e=region_editor;left,_,_=hierarchy(e);a=RegionActions(e)
    keep=a.add_keepout((24000,3000,25000,4000))
    layout=e.w.layout_connectivity;e.w=e.w.model_copy(update={'layout_connectivity':layout.model_copy(update={'instances':{
        **layout.instances,'object-D':layout.instances['object-D'].model_copy(update={'black_box':True})}})})
    assert set(blocked_layers(e.w,e.profile,'keepout',keep))=={'wire_a','wire_b'}
    set_blocked_layers(e,'keepout',keep,[]);set_blocked_layers(e,'area',left,['wire_b']);set_blocked_layers(e,'native','object-D',['wire_a'])
    assert blocked_layers(e.w,e.profile,'keepout',keep)==()
    assert blocked_layers(e.w,e.profile,'area',left)==('wire_b',)
    path=tmp_path/'policy.json';save_document(path,e.w,e.profile);w,p=load_document(path)
    assert blocked_layers(w,p,'native','object-D')==('wire_a',)
    assert blocked_layers(w,p,'keepout',keep)==()


def test_container_proof_cannot_move_only_the_frame(region_editor):
    from colayout_lite.human_edit import transform_local
    e=region_editor;left,right,parent=hierarchy(e);before=e.w
    local=transform_local(e.w.local_data,parent,(1,0,0,1,1000,0))
    with pytest.raises(LiteError,match='INVALID_REGION_TRANSFORM'):
        e._publish(e.w.model_copy(update={'local_data':local}),region_transforms={parent:((1000,0),'R0',(0,0))})
    assert e.w==before


def test_region_overlap_or_missing_pin_is_atomic(region_editor):
    e=region_editor;left,right,parent=hierarchy(e);e.scope_id=parent;before=e.w
    with pytest.raises(LiteError):HumanEdit(e).transform([left],delta=(10000,0))
    assert e.w==before
    with pytest.raises(LiteError):HumanEdit(e).adjust_pin(left,'missing',0,0)
    assert e.w==before
