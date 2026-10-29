"""Configured MIM contacts: arbitrary PDK names, exact cuts, native exclusion."""
import pytest
from shapely.geometry import box
from colayout_lite.model import Shape,Object,Placement,LiteError
from colayout_lite.materials import Physical
from colayout_lite.drc.mim_config import MimCapacitor
from colayout_lite.drc.mim_vias import run as check_vias
from colayout_lite.drc.local import run
from colayout_lite.drc.reporting import report_payload
from tests_lite.test_drc import tech,workspace,profile,rule,ROI


def configured(tech,purpose='drawing'):
    p=tech.model_copy(update={'layers':[
        {'layer':'A','purpose':'drawing','material':'metal'},
        {'layer':'B','purpose':'drawing','material':'metal'},
        {'layer':'C','purpose':'drawing','material':'cut'},
        {'layer':'plate','purpose':purpose,'material':'unknown'}]})
    mim=MimCapacitor(status='configured',lpp=('plate',purpose),lower_metal='A',upper_metal='B',source='actual process evidence')
    d=profile(p,rule('width',value=.01),mim_capacitor=mim)
    return p,d


def mask(bbox=((-1000,-1000),(1000,1000)),purpose='drawing'):
    return Shape(kind='rect',lpp=('plate',purpose),bbox=bbox)


def via(origin=(0,0),**kw):return Shape(kind='stdVia',origin=origin,via_definition='V',**kw)


@pytest.mark.parametrize('rename',[False,True])
def test_pdk_names_are_configured_and_via_array_emits_one_error(tech,rename):
    p,d=configured(tech);shapes=[mask(),via(via_parameters={'cutRows':2,'cutColumns':2})]
    if rename:
        names={'A':'lower_copper','B':'upper_aluminium','C':'hole99','plate':'cap_dielectric'}
        vd={**p.vias['V'],'layer1':names['B'],'layer2':names['A'],'cut_layer':names['C']}
        p=p.model_copy(update={'layers':[{**r,'layer':names[r['layer']]} for r in p.layers],
            'vias':{'junction':vd},'writable_lpps':((names['A'],'drawing'),(names['B'],'drawing'))})
        d=d.model_copy(update={'rules':(rule('width',value=.01,layer=names['A']),),
            'mim_capacitor':d.mim_capacitor.model_copy(update={'lpp':(names['plate'],'drawing'),'lower_metal':names['A'],'upper_metal':names['B']})})
        shapes=[shapes[0].model_copy(update={'lpp':(names['plate'],'drawing')}),shapes[1].model_copy(update={'via_definition':'junction'})]
    w=workspace(p,shapes);before=w.model_dump_json();r=run(w,p,d,ROI)
    hits=[m for m in r.markers if m.rule_id=='MIM_VIA_BLOCKED']
    assert len(hits)==1 and hits[0].severity=='error' and hits[0].details['overlapping_cuts']==4
    assert hits[0].objects[0]['uid']=='1' and hits[0].details['mim_owners']==['0']
    assert report_payload(r)['counts']['technology_errors']>=1 and w.model_dump_json()==before


@pytest.mark.parametrize('x,expected',[(0,1),(1199,1),(1200,0),(1250,0),(2000,0)])
def test_cut_overlap_not_metal_enclosure_or_touching(tech,x,expected):
    p,d=configured(tech);w=workspace(p,[mask(),via((x,0))]);r=run(w,p,d,ROI)
    assert sum(m.rule_id=='MIM_VIA_BLOCKED' for m in r.markers)==expected


def test_purpose_other_pairs_and_old_configuration(tech):
    p,d=configured(tech,purpose='marker');w=workspace(p,[mask(),via()])
    assert not any(m.rule_id=='MIM_VIA_BLOCKED' for m in run(w,p,d,ROI).markers)
    w=workspace(p,[mask(purpose='marker'),via()])
    assert any(m.rule_id=='MIM_VIA_BLOCKED' for m in run(w,p,d,ROI).markers)
    for settings in (MimCapacitor(),MimCapacitor(status='unsupported')):
        assert not any(m.rule_id=='MIM_VIA_BLOCKED' for m in run(w,p,d.model_copy(update={'mim_capacitor':settings}),ROI).markers)
    # A stack's lower level must not be confused with the configured crossing.
    vd={**p.vias['V'],'layer1':'Z','layer2':'A','cut_layer':'othercut'}
    p=p.model_copy(update={'vias':{**p.vias,'LOW':vd}})
    w=workspace(p,[mask(purpose='marker'),via().model_copy(update={'via_definition':'LOW'})])
    assert not any(m.rule_id=='MIM_VIA_BLOCKED' for m in run(w,p,d,ROI).markers)


def test_native_internal_vias_exempt_but_added_via_over_leaf_cap_is_not(tech):
    p,d=configured(tech);w=workspace(p,[via()]);external=w.baseline.objects['0']
    native=Object(uid='cap',native_id='cap',kind='inst',placement=Placement(origin=(0,0)),bbox=((-1000,-1000),(1000,1000)))
    physical=[Physical('cap','plate',box(-1000,-1000,1000,1000),True),
              Physical('cap','C',box(-200,-200,200,200),True)]
    objects={'cap':native,'0':external}
    assert not check_vias(w,p,d.mim_capacitor,physical,objects,{'cap'},box(-2000,-2000,2000,2000))[0]
    hits,_=check_vias(w,p,d.mim_capacitor,physical,objects,{'cap','0'},box(-2000,-2000,2000,2000))
    assert len(hits)==1 and hits[0].details['via_uid']=='0'
    assert hits[0].details['mim_owners']==['cap']
    # Parent checks exclude child-owned via objects, not merely their cuts.
    assert not check_vias(w,p,d.mim_capacitor,physical,objects,{'cap'},box(-2000,-2000,2000,2000))[0]
    assert not check_vias(w,p,d.mim_capacitor,physical,objects,{'0'},box(1000,1000,2000,2000))[0]


def test_truncation_and_rotation_are_preserved(tech):
    p,d=configured(tech);w=workspace(p,[mask(),via(orientation='R90'),via((50,50))])
    r=run(w,p,d.model_copy(update={'max_markers':1}),ROI)
    assert len(r.markers)==1 and r.coverage['truncated']
    assert r.coverage['mim_via_check']['truncated']


@pytest.mark.parametrize('update,code',[
    ({'lpp':('absent','drawing')},'MIM_LAYER_UNKNOWN'),
    ({'lower_metal':'missing'},'MIM_METAL_UNKNOWN'),
    ({'lower_metal':'B','upper_metal':'A'},'MIM_METAL_ORDER')])
def test_configuration_validation_uses_actual_technology(tech,update,code):
    p,d=configured(tech);p=p.model_copy(update={'editor_defaults':{'metal_stack':['A','B']}})
    d=d.model_copy(update={'mim_capacitor':d.mim_capacitor.model_copy(update=update)})
    with pytest.raises(LiteError,match=code):d.check_technology(p)


def test_unknown_is_not_silently_unsupported_or_approved():
    with pytest.raises(LiteError,match='MIM_CONFIRMATION_REQUIRED'):MimCapacitor().require_reviewed()
    with pytest.raises(ValueError):MimCapacitor(status='configured',lpp=('plate','drawing'),lower_metal='A',upper_metal='B')
    MimCapacitor(status='unsupported').require_reviewed()


def test_polygon_mask_uses_material_not_its_bounding_box(tech):
    p,d=configured(tech)
    shape=Shape(kind='polygon',lpp=('plate','drawing'),points=((0,0),(1000,0),(1000,200),(200,200),(200,1000),(0,1000)))
    w=workspace(p,[shape,via((700,700))])
    assert not any(m.rule_id=='MIM_VIA_BLOCKED' for m in run(w,p,d,ROI).markers)
