"""Shared conductor rules: poly, N-well taps, and metal-only routing access."""
from copy import deepcopy
import pytest
from colayout_lite.model import Shape,LiteError
from colayout_lite.editor import Editor,projected
from colayout_lite.geometry import via_figures,ORIENT
from colayout_lite.circuit.models import LayoutConnectivity,LayoutInstance,Terminal,ViewRef
from colayout_lite.local_models import LocalData
from colayout_lite.regions.models import OperationRegion,InterfacePin
from colayout_lite.inspection_data import build_scope_graph
from colayout_lite.net_selection import select_net
from colayout_lite.physical_connectivity import check_connectivity
from colayout_lite.autoroute.snapshot import prepare,scope_graph,connectivity
from colayout_lite.autoroute.validation import validate
from colayout_lite.autoroute.builtin import generate
from colayout_lite.drc.models import DrcProfile,Rule
from tests_lite.test_agent_connectivity import tech,workspace,rect,local,intent,instance_workspace


@pytest.fixture
def access_tech(tech):
    # Deliberately use a poly name other than GT. No cell/instance names or
    # per-circuit coordinates participate in production conduction rules.
    layers=tech.layers+[dict(layer=l,purpose='drawing',material=m) for l,m in [('NW','nwell'),('NP','nplus'),('PP','pplus'),('PW','pwell')]]
    d=deepcopy(tech.vias['contact']);d.update(layer1='PO')
    well=deepcopy(tech.vias['contact']);well.update(implant1='NP',implant2='NW');well['defaults'].update(imp1Enc=[10,10],imp2Enc=[40,40])
    sub=deepcopy(tech.vias['contact']);sub.update(implant1='PP');sub['defaults'].update(imp1Enc=[10,10])
    return tech.model_copy(update={'layers':layers,'vias':{**tech.vias,'GATE':d,'WELL':well,'SUB':sub}})


def check(technology,shapes,pin_layer='PO'):
    return check_connectivity(workspace(technology,shapes),technology,intent(),
        {'A':local(-140,-10,-120,10,pin_layer),'B':local(0,-10,20,10)})


@pytest.mark.parametrize('layer,via',[('PO','GATE'),('NW','WELL')])
def test_manual_contact_connects_supported_pin_to_metal(access_tech,layer,via):
    base=[rect(-160,-60,80,60,layer),rect(-40,-40,40,40)]
    assert check(access_tech,base,layer)['status']=='fail'
    base.append(Shape(kind='stdVia',via_definition=via,origin=(0,0)))
    report=check(access_tech,base,layer)
    assert (report['status']=='pass')==(layer=='NW') and not report['shorts']
    if layer=='NW':assert {layer,'M1'}<=set(report['components'][0]['layers'])


@pytest.mark.parametrize('defect',['no_cut','no_implant','p_implant','partial_cut','pwell','no_active'])
def test_nwell_contact_needs_full_correct_material_signature(access_tech,defect):
    rows=[rect(-160,-60,80,60,'NW'),rect(-40,-40,40,40),rect(-40,-40,40,40,'AA'),rect(-50,-50,50,50,'NP'),rect(-20,-20,20,20,'CO')]
    if defect=='no_cut':rows.pop()
    elif defect=='no_implant':rows.pop(3)
    elif defect=='no_active':rows.pop(2)
    elif defect=='p_implant':rows[3]=rect(-50,-50,50,50,'PP')
    elif defect=='partial_cut':rows[1]=rect(0,-40,40,40)
    else:rows.append(rect(-80,-80,80,80,'PW'))
    report=check(access_tech,rows,'NW');assert report['status']!='pass' and not report['shorts']


def test_raw_ngr_geometry_uses_same_contact_proof_as_standard_via(access_tech):
    rows=[rect(-160,-60,80,60,'NW'),rect(-40,-40,40,40),rect(-40,-40,40,40,'AA'),rect(-50,-50,50,50,'NP'),rect(-20,-20,20,20,'CO')]
    report=check(access_tech,rows,'NW');assert report['status']=='pass'
    assert report['coverage']['via_link_count']==1
    # Same cut and the wrong implant must never turn a substrate tap into NGR.
    rows[3]=rect(-50,-50,50,50,'PP');assert check(access_tech,rows,'NW')['status']=='fail'


def test_plain_diffusion_contact_uses_existing_nplus_and_well(access_tech):
    rows=[rect(-160,-60,80,60,'NW'),rect(-50,-50,50,50,'NP'),Shape(kind='stdVia',via_definition='contact',origin=(0,0))]
    assert check(access_tech,rows,'NW')['status']=='pass'
    rows[1]=rect(-50,-50,50,50,'PP')
    assert check(access_tech,rows,'NW')['status']!='pass'
    rows[1]=rect(-50,-50,50,50,'NP');rows[2]=Shape(kind='stdVia',via_definition='SUB',origin=(0,0))
    assert check(access_tech,rows,'NW')['status']!='pass'


def test_gate_contact_does_not_turn_active_channel_into_a_wire(access_tech):
    shapes=[rect(-160,-60,80,60,'PO'),rect(-40,-40,40,40),rect(-40,-40,40,40,'AA'),rect(-20,-20,20,20,'CO')]
    assert check(access_tech,shapes)['status']!='pass'


def test_same_net_labels_do_not_rejoin_gate_in_highlight(access_tech):
    from shapely.geometry import box
    from colayout_lite.net_selection import index_contacts
    w=workspace(access_tech,[rect(-160,-60,80,60,'PO'),rect(-40,-40,40,40),Shape(kind='stdVia',via_definition='GATE',origin=(0,0))])
    graph=build_scope_graph(w,access_tech,None)
    graph['pins']=[{'id':'G','label':'G','net':'N','local':False,'figures':[('PO',box(-140,-10,-120,10))]},
        {'id':'M','label':'M','net':'N','local':False,'figures':[('M1',box(0,-10,20,10))]}]
    index_contacts(graph)
    assert {n['layer'] for n in select_net(graph,pin_id='M')['nodes']}=={'M1'}
    assert {n['layer'] for n in select_net(graph,pin_id='G')['nodes']}=={'PO'}
    assert not any(e.get('contact_kind')=='gate_contact' for e in graph['edges'])


def access_workspace(p,layer='PO',*,exposed=False,blackbox=False):
    w=instance_workspace(p,pin_layer='M1' if exposed else layer);display=deepcopy(w.baseline.display);master=display['nodes']['master']
    master[9]=[['conductor','conductor',False,None,'rect',layer+'/drawing',[[0,0],[300,80]],[]]]
    if exposed:
        spec=Shape(kind='stdVia',via_definition='GATE' if layer=='PO' else 'WELL',origin=(50,40))
        for i,f in enumerate(via_figures(spec,p)):
            master[9].append([str(i),str(i),False,None,'rect','/'.join(f['lpp']),f['bbox'],[]])
    styles={row['layer']:row for row in p.layers if row['purpose']=='drawing'}
    display['styles']=[[l+'/drawing',[[l,'drawing'],None,1,True,r['material'],None,None,None,None,None]] for l,r in styles.items()]
    pins=deepcopy(w.baseline.pins);pins[0]['terminal']='G' if layer=='PO' else 'B'
    term=pins[0]['terminal'];obj=w.baseline.objects['mos'].model_copy(update={'bbox':((1000,2000),(1300,2080))})
    inst=LayoutInstance(uid='mos',name='M.1',master=('L','mos','layout'),black_box=blackbox,terminals={term:Terminal(name=term,net='N')})
    conn=LayoutConnectivity(source=ViewRef(library='L',cell='C',view='layout',session='s',counter='1'),instances={'mos':inst},ports={'N':Terminal(name='N',net='N')})
    return w.model_copy(update={'baseline':w.baseline.model_copy(update={'display':display,'pins':pins,'objects':{'mos':obj}}),'layout_connectivity':conn})


@pytest.mark.parametrize('layer',['PO','NW'])
def test_native_metal_pin_lights_its_full_lower_conductor(access_tech,layer):
    w=access_workspace(access_tech,layer,exposed=True);g=build_scope_graph(w,access_tech,None)
    r=select_net(g,point=('mos',1050,2040,'M1',0))
    assert {n['layer'] for n in r['nodes']}==({'M1',layer} if layer=='NW' else {'M1'})
    if layer=='NW':assert max(n['geometry'].bounds[2] for n in r['nodes'] if n['layer']==layer)>=1300
    assert not r['short_nets']


def test_native_module_does_not_expose_its_internal_poly(access_tech):
    w=access_workspace(access_tech,exposed=True,blackbox=True);g=build_scope_graph(w,access_tech,None)
    assert {n['layer'] for n in g['nodes']}=={'M1'} and not g['access_materials']


@pytest.mark.parametrize('layer',['PO','NW'])
@pytest.mark.parametrize('orientation',list(ORIENT))
def test_leaf_contact_follows_rigid_pose(access_tech,layer,orientation):
    e=Editor(access_workspace(access_tech,layer,exposed=True),access_tech)
    e.place('mos',(-2000,3000),orientation);g=build_scope_graph(e.w,access_tech,None)
    pin=g['pins'][0];shape=next(geo for l,geo in pin['figures'] if l=='M1');pt=shape.representative_point()
    trace=select_net(g,point=('mos',pt.x,pt.y,'M1',0))
    assert {n['layer'] for n in trace['nodes']}==({'M1',layer} if layer=='NW' else {'M1'}) and not g['warnings']


def test_empty_leaf_cache_is_not_reported_as_complete_access(access_tech):
    w=access_workspace(access_tech,exposed=True);display=deepcopy(w.baseline.display);display['nodes']['master'][9]=[]
    g=build_scope_graph(w.model_copy(update={'baseline':w.baseline.model_copy(update={'display':display})}),access_tech,None)
    assert any(r['kind']=='access_geometry_missing' for r in g['warnings'])


@pytest.mark.parametrize('same_parent_net',[False,True])
@pytest.mark.parametrize('same_master_net',[False,True])
def test_intrinsic_poly_element_does_not_short_native_terminals(access_tech,same_parent_net,same_master_net):
    w=access_workspace(access_tech,exposed=True);display=deepcopy(w.baseline.display);master=display['nodes']['master']
    for i,f in enumerate(via_figures(Shape(kind='stdVia',via_definition='GATE',origin=(250,40)),access_tech)):
        master[9].append(['end'+str(i),'end'+str(i),False,None,'rect','/'.join(f['lpp']),f['bbox'],[]])
    master[8]=[['G','inputOutput','LEFT',[]],['OTHER','inputOutput','LEFT' if same_master_net else 'RIGHT',[]]]
    pin={**w.baseline.pins[0],'terminal':'OTHER','local_bbox':[[200,0],[300,80]],'bbox':[[1200,2000],[1300,2080]]}
    inst=w.layout_connectivity.instances['mos'];inst=inst.model_copy(update={'terminals':{**inst.terminals,'OTHER':Terminal(name='OTHER',net='N' if same_parent_net else 'P')}})
    w=w.model_copy(update={'baseline':w.baseline.model_copy(update={'display':display,'pins':w.baseline.pins+[pin]}),
        'layout_connectivity':w.layout_connectivity.model_copy(update={'instances':{'mos':inst}})})
    graph=build_scope_graph(w,access_tech,None)
    left=graph['pin_components']['mos:G'];right=graph['pin_components']['mos:OTHER']
    assert not left & right
    assert not connectivity(graph)['shorts']
    nets={'N':['M.1.G','M.1.OTHER']} if same_parent_net else {'N':['M.1.G'],'P':['M.1.OTHER']}
    report=check_connectivity(w,access_tech,intent(nets,{'M.1':'mos'}),{})
    assert not report['shorts']
    assert bool(report['opens'])==same_parent_net
    # The router must apply the same intrinsic-device boundary even when the
    # cached PCell figures carry inside_instance=False. Previously its second
    # obstacle graph shorted both resistor terminals through the poly body.
    region=OperationRegion(id='R',name='poly device',bbox=((800,1800),(1500,2300)),object_uids=('mos',))
    w=w.model_copy(update={'local_data':LocalData(regions={'R':region}),
        'layout_connectivity':w.layout_connectivity.model_copy(update={'ports':{}})})
    drc=DrcProfile(id='test',technology_fingerprint=access_tech.native_fingerprint,rules=tuple(
        Rule(id=l+k,kind=k,layer=l,value=v) for l in ('M1','M2') for k,v in [('width',.04),('spacing',.02)]))
    problem=prepare(w,access_tech,drc,'R',layers=['M1'])
    assert not problem.coverage['connectivity']['shorts'] and len(problem.groups)==2


@pytest.mark.parametrize('layer',['PO','NW'])
def test_contact_landing_is_available_even_when_pin_stays_on_lower_layer(access_tech,layer):
    w=access_workspace(access_tech,layer,exposed=True)
    pins=[{**p,'lpp':[layer,'drawing']} for p in w.baseline.pins]
    w=w.model_copy(update={'baseline':w.baseline.model_copy(update={'pins':pins})})
    graph=build_scope_graph(w,access_tech,None);cs=graph['pin_components'][graph['pins'][0]['id']]
    assert len(cs)==1 and {n['layer'] for n in graph['nodes'] if n['component_id'] in cs}==({'M1',layer} if layer=='NW' else {layer})


@pytest.mark.parametrize('continuous',[False,True])
def test_only_actual_nwell_continuity_joins_two_taps(access_tech,continuous):
    shapes=[rect(-160,-80,560 if continuous else 80,80,'NW',net='SAME'),
        Shape(kind='stdVia',via_definition='WELL',origin=(0,0)),Shape(kind='stdVia',via_definition='WELL',origin=(400,0))]
    if not continuous:shapes.append(rect(320,-80,560,80,'NW',net='SAME'))
    report=check_connectivity(workspace(access_tech,shapes),access_tech,intent(),{'A':local(-140,-10,-120,10,'NW'),'B':local(400,-10,420,10)})
    assert (report['status']=='pass')==continuous


def routing_case(p,layer,contact):
    w=access_workspace(p,layer);e=Editor(w,p)
    if contact:e.create(Shape(kind='stdVia',via_definition='GATE' if layer=='PO' else 'WELL',origin=(1250,2040)))
    pin=InterfacePin(id='OUT',name='OUT',net='N',lpp=('M1','drawing'),bbox=((1960,2000),(2040,2080)),fixed=True)
    region=OperationRegion(id='R',name='access test',bbox=((800,1800),(2000,2400)),object_uids=tuple(projected(e.w)),pins={'OUT':pin})
    e.w=e.w.model_copy(update={'local_data':LocalData(regions={'R':region})});e.scope_id='R'
    drc=DrcProfile(id='test',technology_fingerprint=p.native_fingerprint,rules=tuple(Rule(id=l+k,kind=k,layer=l,value=v) for l in ('M1','M2') for k,v in [('width',.04),('spacing',.02)]))
    return e,drc


def test_router_does_not_rejoin_series_resistor_access_domains(access_tech):
    """Two poly legs joined by internal M1: each PIN domain is accessible,
    but the resistor's other internal metal must not join the two nets."""
    p=access_tech;w=access_workspace(p,exposed=True);display=deepcopy(w.baseline.display)
    master=display['nodes']['master'];master[9]=[]
    shapes=[rect(0,0,300,80,'PO'),rect(0,200,300,280,'PO'),rect(210,0,290,280)]
    shapes += [Shape(kind='stdVia',via_definition='GATE',origin=(x,y)) for x in (50,250) for y in (40,240)]
    for i,s in enumerate(shapes):
        fs=via_figures(s,p) if s.kind=='stdVia' else [{'lpp':s.lpp,'bbox':s.bbox}]
        for j,f in enumerate(fs):master[9].append([f'{i}-{j}',f'{i}-{j}',False,None,'rect','/'.join(f['lpp']),f['bbox'],[]])
    master[8]=[['G','inputOutput','LEFT',[]],['OTHER','inputOutput','RIGHT',[]]]
    first=w.baseline.pins[0];other={**first,'terminal':'OTHER','local_bbox':[[0,200],[100,280]],'bbox':[[1000,2200],[1100,2280]]}
    inst=w.layout_connectivity.instances['mos'];inst=inst.model_copy(update={'terminals':{**inst.terminals,'OTHER':Terminal(name='OTHER',net='P')}})
    region=OperationRegion(id='R',name='series resistor',bbox=((800,1800),(1500,2500)),object_uids=('mos',))
    w=w.model_copy(update={'baseline':w.baseline.model_copy(update={'display':display,'pins':[first,other]}),
        'layout_connectivity':w.layout_connectivity.model_copy(update={'instances':{'mos':inst},'ports':{}}),
        'local_data':LocalData(regions={'R':region})})
    drc=DrcProfile(id='test',technology_fingerprint=p.native_fingerprint,rules=tuple(
        Rule(id=l+k,kind=k,layer=l,value=v) for l in ('M1','M2') for k,v in [('width',.04),('spacing',.02)]))
    graph=scope_graph(w,p,'R');assert not connectivity(graph)['shorts']
    problem=prepare(w,p,drc,'R',layers=['M1'])
    assert len(problem.groups)==2 and not problem.coverage['connectivity']['shorts']
    # The joining metal remains a collision obstacle, not removed geometry.
    from colayout_lite.autoroute.geometry import decode
    from shapely.geometry import Point
    assert any(m.net is None and decode(m.geometry).covers(Point(1250,2140)) for m in problem.materials)
    # A genuine external metal short still fails the shared check.
    e=Editor(w,p,scope_id='R');e.create(rect(1000,2000,1100,2280))
    with pytest.raises(LiteError,match='ROUTING_EXISTING_SHORT'):prepare(e.w,p,drc,'R',layers=['M1'])


@pytest.mark.parametrize('layer',['PO','NW'])
def test_routing_refuses_unescaped_pin_then_uses_manual_metal_access(access_tech,layer):
    if layer=='PO':
        for contact in (False,True):
            e,drc=routing_case(access_tech,layer,contact)
            with pytest.raises(LiteError,match='ROUTING_GATE_PIN_UNSUPPORTED') as error:prepare(e.w,e.profile,drc,'R',layers=['M1'])
            assert error.value.details['pins'][0]['layers']==['PO']
        return
    e,drc=routing_case(access_tech,layer,False)
    with pytest.raises(LiteError,match='ROUTING_NATIVE_ACCESS_REQUIRED') as error:prepare(e.w,e.profile,drc,'R',layers=['M1'])
    assert error.value.details['pins'][0]['unescaped_components']
    e,drc=routing_case(access_tech,layer,True);before=e.w
    problem=prepare(e.w,e.profile,drc,'R',layers=['M1'])
    result=generate(problem,'builtin.astar');reports=[validate(e.w,e.profile,drc,problem,c) for c in result.candidates]
    ready=next((r for r in reports if r['status']=='ready'),None)
    assert ready is not None,reports
    assert e.w is before and ready['connectivity']['complete'] and not ready['drc']['markers']
    assert {s.lpp[0] for c in result.candidates for s in c.shapes if s.kind!='stdVia'}<={'M1','M2'}
    assert all(s.via_definition=='V12' for c in result.candidates for s in c.shapes if s.kind=='stdVia')
    from colayout_lite.autoroute.models import Proposal
    from colayout_lite.autoroute.validation import checked_operations
    for forbidden in ('PO','NW'):
        with pytest.raises(LiteError,match='PLUGIN_LAYER_NOT_ALLOWED'):
            checked_operations(Proposal(title='invalid',shapes=(rect(1000,2100,1400,2140,forbidden,net='N'),)),problem,e.profile)
    with pytest.raises(LiteError,match='PLUGIN_VIA_NOT_ALLOWED'):
        checked_operations(Proposal(title='invalid',shapes=(Shape(kind='stdVia',via_definition='GATE',origin=(1250,2040),net_intent='N'),)),problem,e.profile)
