import json
import random
from pathlib import Path
import pytest
from pydantic import ValidationError
from colayout_lite.model import Shape, Placement, Object, Snapshot, Workspace, Operation, LiteError, digest
from colayout_lite.editor import Editor, projected
from colayout_lite.geometry import ORIENT,transform,point,compose,transform_shape,via_figures
from colayout_lite.technology import TechnologyProfile
from colayout_lite.transport import skill


@pytest.fixture
def profile():
    return TechnologyProfile(id='foreign',label='Synthetic technology',native_fingerprint='fp',dbu_per_micron=2000,grid=2,
        writable_lpps=(('wire_a','drawing'),('wire_b','drawing')),layers=[dict(layer=n,purpose='drawing',material='metal') for n in ['wire_a','wire_b']],
        vias={'JOIN':dict(kind='stdViaDef',layer1='wire_a',layer2='wire_b',cut_layer='cut_x',implant1=None,implant2=None,
            defaults=dict(cutWidth=200,cutHeight=240,cutRows=1,cutColumns=1,cutSpacing=[200,220],layer1Enc=[80,100],layer2Enc=[100,120],layer1Offset=[0,0],layer2Offset=[0,0],originOffset=[0,0]))})


@pytest.fixture
def editor(profile):
    inst=Object(uid='inst',native_id='old',kind='inst',placement=Placement(origin=(0,0)),attributes={'master':['other','device','layout']})
    snap=Snapshot(library='L',cell='C',library_path='/test/L',session='s',counter='1',dirty=False,dbu_per_micron=2000,grid=2,objects={'inst':inst},technology_fingerprint='fp')
    return Editor(Workspace(baseline=snap,profile_id=profile.id),profile)


@pytest.mark.parametrize('bad',[1.0,True,'1',2**31,float('nan')])
def test_edit_coordinates_never_silently_coerce(bad):
    with pytest.raises((ValidationError,ValueError)):
        Shape(kind='rect',lpp=('wire_a','drawing'),bbox=((bad,0),(20,20)))


@pytest.mark.parametrize('points',[[[0,0],[100,100],[200,0]],[[0,0],[100,0],[100,100]],[[0,0],[-100,-100]]])
def test_orthogonal_and_diagonal_path(points):
    assert Shape(kind='path',lpp=('wire_a','drawing'),points=points,width=20)


@pytest.mark.parametrize('points',[[[0,0],[100,50]],[[0,0],[0,0]],[[0,0]]])
def test_bad_path_rejected(points):
    with pytest.raises(ValidationError):Shape(kind='path',lpp=('wire_a','drawing'),points=points,width=20)


@pytest.mark.parametrize('points',[[[0,0],[100,100],[0,100],[100,0]],[[0,0],[20,0],[40,0]],[[0,0],[20,0],[20,20],[0,0]]])
def test_invalid_polygon(points):
    with pytest.raises(ValidationError):Shape(kind='polygon',lpp=('wire_a','drawing'),points=points)


@pytest.mark.parametrize('orientation',list(ORIENT))
def test_transform_inverse_property(orientation):
    t=transform((246,-388),orientation);a,b,c,d,x,y=t
    inv=(a,c,b,d,-a*x-c*y,-b*x-d*y)
    rng=random.Random(193)
    for _ in range(100):
        p=(rng.randrange(-100000,100000),rng.randrange(-100000,100000))
        assert point(point(p,t),inv)==p


def test_diagonal_pathseg_requires_explicit_native_width_basis():
    with pytest.raises(ValidationError):Shape(kind='pathSeg',lpp=('wire_a','drawing'),points=((0,0),(1000,1000)),width=400)
    s=Shape(kind='pathSeg',lpp=('wire_a','drawing'),points=((0,0),(1000,1000)),width=400,width_basis='oa_diagonal')
    assert s.width==400


def test_geometry_batches_are_atomic(editor):
    first=Operation(action='create',uid='r',shape=Shape(kind='rect',lpp=('wire_a','drawing'),bbox=((0,0),(20,20))))
    forbidden=Operation(action='delete',uid='inst',before=digest(projected(editor.w)['inst'].semantic()))
    before=editor.w.model_dump_json()
    with pytest.raises(LiteError,match='INSTANCE'):editor.apply([first,forbidden])
    assert editor.w.model_dump_json()==before


def test_local_delta_and_undo_do_not_require_transport(editor):
    uid=editor.create(Shape(kind='rect',lpp=('wire_a','drawing'),bbox=((0,0),(20,20))))
    editor.edit(uid,bbox=((0,0),(40,20)))
    assert len(editor.w.operations)==1 and editor.w.operations[0].action=='create'
    editor.delete(uid);assert not editor.w.operations
    editor.undo();assert projected(editor.w)[uid].shape.bbox[1][0]==40
    editor.redo();assert uid not in projected(editor.w)


def test_via_partial_update_preserves_other_parameters(editor):
    uid=editor.create(Shape(kind='stdVia',origin=(0,0),via_definition='JOIN',via_parameters={'layer1Offset':[40,60]}))
    editor.edit(uid,via_parameters={'cutRows':3})
    s=projected(editor.w)[uid].shape
    assert s.via_parameters['layer1Offset']==[40,60] and s.via_parameters['cutRows']==3
    editor.reset_via_parameters(uid,['layer1Offset'])
    assert projected(editor.w)[uid].shape.via_parameters['layer1Offset']==[0,0]


@pytest.mark.parametrize('changes',[{'cutRows':0},{'cutRows':True},{'cutRows':65},{'cutWidth':0},{'cutSpacing':[-1,0]},{'invented':20}])
def test_bad_via_parameters(changes):
    with pytest.raises(ValidationError):Shape(kind='stdVia',origin=(0,0),via_definition='JOIN',via_parameters=changes)


def test_instance_only_placement(editor):
    editor.place('inst',(20,40),'MY')
    assert projected(editor.w)['inst'].attributes['master']==['other','device','layout']
    with pytest.raises(LiteError):editor.copy_shape('inst')
    with pytest.raises(LiteError):editor.delete('inst')


def test_revision_and_recovery_gate(editor):
    with pytest.raises(LiteError,match='STALE_REVISION'):editor.apply([],expected_revision=100)
    editor.w=editor.w.model_copy(update={'state':'indeterminate'})
    with pytest.raises(LiteError,match='RECOVERY'):editor.place('inst',(20,20))


def test_foreign_profile_grid_and_layer(editor,profile):
    with pytest.raises(LiteError,match='OFF_GRID'):editor.create(Shape(kind='rect',lpp=('wire_a','drawing'),bbox=((1,0),(20,20))))
    with pytest.raises(LiteError,match='LAYER'):editor.create(Shape(kind='rect',lpp=('M1','drawing'),bbox=((0,0),(20,20))))
    with pytest.raises(LiteError,match='TECHNOLOGY'):Editor(editor.w,profile.model_copy(update={'native_fingerprint':'other'}))


def test_serialization_roundtrip(editor,tmp_path):
    editor.place('inst',(-100,220),'R90');p=tmp_path/'state.json';editor.w.save(p)
    assert Workspace.model_validate_json(p.read_text())==editor.w


def test_skill_data_encoding_escapes_code():
    assert skill({'text':'"\n(load "bad")'})=='list(list("text" "\\\"\\n(load \\\"bad\\\")"))'
    with pytest.raises(TypeError):skill(0.1)


def test_no_old_runtime_or_schematic_dependencies():
    import ast
    for p in Path('colayout_lite').glob('*.py'):
        tree=ast.parse(p.read_text(encoding='utf-8'))
        for n in ast.walk(tree):
            if isinstance(n,ast.ImportFrom):assert not (n.module or '').startswith(('colayout.','paired'))
    for p in Path('colayout_lite/skill').glob('*.il'):
        text=p.read_text(encoding='utf-8')
        for forbidden in ['schCreate','schCheck','bndReplace','coPair','cdfUpdateInstParam','lceExtract']:
            assert forbidden not in text
        if 'lxSetConnRef' in text:
            # The paired-copy operation may preserve its source reference,
            # but no ordinary write/read operation may rebind an existing view.
            assert p.name=='circuit.il'
            helper=text.split('procedure(lcClonePaired(',1)[1].split('\nprocedure(',1)[0]
            assert text.count('lxSetConnRef(')==helper.count('lxSetConnRef(')==1
            assert helper.index('ltClone(')<helper.index('lxSetConnRef(')


@pytest.mark.parametrize('changes',[{'style':'roundRound'},{'begin_extension':10},{'end_style':'extend'},
    {'width_basis':'oa_diagonal'},{'orientation':'R90'},{'points':((0,0),(20,20))},{'width':20}])
def test_irrelevant_fields_cannot_be_silently_dropped(changes):
    with pytest.raises(ValidationError):Shape(kind='rect',lpp=('wire_a','drawing'),bbox=((0,0),(20,20)),**changes)


def test_opaque_bbox_participates_in_source_conflict_signature():
    o=Object(uid='ellipse',native_id='id',kind='ellipse',bbox=((0,0),(10,20)),read_only_reason='opaque')
    assert o.semantic()!=o.model_copy(update={'bbox':((0,0),(20,20))}).semantic()


def test_pathseg_extend_native_extension_is_zero():
    s=Shape(kind='pathSeg',lpp=('wire_a','drawing'),points=((0,0),(100,0)),width=20,end_style='extend')
    assert s.end_extension==0
    with pytest.raises(ValidationError):Shape.model_validate({**s.model_dump(),'end_extension':10})


def test_discard_and_restore_draft(editor):
    uid=editor.create(Shape(kind='rect',lpp=('wire_a','drawing'),bbox=((0,0),(20,20))))
    editor.discard();assert uid not in projected(editor.w)
    editor.undo();assert uid in projected(editor.w)


def test_batch_conflict_does_not_publish_partial_edit(editor):
    o=projected(editor.w)['inst'];before=editor.w.model_dump_json()
    move=Operation(action='transform',uid='inst',before=digest(o.semantic()),placement=Placement(origin=(20,20)))
    stale=Operation(action='transform',uid='inst',before='old-digest',placement=Placement(origin=(40,20)))
    with pytest.raises(LiteError,match='OBJECT_CONFLICT'):editor.apply([move,stale])
    assert editor.w.model_dump_json()==before


def test_empty_net_intent_is_explicit_clear():
    s=Shape(kind='rect',lpp=('wire_a','drawing'),bbox=((0,0),(20,20)),net_intent='')
    assert s.net_intent is None
