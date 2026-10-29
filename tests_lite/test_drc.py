import json,math
from pathlib import Path
import pytest
from colayout_lite.model import Shape,Object,Snapshot,Workspace,Placement,LiteError
from colayout_lite.technology import TechnologyProfile
from colayout_lite.editor import Editor
from colayout_lite.drc.models import Rule,DrcProfile,Region,RemoteConfig
from colayout_lite.drc.local import run
from colayout_lite.drc.geometry import extract,polygon_from_figure,placement_delta,apply_delta
from colayout_lite.drc.rdb import parse
from colayout_lite.geometry import shape_figure,ORIENT


@pytest.fixture
def tech():
    return TechnologyProfile(id='test',label='Foreign PDK',native_fingerprint='test-fp',dbu_per_micron=2000,grid=2,
        layers=[{'layer':x,'purpose':'drawing'} for x in ['A','B','C','W']],writable_lpps=(('A','drawing'),('B','drawing'),('W','drawing')),
        vias={'V':dict(kind='stdViaDef',layer1='A',layer2='B',cut_layer='C',implant1=None,implant2=None,
            defaults=dict(cutWidth=400,cutHeight=400,cutRows=1,cutColumns=1,cutSpacing=[400,400],
                layer1Enc=[100,100],layer2Enc=[100,100],layer1Offset=[0,0],layer2Offset=[0,0],originOffset=[0,0]))})


def workspace(tech,shapes):
    objects={str(i):Object(uid=str(i),native_id=str(i),kind=s.kind,shape=s,bbox=s.bbox) for i,s in enumerate(shapes)}
    return Workspace(profile_id=tech.id,baseline=Snapshot(library='L',cell='C',library_path='/test/L',session='s',counter='1',
        dirty=False,technology_fingerprint=tech.native_fingerprint,dbu_per_micron=tech.dbu_per_micron,grid=tech.grid,objects=objects))


def rect(x,y,xx,yy,layer='A'):return Shape(kind='rect',lpp=(layer,'drawing'),bbox=((x,y),(xx,yy)))
def profile(tech,*rules,**kw):return DrcProfile(id='test',technology_fingerprint=tech.native_fingerprint,rules=tuple(rules),**kw)
def rule(kind,value=.2,layer='A',**kw):return Rule(id=kind+'_'+layer,kind=kind,layer=layer,value=value,**kw)
ROI=Region(bbox=((-10000,-10000),(10000,10000)))


@pytest.mark.parametrize('kind,value,geometry,count',[
    ('width',.2,rect(0,0,1000,398),1),('width',.2,rect(0,0,1000,400),0),('width',.2,rect(0,0,1000,402),0),
    ('area',.1,rect(0,0,200,200),1),('area',.1,rect(0,0,1000,400),0)])
def test_width_area_threshold(tech,kind,value,geometry,count):
    w=workspace(tech,[geometry]);before=w.model_dump_json();result=run(w,tech,profile(tech,rule(kind,value)),ROI)
    assert len(result.markers)==count;assert w.model_dump_json()==before
    if count:assert result.markers[0].objects[0]['uid']=='0'


@pytest.mark.parametrize('gap,count',[(0,0),(-20,0),(398,1),(400,0),(402,0)])
def test_spacing_and_overlap_union(tech,gap,count):
    w=workspace(tech,[rect(0,0,1000,400),rect(0,400+gap,1000,800+gap)])
    r=run(w,tech,profile(tech,rule('spacing')),ROI);assert len(r.markers)==count
    if count:assert r.markers[0].measured_um==pytest.approx(gap/2000)


def test_boundary_neighbor_outside_roi_and_remote_outside_ignored(tech):
    w=workspace(tech,[rect(0,0,1000,400),rect(0,600,1000,1000),rect(20000,20000,20100,22000)])
    region=Region(bbox=((-100,-100),(1100,500)))
    r=run(w,tech,profile(tech,rule('spacing'),rule('width')),region)
    assert [m.rule_id for m in r.markers]==['spacing_A']
    assert {o['uid'] for o in r.markers[0].objects}=={'0','1'}


@pytest.mark.parametrize('kind,points,basis',[('path',((0,0),(1000,0),(1000,1000)),'perpendicular'),
    ('path',((0,0),(1000,1000)),'perpendicular'),('pathSeg',((0,0),(1000,0)),'perpendicular'),
    ('pathSeg',((0,0),(1000,1000)),'oa_diagonal')])
def test_path_actual_width(tech,kind,points,basis):
    s=Shape(kind=kind,points=points,width=200,lpp=('A','drawing'),width_basis=basis)
    result=run(workspace(tech,[s]),tech,profile(tech,rule('width')),ROI)
    assert result.markers
    assert result.markers[0].measured_um==pytest.approx(.1/(math.sqrt(2) if basis=='oa_diagonal' else 1))


@pytest.mark.parametrize('orientation',list(ORIENT))
def test_via_enclosures_and_orientation(tech,orientation):
    good=Shape(kind='stdVia',origin=(2000,3000),orientation=orientation,via_definition='V')
    cfg=profile(tech,rule('enclosure',.05,layer='C',other_layer='A'))
    assert not run(workspace(tech,[good]),tech,cfg,ROI).markers
    bad=good.model_copy(update={'via_parameters':{'layer1Enc':[0,0]}})
    result=run(workspace(tech,[bad]),tech,cfg,ROI);assert len(result.markers)==1
    assert result.markers[0].measured_um==0


def test_added_metal_can_fix_via_enclosure(tech):
    via=Shape(kind='stdVia',origin=(0,0),via_definition='V',via_parameters={'layer1Enc':[0,0]})
    cfg=profile(tech,rule('enclosure',.05,layer='C',other_layer='A'))
    assert not run(workspace(tech,[via,rect(-300,-300,300,300)]),tech,cfg,ROI).markers


def test_geometry_union_fixes_primitive_width(tech):
    w=workspace(tech,[rect(0,0,1000,200),rect(0,-200,1000,400)])
    assert not run(w,tech,profile(tech,rule('width')),ROI).markers


def test_well_assumption_warning_and_no_net_intent_trust(tech):
    a=rect(0,0,2000,2000,'W').model_copy(update={'net_intent':'same'})
    b=rect(2400,0,4400,2000,'W').model_copy(update={'net_intent':'same'})
    result=run(workspace(tech,[a,b]),tech,profile(tech,rule('spacing',.6,layer='W',severity='warning')),ROI)
    assert len(result.markers)==1 and result.markers[0].severity=='warning'


@pytest.mark.parametrize('orientation',list(ORIENT))
def test_instance_placement_geometry_delta(orientation):
    from shapely.geometry import box
    before=Placement(origin=(2000,3000),orientation='R90');after=Placement(origin=(-4000,-5000),orientation=orientation)
    local=box(0,0,1000,2000)
    initial=apply_delta(local,(*ORIENT['R90'],2000,3000))
    actual=apply_delta(initial,placement_delta(before,after));expected=apply_delta(local,(*ORIENT[orientation],-4000,-5000))
    assert actual.equals_exact(expected,1e-6)


def test_unknown_native_cache_is_reported_not_silently_excluded(tech):
    w=workspace(tech,[]);o=Object(uid='I',native_id='i',kind='inst',bbox=((0,0),(1000,1000)),placement=Placement(origin=(0,0)))
    w=w.model_copy(update={'baseline':w.baseline.model_copy(update={'objects':{'I':o}})})
    result=run(w,tech,profile(tech,rule('width')),ROI)
    assert not result.coverage['complete_for_configured_subset']
    assert result.coverage['scope']['native_instances_excluded']==0
    assert result.coverage['warnings']


def test_unsupported_polygon_width_is_outside_local_subset(tech):
    s=Shape(kind='polygon',lpp=('A','drawing'),points=((0,0),(1000,0),(1000,500),(500,1000),(0,1000)))
    r=run(workspace(tech,[s]),tech,profile(tech,rule('width')),ROI)
    assert r.coverage['complete_for_configured_subset']
    assert not r.markers and not r.coverage['warnings']


def test_cancellation(tech):
    def stop():raise LiteError('DRC_CANCELLED')
    with pytest.raises(LiteError,match='DRC_CANCELLED'):run(workspace(tech,[rect(0,0,200,200)]),tech,profile(tech,rule('width')),ROI,checkpoint=stop)


def test_result_stale_after_edit_and_rule_change(tech):
    e=Editor(workspace(tech,[rect(0,0,200,200)]),tech);cfg=profile(tech,rule('width'));result=run(e.w,tech,cfg,ROI)
    assert result.is_current(e.w,cfg)
    e.edit('0',bbox=((0,0),(1000,1000)));assert not result.is_current(e.w,cfg)
    assert not result.is_current(workspace(tech,[]),cfg)


@pytest.mark.parametrize('roi',[(0,0,0,1),(2,0,1,1),(0,0,'nan',1),(0,0,.00001,1)])
def test_invalid_regions(roi):
    with pytest.raises(ValueError):Region.from_um(roi,2000)


@pytest.mark.parametrize('value',[0,-1,float('nan'),float('inf')])
def test_invalid_thresholds(value):
    with pytest.raises(ValueError):rule('width',value)


def test_process_mismatch_no_fallback(tech):
    with pytest.raises(LiteError,match='MISMATCH'):profile(tech,rule('width')).check_technology(tech.model_copy(update={'native_fingerprint':'another'}))
    with pytest.raises(LiteError,match='LAYER_UNKNOWN'):profile(tech,rule('width',layer='M1')).check_technology(tech)


def test_rdb_precision_edges_region_and_original_geometry():
    text='TOP 1000\nR\n3 3 1 stamp\nrule text\np 1 4\n-100 -100\n100 -100\n100 100\n-100 100\ne 2 2\n0 0 100 0\n0 50 100 50\np 3 4\n500 500\n600 500\n600 600\n500 600\n'
    region=Region(bbox=((-300,-300),(300,300)))
    m,c=parse(text,region,2000);assert len(m)==2 and c['total_context_markers']==3
    assert m[0].bbox==((-200,-200),(200,200));assert m[1].edges[1]==(0,100,200,100)
    m,c=parse(text,region,2000,max_markers=1);assert len(m)==1 and c['truncated']


def test_calibre_hole_polygon_keeps_native_walk():
    text='TOP 1000\nBD\n1 1 0 stamp\np 1 10\n0 0\n1000 0\n1000 1000\n900 1000\n900 100\n100 100\n100 900\n900 900\n900 1000\n0 1000\n'
    m,c=parse(text,ROI,2000);assert len(m[0].points)==10


@pytest.mark.parametrize('text',['TOP 0','TOP 1000\nR\n1 1 0\np 1 4\n0 0',
    'TOP 1000\nR\n1 1 0\nCN cell 1','TOP 1000\nR\n1 1 0\np 1 3\nx y\n1 1\n0 1'])
def test_bad_rdb_fails_not_clean(text):
    with pytest.raises((LiteError,ValueError)):parse(text,ROI,2000)


def test_empty_rules_not_pass(tech):
    r=run(workspace(tech,[]),tech,profile(tech),ROI);assert not r.coverage['complete_for_configured_subset']


def test_marker_limit_disclosed(tech):
    r=run(workspace(tech,[rect(0,0,200,200),rect(1000,0,1200,200)]),tech,profile(tech,rule('width'),max_markers=1),ROI)
    assert len(r.markers)==1 and r.coverage['truncated']
