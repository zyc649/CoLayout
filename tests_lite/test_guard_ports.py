"""Guard interfaces identify actual metal and never connect islands by name."""
from copy import deepcopy
import pytest
from shapely.geometry import box,Point
from colayout_lite.model import Object,MultipartPath,Placement,Shape,Operation,LiteError
from colayout_lite.inspection_data import scope_pins,build_scope_graph
from colayout_lite.drc.geometry import Physical
from colayout_lite.net_selection import select_net
from colayout_lite.regions.models import OperationRegion
from colayout_lite.guard_ports import required_net
from tests_lite.test_agent_connectivity import tech,workspace


def guards(tech,monkeypatch,names=('VDD',None)):
    w=workspace(tech,[]);objects={};materials=[]
    for i,net in enumerate(names):
        uid=str(i);x=i*300
        metal=box(x,0,x+200,200).difference(box(x+20,20,x+180,180))
        objects[uid]=Object(uid=uid,native_id=uid,kind='mpp',observed_net=net,bbox=((x,0),(x+200,200)),placement=Placement(origin=(x,0)),
            mpp=MultipartPath(master=Shape(kind='path',lpp=('M1','drawing'),points=((x,0),(x+200,0)),width=40)))
        materials.append(Physical(uid,'M1',metal,False,(),None,None))
    w=w.model_copy(update={'baseline':w.baseline.model_copy(update={'objects':objects})})
    monkeypatch.setattr('colayout_lite.mpp_geometry.rows',lambda w,p,o,**kw:[('M1',materials[int(o.uid)].geometry)])
    monkeypatch.setattr('colayout_lite.inspection_data.extract',lambda *a:(materials,[],[],None,None))
    return w,materials


def test_named_and_unnamed_guard_have_exact_metal_interfaces(tech,monkeypatch):
    w,m=guards(tech,monkeypatch);pins,warnings=scope_pins(w,tech,None)
    assert not warnings and len(pins)==1 and pins[0]['name']==pins[0]['net']=='VDD'
    assert pins[0]['figures'][0][1].equals(m[0].geometry)
    assert not pins[0]['figures'][0][1].covers(Point(100,100))  # The hole is not copper.
    graph=build_scope_graph(w,tech,None);trace=select_net(graph,pin_id=pins[0]['id'])
    assert len(trace['component_ids'])==1 and {n['owner_uid'] for n in trace['nodes']}=={'0'}
    assert not select_net(graph,point=('0',100,100,'M1',0))['nodes']


def test_same_name_guard_islands_stay_separate_and_scope_stops_at_blackbox(tech,monkeypatch):
    w,_=guards(tech,monkeypatch,('VDD','VDD'));graph=build_scope_graph(w,tech,None)
    trace=select_net(graph,pin_id=graph['pins'][0]['id']);assert len(trace['component_ids'])==2 and not trace['short_nets']
    r=OperationRegion(id='area',name='guard box',bbox=((-10,-10),(210,210)),object_uids=('0',))
    w=w.model_copy(update={'local_data':w.local_data.model_copy(update={'regions':{r.id:r}})})
    assert {p['owner'] for p in scope_pins(w,tech,None)[0]}=={'1'}
    assert {p['owner'] for p in scope_pins(w,tech,'area')[0]}=={'0'}
    assert {p['owner'] for p in scope_pins(w,tech,None,True)[0]}=={'0','1'}


def test_unknown_legacy_intent_does_not_invent_native_assignment(tech,monkeypatch):
    w,_=guards(tech,monkeypatch,(None,));obj=w.baseline.objects['0']
    obj=obj.model_copy(update={'properties':[['colayoutNetIntent','string',['string','VDD']]]})
    w=w.model_copy(update={'baseline':w.baseline.model_copy(update={'objects':{'0':obj}})})
    assert scope_pins(w,tech,None)[0]==[]
    pending=w.model_copy(update={'operations':(Operation(action='guard',uid='0',guard={'net_intent':'VDD'}),),
        'guard_previews':{'0':{'objects':{'0':obj.model_dump()},'display':{}}}})
    assert scope_pins(pending,tech,None)[0][0]['name']=='VDD'


@pytest.mark.parametrize('value',[None,'','  ','VDD\nVSS','VDD\x00'])
def test_guard_name_required(value):
    with pytest.raises(LiteError,match='GUARD_NET_REQUIRED'):required_net(value)


def test_guard_native_ambiguous_names_are_reported_not_guessed(tech,monkeypatch):
    w,_=guards(tech,monkeypatch,('VDD',));obj=w.baseline.objects['0']
    obj=obj.model_copy(update={'mpp':obj.mpp.model_copy(update={'parts':[{'lpp':['M1','drawing'],'net_name':'VSS'}]})})
    w=w.model_copy(update={'baseline':w.baseline.model_copy(update={'objects':{'0':obj}})})
    pins,warnings=scope_pins(w,tech,None);assert not pins and warnings[0]['kind']=='guard_pin_ambiguous'
