"""Geometry helpers preserve order, exact spacing, parameters and undo semantics."""
import pytest
from colayout_lite.editor import Editor,projected
from colayout_lite.model import Object,Placement,LiteError
from colayout_lite.geometry import box,transform
from colayout_lite.regions.query import object_bounds
from colayout_lite.layout_helpers.service import execute
from colayout_lite.pin_geometry import pin_geometry
from tests_lite.test_agent_connectivity import tech,workspace


@pytest.mark.parametrize('direction',['horizontal','vertical'])
def test_bus_uses_default_layer_width_exact_gap_and_one_undo(tech,direction):
    p=tech.model_copy(update={'editor_defaults':{'widths_um':{'M1':.12,'M2':.24}}})
    e=Editor(workspace(p),p);before=e.w
    result=execute(e,'create_bus',{'lpp':['M2','drawing'],'x':.1,'y':.2,'length':2,'count':5,'spacing':.3,'direction':direction})
    assert result['width_um']==.24 and len(result['created_uids'])==5
    bounds=[object_bounds(e.w,e.object(uid),p) for uid in result['created_uids']]
    axis=1 if direction=='horizontal' else 0
    assert all(b[0][axis]-a[1][axis]==pytest.approx(300) for a,b in zip(bounds,bounds[1:]))
    e.undo();assert e.w.operations==before.operations


def many_instances(tech,count=91):
    objects={};pins=[]
    for i in range(count):
        uid=f'M{i}';origin=(i*1000,0);orientation='R90' if i%2 else 'R0';tr=transform(origin,orientation)
        bounds=box(((-50,-20),(250+20*(i%3),380)),tr)
        objects[uid]=Object(uid=uid,native_id=uid,kind='inst',bbox=bounds,
            placement=Placement(origin=origin,orientation=orientation),attributes={'parameters':[['fingers',str(i+1)]]})
        pins.append({'instance_uid':uid,'terminal':'D','kind':'rect','lpp':['M1','drawing'],
                     'local_bbox':[[0,0],[50,50]],'local_geometry':{},'transform':tr})
    return workspace(tech,objects=objects,pins=pins)


def test_91_instances_arrange_by_body_bounds_zero_gap_and_pins_follow(tech):
    w=many_instances(tech);e=Editor(w,tech);uids=list(w.baseline.objects)
    result=execute(e,'arrange',{'uids':uids,'direction':'horizontal','align':'bottom','spacing':0,'x':0,'y':10})
    bounds=[object_bounds(e.w,e.object(uid),tech) for uid in uids]
    assert all(a[1][0]==b[0][0] for a,b in zip(bounds,bounds[1:]))
    assert all(b[0][1]==10000 for b in bounds)
    assert result['moved_uids']==uids
    for pin in w.baseline.pins:
        uid=pin['instance_uid'];old=w.baseline.objects[uid];new=e.object(uid)
        assert old.attributes==new.attributes and old.placement.orientation==new.placement.orientation
        g=pin_geometry(pin,old.placement,new.placement)
        assert g.is_valid and not g.is_empty
    e.undo();assert projected(e.w)==projected(w)


def test_grid_empty_slots_alignment_and_atomic_off_grid_rejection(tech):
    w=many_instances(tech,4);e=Editor(w,tech)
    result=execute(e,'arrange',{'rows':[['M0',{'width':.5,'height':.5},'M1'],['M3','M2']],
        'align':'bottom','spacing':.1,'row_spacing':.2,'x':0,'y':0})
    assert len(result['empty_slots_um'])==1 and len(projected(e.w))==4
    ref=object_bounds(e.w,e.object('M0'),tech)[0][1]/1000
    execute(e,'align',{'uids':['M2','M3'],'edge':'bottom','reference_uid':'M0'})
    assert all(object_bounds(e.w,e.object(uid),tech)[0][1]/1000==ref for uid in ('M2','M3'))
    before=e.w
    with pytest.raises(LiteError):execute(e,'align',{'uids':['M2','M3'],'edge':'left','coordinate':.001})
    assert e.w is before
