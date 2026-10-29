import pytest
from colayout_lite.model import Object,Shape,Workspace,LiteError
from colayout_lite.editor import Editor
from colayout_lite.actions import availability
from colayout_lite.adapter import Adapter,verify
from tests_lite.test_kernel import profile,editor


def route_wire():
    return Object(uid='wire',native_id='id',kind='pathSeg',
        shape=Shape(kind='pathSeg',lpp=('wire_a','drawing'),points=((0,0),(2000,0)),width=200),
        attributes={'native_route':{'kind':'single_path_segment','status':'normal','net':'VDD','properties':None}})


def test_route_information_survives_local_edit_and_readback_is_strict(editor):
    obj=route_wire()
    editor.w=editor.w.model_copy(update={'baseline':editor.w.baseline.model_copy(update={'objects':{'wire':obj}})})
    editor.transform_shape('wire',delta=(2000,3000),orientation='R90')
    assert editor.object('wire').attributes==obj.attributes
    changed=editor.object('wire').model_copy(update={'attributes':{}})
    actual=editor.w.baseline.model_copy(update={'objects':{'wire':changed}})
    with pytest.raises(LiteError,match='READBACK_OBJECT_MISMATCH'):verify(editor.w,actual)
    copy=editor.copy_shape('wire',delta=(5000,0))
    assert not editor.object(copy).attributes


@pytest.mark.parametrize('reason',['native_route_locked','native_route_topology_requires_adapter'])
def test_specific_route_protections_are_visible_and_enforced(editor,reason):
    obj=route_wire().model_copy(update={'read_only_reason':reason})
    editor.w=editor.w.model_copy(update={'baseline':editor.w.baseline.model_copy(update={'objects':{'wire':obj}})})
    assert not availability('move',obj)[0]
    assert 'route' in availability('move',obj)[1]
    with pytest.raises(LiteError,match='OBJECT_READ_ONLY'):editor.edit('wire',width=400)


def setup_migration(editor,profile):
    old=route_wire().model_copy(update={'attributes':{},'read_only_reason':'native_relationship_requires_adapter'})
    baseline=editor.w.baseline.model_copy(update={'objects':{**editor.w.baseline.objects,'wire':old}})
    editor.w=editor.w.model_copy(update={'baseline':baseline})
    editor.place('inst',(2000,0))
    current=baseline.model_copy(update={'objects':{**baseline.objects,'wire':route_wire()}})
    adapter=object.__new__(Adapter);adapter.read=lambda *a:(current,profile);adapter.save=lambda w:None
    return adapter,current


def test_upgrade_preserves_unrelated_unsynced_instance_move(editor,profile):
    adapter,_=setup_migration(editor,profile)
    before=editor.w.operations
    w,p=adapter.upgrade_metadata(editor.w)
    assert w.operations==before and w.state=='editing'
    assert w.baseline.objects['wire'].read_only_reason is None
    assert w.baseline.objects['wire'].attributes['native_route']['net']=='VDD'
    assert Editor(w,p).object('inst').placement.origin==(2000,0)


def test_upgrade_never_overwrites_concurrent_native_geometry(editor,profile):
    adapter,current=setup_migration(editor,profile)
    wire=current.objects['wire'];wire=wire.model_copy(update={'shape':wire.shape.model_copy(update={'width':400})})
    current=current.model_copy(update={'objects':{**current.objects,'wire':wire}})
    adapter.read=lambda *a:(current,profile)
    before=editor.w.model_dump()
    with pytest.raises(LiteError,match='SOURCE_CONFLICT'):adapter.upgrade_metadata(editor.w)
    assert editor.w.model_dump()==before
