"""L1 tests assert requested meaning, not merely that an operation exists."""
import math
import pytest
from tests_lite.test_kernel import profile,editor
from colayout_lite.actions import Actions,availability
from colayout_lite.editor import projected
from colayout_lite.model import Shape,LiteError


def test_90_route_honors_every_vertex_and_width(editor):
    result=Actions(editor).execute('create_path90',{'points':[[1,2],[7,2],[7,11]],'width':.6,'lpp':['wire_b','drawing']})
    shape=projected(editor.w)[result.uid].shape
    assert shape.points==((2000,4000),(14000,4000),(14000,22000))
    assert shape.width==1200 and shape.lpp==('wire_b','drawing')
    assert all(a[0]==b[0] or a[1]==b[1] for a,b in zip(shape.points,shape.points[1:]))


def test_90_rejects_diagonal_instead_of_silently_accepting(editor):
    before=editor.w.model_dump_json()
    with pytest.raises(LiteError,match='ORTHOGONAL'):
        Actions(editor).execute('create_path90',{'points':[[1,2],[7,2],[11,6]],'width':.6,'lpp':['wire_a','drawing']})
    assert editor.w.model_dump_json()==before


def test_45_route_contains_requested_diagonal(editor):
    r=Actions(editor).execute('create_path45',{'points':[[1,2],[7,8],[10,8]],'width':.4,'lpp':['wire_a','drawing']})
    assert projected(editor.w)[r.uid].shape.points==((2000,4000),(14000,16000),(20000,16000))


@pytest.mark.parametrize('position',[(0,0),(-4.25,3.5),(123.5,-67.25)])
def test_rectangle_creation_uses_position_and_size(editor,position):
    x,y=position;r=Actions(editor).execute('create_rect',dict(x=x,y=y,width=4.5,height=2.75,lpp=['wire_b','drawing']))
    assert projected(editor.w)[r.uid].shape.bbox==((int(x*2000),int(y*2000)),(int((x+4.5)*2000),int((y+2.75)*2000)))


@pytest.mark.parametrize('kind',['inst','rect','polygon','path','stdVia'])
def test_move_two_times_accumulates_requested_delta(editor,kind):
    if kind=='inst':uid='inst'
    else:
        specs={'rect':dict(bbox=((0,0),(2000,4000))), 'polygon':dict(points=((0,0),(2000,0),(1000,2000))),
               'path':dict(points=((0,0),(2000,0)),width=200), 'stdVia':dict(origin=(0,0),via_definition='JOIN')}
        uid=editor.create(Shape(kind=kind,**({'lpp':('wire_a','drawing')} if kind!='stdVia' else {}),**specs[kind]))
    a=Actions(editor)
    for _ in range(2):a.execute('move',dict(dx=1.5,dy=-2),uid)
    obj=projected(editor.w)[uid]
    if kind=='inst':origin=obj.placement.origin
    elif kind=='stdVia':origin=obj.shape.origin
    elif kind=='rect':origin=obj.shape.bbox[0]
    else:origin=obj.shape.points[0]
    assert origin==(6000,-8000)


def test_rotate_instance_is_relative_on_every_click(editor):
    a=Actions(editor)
    for expected in ['R90','R180','R270','R0']:
        result=a.execute('rotate',{'degrees':90},'inst')
        assert projected(editor.w)['inst'].placement.orientation==expected
        assert result.changed


@pytest.mark.parametrize('kind',['rect','polygon','path','stdVia'])
def test_rotate_shapes_repeatedly_is_not_instance_only(editor,kind):
    data={'rect':dict(bbox=((2000,0),(4000,2000))),'polygon':dict(points=((2000,0),(4000,0),(3000,2000))),
          'path':dict(points=((2000,0),(4000,0)),width=400),'stdVia':dict(origin=(2000,0),via_definition='JOIN')}
    uid=editor.create(Shape(kind=kind,**({'lpp':('wire_a','drawing')} if kind!='stdVia' else {}),**data[kind]));original=projected(editor.w)[uid].shape
    for _ in range(4):Actions(editor).execute('rotate',{'degrees':90,'pivot':[0,0]},uid)
    assert projected(editor.w)[uid].shape==original


def test_physical_width_and_noop_feedback(editor):
    uid=editor.create(Shape(kind='path',lpp=('wire_a','drawing'),points=((0,0),(2000,0)),width=400))
    a=Actions(editor);a.execute('set_width',{'width':1.2},uid)
    assert projected(editor.w)[uid].shape.width==2400
    revision=editor.w.revision;result=a.execute('set_width',{'width':1.2},uid)
    assert not result.changed and editor.w.revision==revision and '相同' in result.message


def test_diagonal_pathseg_physical_width_is_converted_explicitly(editor):
    uid=editor.create(Shape(kind='pathSeg',lpp=('wire_a','drawing'),points=((0,0),(2000,2000)),width=400,width_basis='oa_diagonal'))
    r=Actions(editor).execute('set_width',{'width':1},uid);actual=projected(editor.w)[uid].shape.width
    assert actual==2828 and abs(actual/math.sqrt(2)/2000-1)<.001
    assert '原生 2828 DBU' in r.after


@pytest.mark.parametrize('action',['move','rotate','set_width','delete','copy'])
def test_missing_selection_is_an_explained_error(editor,action):
    params={'move':{'dx':1,'dy':0},'rotate':{'degrees':90},'set_width':{'width':1},'delete':{},'copy':{'dx':1,'dy':0}}[action]
    with pytest.raises(LiteError,match='先在画布'):Actions(editor).execute(action,params,None)


def test_via_cannot_be_misused_as_wire_width(editor):
    uid=Actions(editor).execute('create_via',dict(x=12,y=-3,definition='JOIN',via_parameters={'cutRows':3,'cutColumns':4})).uid
    shape=projected(editor.w)[uid].shape
    assert shape.origin==(24000,-6000) and shape.via_parameters['cutRows']==3 and shape.via_parameters['cutColumns']==4
    allowed,reason=availability('set_width',projected(editor.w)[uid]);assert not allowed and '标准过孔' in reason
    with pytest.raises(LiteError,match='ACTION_NOT_APPLICABLE'):Actions(editor).execute('set_width',{'width':1},uid)


def test_deleted_selection_is_not_reused(editor):
    uid=Actions(editor).execute('create_rect',dict(x=0,y=0,width=2,height=3,lpp=['wire_a','drawing'])).uid
    Actions(editor).execute('delete',{},uid)
    with pytest.raises(LiteError,match='ACTION_NOT_APPLICABLE'):Actions(editor).execute('delete',{},uid)


def test_no_ignored_parameters(editor):
    with pytest.raises(LiteError,match='UNKNOWN_ARGUMENT'):
        Actions(editor).execute('create_rect',dict(x=0,y=0,width=2,height=3,lpp=['wire_a','drawing'],foo=3))
    with pytest.raises(LiteError,match='MISSING_ARGUMENT'):Actions(editor).execute('create_rect',{'width':2})


def test_new_native_baseline_is_an_undo_boundary(editor):
    Actions(editor).execute('move',dict(dx=1,dy=0),'inst')
    acknowledged=editor.w.model_copy(update={'baseline':editor.w.baseline.model_copy(update={'objects':projected(editor.w)}),'operations':(),'state':'clean'})
    editor.w=acknowledged;editor.undo()
    assert editor.w is acknowledged and editor.w.baseline.objects['inst'].placement.origin==(2000,0)


def test_edit_rect_and_polygon_use_requested_coordinates(editor):
    a=Actions(editor);uid=a.execute('create_rect',dict(x=0,y=0,width=2,height=3,lpp=['wire_a','drawing'])).uid
    a.execute('edit_rect',dict(x=-1,y=2,width=6,height=8,lpp=['wire_b','drawing']),uid)
    assert projected(editor.w)[uid].shape.bbox==((-2000,4000),(10000,20000))
    uid=a.execute('create_polygon',dict(points=[[0,0],[2,0],[1,2]],lpp=['wire_a','drawing'])).uid
    a.execute('edit_polygon',dict(points=[[0,0],[4,0],[4,3],[0,3]],lpp=['wire_b','drawing']),uid)
    assert projected(editor.w)[uid].shape.points==((0,0),(8000,0),(8000,6000),(0,6000))
