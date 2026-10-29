"""Local-only Poly patch: arbitrary PDK names, native PIN boundaries, unchanged viewer."""
from copy import deepcopy
import pytest
from colayout_lite.model import Object,Placement,Snapshot,Workspace
from colayout_lite.circuit.models import LayoutConnectivity,LayoutInstance,Terminal,ViewRef
from colayout_lite.drc.models import Region,DrcProfile,Rule
from colayout_lite.drc.local import run
from colayout_lite.inspection_data import build_scope_graph
from colayout_lite.region_analysis import connectivity
from colayout_lite.editor import Editor
from colayout_lite.regions.models import OperationRegion
from colayout_lite.conduction_rules import ConductionRules
from tests_lite.test_conduction_access import access_tech,tech

@pytest.fixture
def pair(access_tech):
    return sample(access_tech)

def sample(p,nets=('bias','ground'),*,count=2,body=False,blackbox=False):
    objects={};pins=[];instances={};nodes={};children=[]
    for i in range(count):
        uid=f'unit-{i}';origin=(i*280,0);key=f'master-{i}';name=f'opaque-{i}'
        figures=[['poly','poly',False,None,'rect','PO/drawing',[[0,0],[300,80]],[]],
                 ['metal','metal',False,None,'rect','M1/drawing',[[0,0],[100,80]],[]],
                 ['cut','cut',False,None,'rect','CO/drawing',[[20,20],[60,60]],[]]]
        terminals=[['G','input','intrinsic-gate',[]]]
        pin_specs=[('G',((25,25),(55,55)))]
        if body and i==0:
            figures += [['end','end',False,None,'rect','M1/drawing',[[220,0],[300,80]],[]],
                        ['endcut','endcut',False,None,'rect','CO/drawing',[[240,20],[280,60]],[]]]
            terminals=[['PLUS','inputOutput','end-a',[]],['MINUS','inputOutput','end-b',[]]]
            pin_specs=[('PLUS',((25,25),(55,55))),('MINUS',((245,25),(275,55)))]
        nodes[key]=[key,'arbitrary','unknown-device','layout',str(p.dbu_per_micron),[[0,0],[300,80]],[],[],terminals,figures,[],
                    [['child_count',1 if blackbox and i==0 else 0]]]
        objects[uid]=Object(uid=uid,native_id=uid,kind='inst',bbox=((origin[0],0),(origin[0]+300,80)),
            placement=Placement(origin=origin),attributes={'name':name,'master_key':key})
        net=nets[min(i,len(nets)-1)]
        instances[uid]=LayoutInstance(uid=uid,name=name,master=('arbitrary','unknown-device','layout'),black_box=blackbox and i==0,
            terminals={term:Terminal(name=term,net=net) for term,_ in pin_specs})
        for term,b in pin_specs:
            pins.append({'instance_uid':uid,'terminal':term,'lpp':['M1','drawing'],'kind':'rect',
                'local_bbox':b,'transform':[1,0,0,1,*origin]})
        children.append([uid,key,'inst',list(origin),'R0','1'])
    nodes['root']=['root','L','C','layout',str(p.dbu_per_micron),[[-100,-100],[count*300,200]],[],[],[],[],children]
    styles=[[r['layer']+'/drawing',[[r['layer'],'drawing'],None,1,True,r['material'],None,None,None,None,None]] for r in p.layers if r['purpose']=='drawing']
    snap=Snapshot(library='L',cell='C',library_path='/L',session='s',counter='1',dirty=False,dbu_per_micron=p.dbu_per_micron,
        grid=p.grid,technology_fingerprint=p.native_fingerprint,objects=objects,pins=pins,
        display={'root':'root','nodes':nodes,'styles':styles,'unsupported':[]})
    conn=LayoutConnectivity(source=ViewRef(library='L',cell='C',view='layout',session='s',counter='1'),instances=instances,ports={})
    return Workspace(baseline=snap,profile_id=p.id,layout_connectivity=conn)

def check(w,p,roi=((-200,-200),(2000,500)),scope=None):
    rules=DrcProfile(id='test',technology_fingerprint=p.native_fingerprint,rules=(Rule(id='width',kind='width',layer='M1',value=.001),))
    return run(w,p,rules,Region(bbox=roi),scope_id=scope)

def patches(report):return [m for m in report.markers if m.rule_id.startswith('LOCAL.POLY')]

def test_detects_metal_pin_short_through_poly_without_changing_connectivity(pair,access_tech):
    before=pair.model_dump_json();prior=build_scope_graph(pair,access_tech,None)
    assert not connectivity(prior)['shorts']
    report=check(pair,access_tech);markers=patches(report)
    assert len(markers)==1 and markers[0].rule_id=='LOCAL.POLY_CONTACT_SHORT'
    assert markers[0].details['nets']==['bias','ground']
    assert {p['owner'] for p in markers[0].details['pins']}=={'unit-0','unit-1'}
    assert pair.model_dump_json()==before
    assert not connectivity(build_scope_graph(pair,access_tech,None))['shorts']
    assert not any(r.kind=='poly_contact' for r in ConductionRules(access_tech).contacts)

def test_same_net_is_safe_for_patch_but_does_not_add_normal_connectivity(access_tech):
    w=sample(access_tech,('same','same'));report=check(w,access_tech)
    assert not patches(report) and report.coverage['poly_contact_check']['safe_pairs']==1
    assert not connectivity(build_scope_graph(w,access_tech,None))['complete']

def test_chain_attributes_conflict_to_bridge_and_resolves_pins_outside_small_roi(access_tech):
    w=sample(access_tech,('same','same','other'),count=3)
    report=check(w,access_tech,((555,-10),(585,90)))
    marker=patches(report)[0]
    assert marker.details['nets']==['other','same']
    assert any(p['owner']=='unit-2' for p in marker.details['pins'])
    full=check(w,access_tech)
    assert len(patches(full))==1 and full.coverage['poly_contact_check']['safe_pairs']==1

@pytest.mark.parametrize('defect',['missing_cut','partial_cut','missing_pin','unassigned_pin','unknown_via'])
def test_missing_evidence_never_turns_into_safety(pair,access_tech,defect):
    w=pair.model_copy(deep=True);p=access_tech
    figures=w.baseline.display['nodes']['master-0'][9]
    if defect=='missing_cut':figures.pop()
    elif defect=='partial_cut':figures[1][6]=[[0,0],[40,80]]
    elif defect=='missing_pin':w=w.model_copy(update={'baseline':w.baseline.model_copy(update={'pins':[r for r in w.baseline.pins if r['instance_uid']!='unit-0']})})
    elif defect=='unassigned_pin':
        conn=w.layout_connectivity;inst=conn.instances['unit-0']
        conn=conn.model_copy(update={'instances':{**conn.instances,'unit-0':inst.model_copy(update={'terminals':{'G':Terminal(name='G',net=None)}})}})
        w=w.model_copy(update={'layout_connectivity':conn})
    else:p=p.model_copy(update={'vias':{k:v for k,v in p.vias.items() if k!='GATE'}})
    report=check(w,p);assert any(m.rule_id=='LOCAL.POLY_CONTACT_UNRESOLVED' for m in patches(report))
    assert not report.coverage['complete_for_configured_subset']

def test_multi_terminal_body_not_an_ideal_wire_even_when_external_nets_equal(access_tech):
    w=sample(access_tech,('same','same'),body=True)
    report=check(w,access_tech);marker=patches(report)[0]
    assert marker.rule_id=='LOCAL.POLY_CONTACT_UNRESOLVED'
    assert any(set(i.get('terminal_domains',[]))=={'end-a','end-b'} for i in marker.details['issues'])
    e=Editor(w,access_tech);e.place('unit-1',(1000,0))
    report=check(e.w,access_tech);assert not patches(report)

def test_internal_poly_and_hierarchical_module_do_not_trigger(access_tech):
    assert not patches(check(sample(access_tech,count=1),access_tech))
    assert not patches(check(sample(access_tech,blackbox=True),access_tech))

def test_pose_and_move_away_use_current_geometry(pair,access_tech):
    e=Editor(pair,access_tech)
    e.place('unit-1',(1000,0));assert not patches(check(e.w,access_tech))
    e.undo();assert patches(check(e.w,access_tech))
    e.place('unit-1',(580,0),'MY');assert patches(check(e.w,access_tech))

def test_other_local_levels_stay_opaque(pair,access_tech):
    child=OperationRegion(id='child',name='child',bbox=((270,-100),(650,200)),object_uids=('unit-1',))
    w=pair.model_copy(update={'local_data':pair.local_data.model_copy(update={'regions':{'child':child}})})
    assert not patches(check(w,access_tech))

def test_renamed_pdk_layers_and_contact_names(pair,access_tech):
    names={'PO':'arbitrary_gate','CO':'plug_x','M1':'wire_a','M2':'wire_b','V1':'via_x'}
    p=access_tech.model_copy(deep=True);w=pair.model_copy(deep=True)
    p=p.model_copy(update={'layers':[{**r,'layer':names.get(r['layer'],r['layer'])} for r in p.layers],
        'vias':{'via_'+k:{**v,**{f:names.get(v[f],v[f]) for f in ('layer1','layer2','cut_layer')}} for k,v in p.vias.items()}})
    for n in w.baseline.display['nodes'].values():
        for f in n[9]:
            layer,purpose=f[5].split('/');f[5]=names.get(layer,layer)+'/'+purpose
    for row in w.baseline.pins:row['lpp'][0]=names.get(row['lpp'][0],row['lpp'][0])
    for row in w.baseline.display['styles']:
        l=row[1][0][0];row[0]=names.get(l,l)+'/drawing';row[1][0][0]=names.get(l,l)
    rules=DrcProfile(id='test',technology_fingerprint=p.native_fingerprint,rules=(Rule(id='width',kind='width',layer='wire_a',value=.001),))
    report=run(w,p,rules,Region(bbox=((-200,-200),(2000,500))),scope_id=None)
    assert patches(report)[0].details['nets']==['bias','ground']
    assert patches(report)[0].layers==('arbitrary_gate',)

def test_unknown_poly_role_is_disclosed(pair,access_tech):
    p=access_tech.model_copy(update={'layers':[{**r,'material':None} if r['layer']=='PO' else r for r in access_tech.layers]})
    report=check(pair,p)
    assert report.coverage['poly_contact_check']['status']=='unavailable'
    assert not report.coverage['complete_for_configured_subset']

def test_upper_metal_overlap_is_not_a_missing_gate_contact_mapping(pair,access_tech):
    w=pair.model_copy(deep=True)
    for node in (w.baseline.display['nodes']['master-0'],w.baseline.display['nodes']['master-1']):
        node[9].append(['upper','upper',False,None,'rect','M2/drawing',[[0,0],[100,80]],[]])
    report=check(w,access_tech)
    assert len(patches(report))==1 and patches(report)[0].rule_id=='LOCAL.POLY_CONTACT_SHORT'
    assert not patches(report)[0].details['issues']

def test_poly_pin_with_unknown_cut_mapping_is_not_silently_safe(access_tech):
    w=sample(access_tech,('same','same'))
    for pin in w.baseline.pins:pin['lpp'][0]='PO'
    p=access_tech.model_copy(update={'vias':{k:v for k,v in access_tech.vias.items() if k!='GATE'}})
    report=check(w,p)
    assert patches(report)[0].rule_id=='LOCAL.POLY_CONTACT_UNRESOLVED'
    assert any(i['kind']=='unknown_poly_contact_mapping' for i in patches(report)[0].details['issues'])

def test_marker_budget_and_cancellation_are_honoured(access_tech):
    w=sample(access_tech,('a','b','c'),count=3)
    rules=DrcProfile(id='test',technology_fingerprint=access_tech.native_fingerprint,max_markers=1,
        rules=(Rule(id='width',kind='width',layer='M1',value=.001),))
    r=run(w,access_tech,rules,Region(bbox=((-200,-200),(2000,500))),scope_id=None)
    assert len(patches(r))==1 and r.coverage['truncated'] and not r.coverage['complete_for_configured_subset']
    def cancel():raise RuntimeError('cancelled')
    with pytest.raises(RuntimeError,match='cancelled'):
        run(w,access_tech,rules,Region(bbox=((-200,-200),(2000,500))),scope_id=None,checkpoint=cancel)

def test_agent_rules_distinguish_patch_from_normal_conduction(access_tech):
    from colayout_lite.agent_tools.inspection import rules
    result=rules(access_tech,None)
    assert result['local_drc_patches'][0]['poly_layers']==['PO']
    assert any(r['names']==['GATE'] for r in result['local_drc_patches'][0]['contact_definitions'])
    assert 'gate-to-metal contact' in result['conduction']['unsupported_conduction']
    assert result['verification_workflow']['recommended_order']==['check_region','server_drc_region','release_region(done)']
    assert result['verification_workflow']['order_required'] is False
