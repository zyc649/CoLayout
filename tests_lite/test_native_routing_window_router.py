from shapely.geometry import box
from colayout_lite.editor import Editor
from colayout_lite.circuit.models import CircuitContext,ReferenceInstance,NativeBinding,NativePathSegment,NativeCheck,Terminal
from colayout_lite.regions.models import OperationRegion,InterfacePin
from colayout_lite.native_routing_windows import NativeRoutingWindows
from colayout_lite.autoroute.snapshot import prepare
from colayout_lite.autoroute.maze import Maze
from colayout_lite.autoroute.builtin import generate
from colayout_lite.autoroute.validation import validate
from colayout_lite.drc.models import DrcProfile,Rule,Region
from colayout_lite.drc.scope import selection
from tests_lite.test_drc_hierarchy_scope import device_fixture,with_native_module,tech


def test_native_internal_pin_can_escape_corridor_without_exposing_internal_copper(tech):
    w=with_native_module(device_fixture(tech,nested=True),'i');layout=w.layout_connectivity
    term=Terminal(name='P',net='N')
    layout=layout.model_copy(update={'instances':{'i':layout.instances['i'].model_copy(update={'terminals':{'P':term}})},
                                     'ports':{'OUT':Terminal(name='OUT',net='N')}})
    path=(NativePathSegment(library='L',cell='C',view='schematic',instance='I',member=0,row=0,column=0),)
    circuit=CircuitContext(source=layout.source.model_copy(update={'view':'schematic'}),
        instances={'I':ReferenceInstance(name='I',master=('L','wrapped','symbol'),terminals={'P':term})},
        ports={'OUT':Terminal(name='OUT',net='N')},bindings=(NativeBinding(layout_uid='i',schematic_paths=(path,)),),
        native_check=NativeCheck(report='fixture'))
    # A large internal wall would block the corridor if the router flattened it.
    display=w.baseline.display
    display['nodes']['leaf'][9].append(['hidden-wall','hidden-wall',False,None,'rect','M1/drawing',[[800,0],[900,1000]],None])
    pin={'instance_uid':'i','terminal':'P','lpp':['M1','drawing'],'kind':'rect','bbox':[[450,450],[650,650]]}
    region=OperationRegion(id='r',name='r',bbox=((-500,-500),(2000,1500)),object_uids=('i',),
        pins={'edge':InterfacePin(id='edge',name='N',net='N',bbox=((1900,400),(2100,600)),lpp=('M1','drawing'))})
    w=w.model_copy(update={'layout_connectivity':layout,'circuit':circuit,
        'baseline':w.baseline.model_copy(update={'pins':[pin]}),'local_data':w.local_data.model_copy(update={'regions':{'r':region}})})
    e=Editor(w,tech,scope_id='r')
    drc=DrcProfile(id='routing',technology_fingerprint='fp',rules=(
        Rule(id='width',kind='width',layer='M1',value=.1),
        Rule(id='spacing',kind='spacing',layer='M1',value=.1),
        Rule(id='area',kind='area',layer='M1',value=.01)))
    closed=prepare(e.w,tech,drc,'r',layers=['M1'])
    assert Maze(closed,'N',[]).collision('M1',box(500,450,1200,650),0)
    ident=NativeRoutingWindows(e).create('i',(400,350,1100,750),['M1'])
    opened=prepare(e.w,tech,drc,'r',layers=['M1'])
    assert not Maze(opened,'N',[]).collision('M1',box(500,450,1200,650),0)
    assert Maze(opened,'N',[]).collision('M1',box(500,100,1200,200),0)
    assert selection(e.w,Region(bbox=region.bbox),'r')[1]['native_instance_ids']==['i']
    candidates=generate(opened,'builtin.pattern')
    reports=[validate(e.w,tech,drc,opened,c) for c in candidates.candidates]
    assert any(r['status']=='ready' for r in reports),reports
    assert len(opened.pins)==2 and {p['id'] for p in opened.pins}=={'i:P','edge'}
    NativeRoutingWindows(e).update(ident,enabled=False)
    assert Maze(prepare(e.w,tech,drc,'r',layers=['M1']),'N',[]).collision('M1',box(500,450,1200,650),0)
