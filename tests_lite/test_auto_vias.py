"""Dense, checked via arrays include real neighbours and never guess net ownership."""
from copy import deepcopy
import pytest
from colayout_lite.model import LiteError,Shape
from colayout_lite.local_models import LocalData,LocalPin
from colayout_lite.editor import Editor,projected
from colayout_lite.drc.models import DrcProfile,Rule
from colayout_lite.layout_helpers.service import execute
from tests_lite.test_agent_connectivity import tech,workspace,rect


def via_rules(p):
    layers={row['layer'] for row in p.layers if row.get('material') in ('metal','cut')}
    rules=[Rule(id=layer+'.'+kind,kind=kind,layer=layer,value=.04) for layer in layers for kind in ('width','spacing')]
    rules += [Rule(id=name+'.enc.'+metal,kind='enclosure',layer=v['cut_layer'],other_layer=metal,value=.02)
              for name,v in p.vias.items() if name!='contact' for metal in (v['layer1'],v['layer2'])]
    return DrcProfile(id='test',technology_fingerprint=p.native_fingerprint,rules=tuple(rules))


def landing(p,start='M1',end='M2',*,foreign=False,known=True):
    shapes=[rect(0,0,1000,200,start),rect(0,0,1000,200,end)]
    pins={}
    if known:
        for i,layer in enumerate((start,end)):
            pins[str(i)]=LocalPin(id=str(i),name='P'+str(i),net='N',lpp=(layer,'drawing'),bbox=((0,0),(80,80)))
    if foreign:
        shapes.append(rect(0,0,1000,200,'M2'))
        pins['foreign']=LocalPin(id='foreign',name='OTHER',net='OTHER',lpp=('M2','drawing'),bbox=((0,0),(80,80)))
    w=workspace(p,shapes).model_copy(update={'local_data':LocalData(pins=pins)})
    return Editor(w,p)


def test_long_overlap_fills_many_cuts_checked_then_reuses_without_duplicates(tech):
    e=landing(tech);before=e.w;rules=via_rules(tech)
    args={'bounds_um':[0,0,1,.2],'start_layer':'M1','end_layer':'M2','net_intent':'N'}
    result=execute(e,'create_auto_vias',args,rules=rules)
    assert result['total_cuts']==24 and result['net_confirmed'] and result['internal_connected']
    assert result['search']['local_drc_checks']>=1 and len(result['created_uids'])==1
    after=e.w
    again=execute(e,'create_auto_vias',args,rules=rules)
    assert not again['created_uids'] and again['reused_uids']==result['created_uids']
    assert e.w is after
    e.undo();assert projected(e.w)==projected(before)


def test_narrow_or_unknown_access_leaves_no_partial_edit(tech):
    e=landing(tech);before=e.w
    with pytest.raises(LiteError,match='AUTOVIA_NO_LEGAL_ARRAY'):
        execute(e,'create_auto_vias',{'bounds_um':[0,0,.06,.06],'start_layer':'M1','end_layer':'M2','net_intent':'N'},rules=via_rules(tech))
    assert e.w is before
    e=landing(tech,known=False);before=e.w
    with pytest.raises(LiteError,match='AUTOVIA_NET_UNRESOLVED'):
        execute(e,'create_auto_vias',{'bounds_um':[0,0,1,.2],'start_layer':'M1','end_layer':'M2','net_intent':'N'},rules=via_rules(tech))
    assert e.w is before


def three_layers(tech):
    via=deepcopy(tech.vias['V12']);via.update(layer1='M2',layer2='M3',cut_layer='V2')
    return tech.model_copy(update={'layers':tech.layers+[{'layer':'M3','purpose':'drawing','material':'metal'},{'layer':'V2','purpose':'drawing','material':'cut'}],
        'writable_lpps':tech.writable_lpps+(('M3','drawing'),),'vias':{**tech.vias,'V23':via}})


def test_multilevel_checks_every_level_and_rejects_intermediate_short(tech):
    p=three_layers(tech);e=landing(p,'M1','M3');args={'bounds_um':[0,0,1,.2],'start_layer':'M1','end_layer':'M3','net_intent':'N'}
    result=execute(e,'create_auto_vias',args,rules=via_rules(p))
    assert len(result['levels'])==2 and all(r['cuts']>=2 for r in result['levels'])
    e=landing(p,'M1','M3',foreign=True);before=e.w
    with pytest.raises(LiteError,match='AUTOVIA_SHORT_OR_UNKNOWN_CONTACT'):
        execute(e,'create_auto_vias',args,rules=via_rules(p))
    assert e.w is before


def test_manual_via_array_parameters_remain_available(tech):
    from colayout_lite.actions import Actions
    e=landing(tech)
    uid=Actions(e).execute('create_via',{'definition':'V12','x':.5,'y':.1,'via_parameters':{'cutRows':1,'cutColumns':3}}).uid
    params=tech.effective_via(e.object(uid).shape)
    assert (params['cutRows'],params['cutColumns'])==(1,3)


def test_explicit_floating_target_needs_real_pin_after_connection(tech):
    e=landing(tech)
    e.w=e.w.model_copy(update={'local_data':LocalData(pins={'0':e.w.local_data.pins['0']})})
    result=execute(e,'create_auto_vias',{'bounds_um':[0,0,1,.2],'start_layer':'M1','end_layer':'M2',
        'net_intent':'N','targets':['0','1']},rules=via_rules(tech))
    assert result['net_confirmed']
    e=landing(tech,known=False);before=e.w
    with pytest.raises(LiteError,match='AUTOVIA_NET_UNRESOLVED'):
        execute(e,'create_auto_vias',{'bounds_um':[0,0,1,.2],'start_layer':'M1','end_layer':'M2',
            'net_intent':'N','targets':['0','1']},rules=via_rules(tech))
    assert e.w is before
