import pytest
from colayout_lite.editor import Editor,projected
from colayout_lite.model import Workspace,Snapshot,Object,Placement,Shape,LiteError
from colayout_lite.circuit.models import (CircuitContext,LayoutConnectivity,ReferenceInstance,LayoutInstance,
    NativeBinding,NativePathSegment,NativeCheck,Terminal,ViewRef)
from colayout_lite.regions.actions import RegionActions
from colayout_lite.regions.query import boundary,owner_map
from colayout_lite.regions.constraints import check_workspace
from colayout_lite.document import save_document,load_document
from tests_lite.test_kernel import profile


@pytest.fixture
def region_editor(profile):
    objects={};physical={};logical={};bindings=[]
    for name,x in [('A',0),('B',4000),('C',12000),('D',16000)]:
        uid='object-'+name;terms={'N':Terminal(name='N',net='N',members={'N':'N'})}
        if name=='A':terms['X']=Terminal(name='X',net='X',members={'X':'X'})
        objects[uid]=Object(uid=uid,native_id=name,kind='inst',bbox=((x,0),(x+2000,2000)),placement=Placement(origin=(x,0)),attributes={'name':name})
        physical[uid]=LayoutInstance(uid=uid,name=name,master=('PDK','mos','layout'),terminals=terms,black_box=False)
        logical[name]=ReferenceInstance(name=name,master=('PDK','mos','symbol'),terminals=terms)
        bindings.append(NativeBinding(layout_uid=uid,schematic_paths=((NativePathSegment(library='L',cell='C',view='schematic',instance=name,member=0,row=0,column=0),),)))
    source=ViewRef(library='L',cell='C',view='schematic',session='s',counter='1')
    reference=CircuitContext(source=source,pair_id='pair',instances=logical,ports={'OUT':Terminal(name='OUT',net='X')},bindings=tuple(bindings),native_check=NativeCheck(report='native fixture'))
    layout=LayoutConnectivity(source=source.model_copy(update={'view':'layout'}),pair_id='pair',instances=physical,ports={})
    snapshot=Snapshot(library='L',cell='C',library_path='/L',session='s',counter='1',dirty=False,dbu_per_micron=profile.dbu_per_micron,
        grid=profile.grid,objects=objects,routes={},fig_groups={},technology_fingerprint=profile.native_fingerprint)
    return Editor(Workspace(baseline=snapshot,profile_id=profile.id,circuit=reference,layout_connectivity=layout),profile)


def test_three_level_hierarchy_fixed_interfaces_ownership_undo_and_document(region_editor,tmp_path):
    e=region_editor;a=RegionActions(e)
    left=a.create((-1000,-1000,7000,7000),'left');right=a.create((11000,-1000,19000,7000),'right')
    assert {p.net for p in e.w.local_data.regions[left].pins.values()}=={'N','X'}
    pin=next(p for p in e.w.local_data.regions[left].pins.values() if p.net=='N')
    a.place_pin(left,pin.id,6500,5000,'wire_a')
    assert sum(p[0] for p in e.w.local_data.regions[left].pins[pin.id].bbox)/2==7000
    a.seal(left);a.seal(right)
    parent=a.create((-2000,-2000,21000,9000),'parent');a.seal(parent)
    top=a.create((-3000,-3000,23000,11000),'top');a.seal(top)
    assert e.w.local_data.regions[left].parent_id==parent
    assert e.w.local_data.regions[parent].parent_id==top
    assert e.w.local_data.regions[top].object_uids==()
    assert set(owner_map(e.w))==set(e.w.baseline.objects)
    before=e.w
    with pytest.raises(LiteError,match='REGION_SCOPE_VIOLATION'):e.place('object-A',(0,1000))
    with pytest.raises(LiteError,match='REGION_SCOPE_VIOLATION'):a.place_pin(left,pin.id,0,0,'wire_a')
    with pytest.raises(LiteError,match='REGION_ALWAYS_ACTIVE'):a.unseal(left)
    e.scope_id=left;e.place('object-A',(0,1000))
    assert e.w.local_data.regions[left].pins==before.local_data.regions[left].pins
    assert e.w.local_data.regions[parent]==before.local_data.regions[parent]  # Internal work does not move parent interface.
    e.undo();assert e.w.local_data==before.local_data
    uid=e.create(Shape(kind='rect',lpp=('wire_a','drawing'),bbox=((2000,3000),(3000,4000)),net_intent='N'))
    assert owner_map(e.w)[uid]==left
    e.delete(uid);assert uid not in owner_map(e.w)
    e.undo();assert owner_map(e.w)[uid]==left
    path=tmp_path/'regions.colayout.json';save_document(path,e.w,e.profile);loaded,p=load_document(path)
    assert loaded.local_data==e.w.local_data and p==e.profile


def test_partial_objects_and_sibling_overlap_leave_workspace_unchanged(region_editor):
    e=region_editor;a=RegionActions(e);before=e.w
    with pytest.raises(LiteError,match='REGION_CUTS_OBJECTS'):a.create((1000,-1000,7000,7000))
    assert e.w==before
    left=a.create((-1000,-1000,7000,7000));a.seal(left);before=e.w
    with pytest.raises(LiteError,match='REGION_PARTIAL_OVERLAP'):a.create((5000,-2000,20000,8000))
    assert e.w==before


def test_ambiguous_top_reference_requires_explicit_local_association(region_editor):
    e=region_editor;a=RegionActions(e);c=e.w.circuit
    terms={**c.instances['A'].terminals,'X':Terminal(name='X',net='REF_X')}
    c=c.model_copy(update={'instances':{**c.instances,'A':c.instances['A'].model_copy(update={'terminals':terms})},'ports':{'OUT':Terminal(name='OUT',net='REF_X')}})
    e.w=e.w.model_copy(update={'circuit':c})
    before=e.w
    with pytest.raises(LiteError,match='BOUNDARY_UNRESOLVED'):a.create((-1000,-1000,7000,7000))
    assert e.w==before
    a.associate_reference('REF_X','X');ident=a.create((-1000,-1000,7000,7000))
    assert any('人工关联' in evidence for p in e.w.local_data.regions[ident].pins.values() for evidence in p.evidence)
    assert e.w.layout_connectivity.instances['object-A'].terminals['X'].net=='X'


def test_keepouts_layers_vias_and_blackbox_overflight(region_editor):
    e=region_editor;a=RegionActions(e)
    left=a.create((-1000,-1000,7000,7000));a.seal(left)
    a.update_details(left,'left','',('wire_a',))
    blocked=Shape(kind='rect',lpp=('wire_a','drawing'),bbox=((2000,3000),(3000,4000)))
    with pytest.raises(LiteError,match='LOCAL_ROUTING_BLOCKED'):e.create(blocked)
    uid=e.create(blocked.model_copy(update={'lpp':('wire_b','drawing')}))
    assert uid not in owner_map(e.w)  # Parent-layer overflight remains parent-owned.
    keep=a.add_keepout((9000,3000,11000,5000),['wire_b'])
    with pytest.raises(LiteError,match='LOCAL_ROUTING_BLOCKED'):
        e.create(Shape(kind='stdVia',origin=(10000,4000),via_definition='JOIN'))
    e.create(Shape(kind='rect',lpp=('wire_a','drawing'),bbox=((9200,3200),(9500,3500))))
    a.remove_box(keep)
    assert check_workspace(e.w,e.profile)['passed']


def test_new_keepout_reports_existing_wire_and_markup_roundtrips(region_editor,tmp_path):
    e=region_editor;a=RegionActions(e)
    wire=e.create(Shape(kind='rect',lpp=('wire_a','drawing'),bbox=((8000,4000),(9000,5000))))
    keep=a.add_keepout((7000,3000,10000,6000),['wire_a'],'review');mark=a.add_markup((7000,3000,10000,6000),'重画这根线')
    report=check_workspace(e.w,e.profile)
    assert report['violations'][0]['object_id']==wire and report['violations'][0]['blocker_id']==keep
    e.undo();assert mark not in e.w.local_data.markups;e.redo();assert e.w.local_data.markups[mark].text=='重画这根线'
    path=tmp_path/'boxes.json';save_document(path,e.w,e.profile);assert load_document(path)[0].local_data==e.w.local_data


def test_native_module_whole_layer_policy_does_not_open_internals(region_editor):
    e=region_editor;a=RegionActions(e);layout=e.w.layout_connectivity
    inst=layout.instances['object-C'].model_copy(update={'black_box':True})
    e.w=e.w.model_copy(update={'layout_connectivity':layout.model_copy(update={'instances':{**layout.instances,'object-C':inst}})})
    shape=Shape(kind='rect',lpp=('wire_b','drawing'),bbox=((12200,200),(12400,400)))
    with pytest.raises(LiteError,match='LOCAL_ROUTING_BLOCKED'):e.create(shape)
    a.native_policy('object-C',['wire_a']);uid=e.create(shape)
    assert uid in projected(e.w)
    assert e.w.layout_connectivity.instances['object-C'].black_box


def test_geometry_batch_has_one_owner_and_one_region_revision(region_editor,tmp_path):
    from colayout_lite.workspace_actions import WorkspaceActions
    e=region_editor;a=RegionActions(e);ident=a.create((-1000,-1000,7000,7000));a.seal(ident);e.scope_id=ident
    before=e.w;result=WorkspaceActions(e).geometry_batch([{'action':'create_rect','params':{'lpp':['wire_a','drawing'],'x':1,'y':1.5,'width':.5,'height':.5}}])
    uid=result['operations'][0]['uid'];r=e.w.local_data.regions[ident]
    assert r.object_uids.count(uid)==1 and r.revision==before.local_data.regions[ident].revision+1
    path=tmp_path/'batch.json';save_document(path,e.w,e.profile);load_document(path)
    e.undo();assert e.w.local_data==before.local_data
