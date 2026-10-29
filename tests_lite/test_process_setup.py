import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from colayout_lite.model import Object,Shape,LiteError
from colayout_lite.process_setup import metal_pair,measure_single_via,settings_profile,policy_key,confirm
from colayout_lite.process_library import ProcessLibrary,write_json
from tests_lite.test_kernel import profile,editor


def sample(profile,monkeypatch,*,size=800,upper=900,height=None,overrides=None,group=None):
    o=Object(uid='v',native_id='v',kind='stdVia',shape=Shape(kind='stdVia',via_definition='JOIN',origin=(0,0),via_parameters=overrides or {}),group_uid=group)
    figures={'v':[dict(kind='rect',style='wire_a/drawing',bbox=((0,0),(size,height or size))),dict(kind='rect',style='wire_b/drawing',bbox=((0,0),(upper,upper)))]}
    monkeypatch.setattr('colayout_lite.scene.figures_by_owner',lambda *a,**k:(figures,{}))
    return SimpleNamespace(objects={'v':o}),figures


def test_stack_uses_native_edges_not_lexicographic_names(profile):
    assert metal_pair(profile)==('wire_a','wire_b')
    data=profile.model_dump();data['layers'].append(dict(layer='first_alphabetically',purpose='drawing',material='metal'))
    with pytest.raises(LiteError,match='AMBIGUOUS'):metal_pair(type(profile).model_validate(data))
    assert metal_pair(type(profile).model_validate(data),('wire_a','wire_b'))==('wire_a','wire_b')


def test_width_measures_actual_m1_metal_not_cut_or_default(profile,monkeypatch):
    s,_=sample(profile,monkeypatch)
    m=measure_single_via(s,profile,metal_pair(profile))
    assert m['width_um']==.4 and m['width_dbu']==800
    assert m['metal_rectangles']['wire_b']['side_dbu']==900
    assert m['width_dbu']!=profile.vias['JOIN']['defaults']['cutWidth']


@pytest.mark.parametrize('kwargs',[{'overrides':{'cutRows':2}},{'group':'guard'}])
def test_unsuitable_sample_is_rejected_not_guessed(profile,monkeypatch,kwargs):
    s,_=sample(profile,monkeypatch,**kwargs)
    with pytest.raises(LiteError,match='SAMPLE_SINGLE_VIA_REQUIRED'):measure_single_via(s,profile,metal_pair(profile))


def test_rectangular_via_pads_preserve_dimensions_and_use_short_side(profile,monkeypatch):
    s,_=sample(profile,monkeypatch,height=600)
    result=measure_single_via(s,profile,metal_pair(profile))
    assert result['width_dbu']==600
    assert result['metal_rectangles']['wire_a']['size_dbu']==[800,600]
    assert result['metal_rectangles']['wire_a']['width_basis']=='short_side'


def test_round_up_odd_manufacturing_grid_and_report_it(profile,monkeypatch):
    p=profile.model_copy(update={'grid':5});s,_=sample(p,monkeypatch,size=385)
    m=measure_single_via(s,p,metal_pair(p))
    assert m['width_dbu']==385 and m['suggested_width_um']==390/2000 and m['rounded_to_path_grid']


def test_multiple_different_single_vias_require_explicit_choice(profile,monkeypatch):
    s,f=sample(profile,monkeypatch);s.objects['v2']=s.objects['v'].model_copy(update={'uid':'v2'})
    f['v2']=[dict(x,bbox=((0,0),(1000,1000))) for x in f['v']]
    with pytest.raises(LiteError,match='SAMPLE_VIA_AMBIGUOUS'):measure_single_via(s,profile,metal_pair(profile))
    assert measure_single_via(s,profile,metal_pair(profile),'v2')['width_dbu']==1000


def proposal(profile):
    return {'profile':profile.model_dump(),'metal_pair':['wire_a','wire_b'],'measurement':{'definition':'JOIN'}}


def test_user_confirms_width_and_layers_but_default_layer_stays_m1(profile):
    d=proposal(profile);p=settings_profile(d,'Named',.4,profile.writable_lpps)
    assert p.editor_defaults['layer']==('wire_a','drawing') and p.id=='Named'
    with pytest.raises(LiteError,match='M1_MUST_BE_WRITABLE'):settings_profile(d,'Named',.4,[['wire_b','drawing']])
    with pytest.raises(ValueError):settings_profile(d,'Named',.4001,profile.writable_lpps)
    assert policy_key(p)==policy_key(p.model_copy(update={'id':'Other','label':'Other'}))
    assert policy_key(p)!=policy_key(settings_profile(d,'Named',.5,profile.writable_lpps))


def test_failed_revalidation_never_publishes_configuration(profile,tmp_path,monkeypatch):
    p=settings_profile(proposal(profile),'P',.4,profile.writable_lpps)
    data={**proposal(profile),'status':'ready_for_confirmation','validation':{'status':'passed','policy_key':'old'}}
    path=tmp_path/'proposal.json';write_json(path,data);before=path.read_bytes()
    def fail(*args):raise LiteError('VALIDATION_FAILED')
    monkeypatch.setattr('colayout_lite.process_setup.validate',fail)
    with pytest.raises(LiteError):confirm(path,p,store=ProcessLibrary(tmp_path))
    assert not (tmp_path/'config/process-library.json').exists() and path.read_bytes()==before


def test_registry_reopens_saved_process_and_pending_workspace(profile,editor,tmp_path):
    store=ProcessLibrary(tmp_path);pp=tmp_path/'profile.json';profile.save(pp)
    cp=tmp_path/'config/connection.json';write_json(cp,{'bridge_env':'.env'})
    key=store.register(profile,pp,cp,confirmed=True)
    editor.create(Shape(kind='rect',lpp=profile.writable_lpps[0],bbox=((0,0),(100,100))))
    w=editor.w.model_copy(update={'connection_config':str(cp.resolve())});store.remember(w)
    entry,p,reopened=ProcessLibrary(tmp_path).load(key)
    assert reopened.operations==w.operations and reopened.baseline.semantic()==w.baseline.semantic()
    assert entry['confirmed'] and p==profile
    other=tmp_path/'other-connection.json';write_json(other,{'bridge_env':'.env'})
    store.register(profile,pp,other)
    assert store.load(key)[2] is None # Never use another project's workspace.


def test_confirmation_rejects_an_already_published_proposal(profile,tmp_path):
    path=tmp_path/'proposal.json';write_json(path,{'status':'confirmed'})
    with pytest.raises(LiteError,match='ALREADY_CONFIRMED'):confirm(path,profile,store=ProcessLibrary(tmp_path))
