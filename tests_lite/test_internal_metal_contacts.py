"""Native PIN extensions, scope and advisory-only contact witnesses."""
# Imported shared fixtures intentionally have the pytest fixture names.
# ruff: noqa: F811
from copy import deepcopy
import pytest
from shapely.geometry import box
from colayout_lite.model import Object,Placement,Shape,Snapshot,Workspace
from colayout_lite.circuit.models import LayoutConnectivity,LayoutInstance,Terminal,ViewRef
from colayout_lite.local_models import LocalData,OperationRegion
from colayout_lite.drc.models import DrcProfile,Rule,Region
from colayout_lite.drc.local import run
from colayout_lite.drc.internal_metal_contacts import RULE_ID
from colayout_lite.drc.design_warnings import blocking
from colayout_lite.drc.reporting import report_payload
from colayout_lite.editor import Editor,projected
from colayout_lite.region_analysis import analyze
from tests_lite.test_agent_connectivity import tech


def fixture(p,wire=((50,20),(750,80)),*,layer='M1',purpose='drawing',kind='inst',nested=False):
    def figure(name,bbox,lpp='M1/drawing'):
        return [name,name,False,None,'rect',lpp,[list(pt) for pt in bbox],[]]
    figures=[figure('pin',((0,0),(100,100))),figure('extension',((100,0),(250,100))),
             figure('chain',((250,0),(400,100))),figure('island-a',((600,0),(700,100))),
             figure('island-b',((700,0),(800,100))),figure('island-c',((600,200),(700,300)))]
    device=Object(uid='device',native_id='device',kind=kind,bbox=((0,0),(1000,300)),
        placement=Placement(origin=(0,0)),attributes={'name':'opaque_device','master_key':'leaf'})
    shape=Shape(kind='rect',lpp=(layer,purpose),bbox=wire,net_intent='N')
    wire_obj=Object(uid='wire',native_id='wire',kind='rect',shape=shape,bbox=shape.bbox)
    styles=[[r['layer']+'/drawing',[[r['layer'],'drawing'],None,1,True,r['material'],None,None,None,None,None]]
            for r in p.layers if r['purpose']=='drawing']
    nodes={'leaf':['leaf','foreign_pdk','opaque_device','layout',str(p.dbu_per_micron),[[0,0],[1000,300]],[],[],
                   [['P','inputOutput','native',[]]],figures,[],[['child_count',int(nested)]]],
           'root':['root','L','C','layout',str(p.dbu_per_micron),[[-100,-100],[1100,400]],[],[],[],[],
                   [['device','leaf',kind,[0,0],'R0','1']]]}
    snap=Snapshot(library='L',cell='C',library_path='/L',session='s',counter='1',dirty=False,
        dbu_per_micron=p.dbu_per_micron,grid=p.grid,technology_fingerprint=p.native_fingerprint,
        objects={'device':device,'wire':wire_obj},pins=[{'instance_uid':'device','terminal':'P','kind':'rect',
            'lpp':['M1','drawing'],'local_bbox':[[20,20],[80,80]],'transform':[1,0,0,1,0,0]}],
        display={'root':'root','nodes':nodes,'styles':styles,'unsupported':[]})
    conn=LayoutConnectivity(source=ViewRef(library='L',cell='C',view='layout',session='s',counter='1'),
        instances={'device':LayoutInstance(uid='device',name='opaque_device',master=('foreign_pdk','opaque_device','layout'),
            black_box=nested,terminals={'P':Terminal(name='P',net='N')})},ports={})
    return Workspace(baseline=snap,profile_id=p.id,layout_connectivity=conn)


def config(p,**kwargs):
    return DrcProfile(id='test',technology_fingerprint=p.native_fingerprint,
        rules=(Rule(id='minimum',kind='width',layer='M1',value=.001),),**kwargs)


def check(w,p,roi=((-100,-100),(1100,400)),*,scope=None,profile=None):
    return run(w,p,profile or config(p),Region(bbox=roi),scope_id=scope)


def warnings(report):return [m for m in report.markers if m.rule_id==RULE_ID]


def test_external_wire_cannot_launder_internal_metal_as_pin_extension(tech):
    w=fixture(tech);before=w.model_dump_json();r=check(w,tech);hits=warnings(r)
    assert len(hits)==1 and hits[0].severity=='warning' and not blocking(hits[0])
    assert hits[0].bbox==((600,20),(750,80))  # excludes PIN/legitimate extension and device envelope
    assert hits[0].edges and hits[0].details['contact_area_um2']==pytest.approx(.009)
    assert [o['uid'] for o in hits[0].objects]==['wire','device']
    assert report_payload(r)['counts']['design_warnings']==1
    assert r.coverage['complete_for_configured_subset'] and w.model_dump_json()==before


@pytest.mark.parametrize('wire',[((50,20),(180,80)),((280,20),(350,80))])
def test_native_transitive_same_layer_extension_is_legal(tech,wire):
    assert not warnings(check(fixture(tech,wire),tech))


@pytest.mark.parametrize('wire,expected',[(((800,100),(900,200)),0),(((800,0),(900,100)),1),
    (((799,0),(900,100)),1),(((801,0),(900,100)),0)])
def test_exact_area_or_edge_contact_not_corner_or_bbox_overlap(tech,wire,expected):
    assert len(warnings(check(fixture(tech,wire),tech)))==expected


def test_one_warning_per_wire_device_layer_for_disconnected_fragments(tech):
    hits=warnings(check(fixture(tech,((640,-20),(660,320))),tech))
    assert len(hits)==1 and len(hits[0].edges)==8


def test_roi_uses_full_native_chain_to_pin_and_clips_only_the_witness(tech):
    p=config(tech,local_halo_um=0)
    w=fixture(tech,((280,20),(350,80)))
    assert not warnings(check(w,tech,((280,10),(360,90)),profile=p))
    w=fixture(tech)
    hit=warnings(check(w,tech,((640,10),(660,90)),profile=p))[0]
    assert hit.bbox==((640,20),(660,80))


@pytest.mark.parametrize('layer,purpose',[('M2','drawing'),('PO','drawing'),('M1','label')])
def test_other_metal_nonmetal_and_nonphysical_purpose_do_not_trigger(tech,layer,purpose):
    assert not warnings(check(fixture(tech,layer=layer,purpose=purpose),tech))


def test_blackbox_and_child_scope_are_not_expanded(tech):
    assert not warnings(check(fixture(tech,nested=True),tech))
    w=fixture(tech);child=OperationRegion(id='child',name='child',bbox=((-10,-10),(1010,310)),object_uids=('device',))
    w=w.model_copy(update={'local_data':LocalData(regions={'child':child})})
    assert not warnings(check(w,tech,scope=None))
    assert not warnings(check(w,tech,scope='child'))  # external parent wire is not a child edit


def test_unknown_pin_geometry_does_not_create_a_certain_nonpin_claim(tech):
    w=fixture(tech);w=w.model_copy(update={'baseline':w.baseline.model_copy(update={'pins':[]})})
    r=check(w,tech)
    assert not warnings(r) and r.coverage['internal_metal_contacts']['skipped_devices_without_complete_pin_geometry']==1


def test_synced_geometry_is_checked_without_pending_operations(tech):
    w=fixture(tech);assert not w.operations
    assert len(warnings(check(w,tech)))==1
    e=Editor(w,tech);e.transform_shape('wire',delta=(0,500));assert not warnings(check(e.w,tech))
    e.undo();assert projected(e.w)==projected(w) and len(warnings(check(e.w,tech)))==1


def test_warning_only_does_not_fail_complete_region_or_truncate_error_coverage(tech):
    w=fixture(tech);region=OperationRegion(id='r',name='r',bbox=((-100,-100),(1100,400)),
        object_uids=('device','wire'),pin_mode='directional')
    w=w.model_copy(update={'local_data':LocalData(regions={'r':region})})
    result=analyze(w,tech,config(tech),region.id)
    assert result['passed'] and result['drc']['counts']['design_warnings']==1
    # An actual foundry error still takes priority when the marker budget is full.
    rule=Rule(id='real_error',kind='width',layer='M1',value=1)
    r=check(w,tech,scope='r',profile=config(tech,max_markers=1).model_copy(update={'rules':(rule,)}))
    assert any(blocking(m) for m in r.markers) and not warnings(r)


def test_material_roles_and_native_pin_geometry_survive_pdk_renaming(tech):
    p=tech.model_copy(update={'layers':[{**r,'layer':'CopperA' if r['layer']=='M1' else r['layer']} for r in tech.layers],
        'writable_lpps':tuple(('CopperA' if l=='M1' else l,purpose) for l,purpose in tech.writable_lpps)})
    w=deepcopy(fixture(tech))
    w.baseline.display['styles'][0][0]='CopperA/drawing';w.baseline.display['styles'][0][1][0][0]='CopperA'
    for f in w.baseline.display['nodes']['leaf'][9]:f[5]='CopperA/drawing'
    w.baseline.pins[0]['lpp'][0]='CopperA'
    obj=w.baseline.objects['wire'];w.baseline.objects['wire']=obj.model_copy(update={'shape':obj.shape.model_copy(update={'lpp':('CopperA','drawing')})})
    rules=config(tech).model_copy(update={'rules':(Rule(id='min',kind='width',layer='CopperA',value=.001),)})
    hits=warnings(check(w,p,profile=rules));assert len(hits)==1 and hits[0].layers==('CopperA',)


@pytest.mark.parametrize('orientation',['R0','R90','R180','R270','MX','MY','MXR90','MYR90'])
def test_rigid_placement_projects_both_metal_and_native_pin(tech,orientation):
    from colayout_lite.geometry import transform,box as transform_box
    e=Editor(fixture(tech),tech)
    e.place('device',(2000,3000),orientation)
    e.transform_shape('wire',delta=(2000,3000),orientation=orientation)
    hit=warnings(check(e.w,tech,((-5000,-5000),(7000,7000))))[0]
    assert hit.bbox==transform_box(((600,20),(750,80)),transform((2000,3000),orientation))


def test_warning_marker_survives_portable_roundtrip(tech,tmp_path):
    w=fixture(tech);original=warnings(check(w,tech))[0]
    path=tmp_path/'saved.json';w.save(path,portable=True)
    loaded=Workspace.model_validate_json(path.read_text(encoding='utf8'))
    assert not loaded.operations and warnings(check(loaded,tech))[0]==original


def test_advisory_omission_does_not_turn_into_a_blocking_coverage_failure(tech):
    w=fixture(tech);a=w.baseline.objects['wire']
    b=a.model_copy(update={'uid':'wire2','native_id':'wire2','shape':a.shape.model_copy(update={'bbox':((640,220),(660,280))})})
    w=w.model_copy(update={'baseline':w.baseline.model_copy(update={'objects':{**w.baseline.objects,'wire2':b}})})
    r=check(w,tech,profile=config(tech,max_markers=1))
    assert len(warnings(r))==1 and r.coverage['internal_metal_contacts']['warning_count']==2
    assert r.coverage['internal_metal_contacts']['omitted_count']==1
    assert r.coverage['complete_for_configured_subset'] and not r.coverage['truncated']
    assert not any(blocking(m) for m in r.markers)


def test_internal_material_alone_is_not_an_external_wire_and_via_metal_is_checked(tech):
    w=fixture(tech);w=w.model_copy(update={'baseline':w.baseline.model_copy(update={'objects':{'device':w.baseline.objects['device']}})})
    assert not warnings(check(w,tech))
    via=Shape(kind='stdVia',via_definition='V12',origin=(650,50))
    obj=Object(uid='via',native_id='via',kind='stdVia',shape=via)
    w=w.model_copy(update={'baseline':w.baseline.model_copy(update={'objects':{**w.baseline.objects,'via':obj}})})
    hit=warnings(check(w,tech))[0];assert hit.details['wire_uid']=='via'


def test_poly_and_other_layer_paths_do_not_make_a_same_layer_pin_extension(tech):
    w=deepcopy(fixture(tech))
    for layer in ('PO','M2'):
        w.baseline.display['nodes']['leaf'][9].append([layer,layer,False,None,'rect',layer+'/drawing',[[0,20],[750,80]],[]])
    assert len(warnings(check(w,tech)))==1
