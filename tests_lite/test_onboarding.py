import json
from types import SimpleNamespace
import pytest
from tests_lite.test_kernel import profile
from colayout_lite import onboarding
from colayout_lite.technology import TechnologyProfile
from colayout_lite.model import LiteError


@pytest.fixture
def adapter(tmp_path,monkeypatch):
    monkeypatch.setattr(onboarding,'ROOT',tmp_path)
    path=tmp_path/'connection.json';config={'profiles_directory':'profiles','bridge_env':'.env'}
    path.write_text(json.dumps(config))
    return SimpleNamespace(native=SimpleNamespace(config_path=path,config=config))


def test_save_exposes_policy_defaults_and_selects_profile(adapter,profile):
    p,path=onboarding.save_profile(adapter,profile,name='TestProcess',writable_lpps=[['wire_b','drawing']],defaults={'layer':['wire_b','drawing'],'width_um':.2,'via_definition':'JOIN'})
    saved=TechnologyProfile.model_validate_json(path.read_text(encoding='utf-8'))
    assert saved.writable_lpps==(('wire_b','drawing'),) and saved.editor_defaults['width_um']==.2
    assert json.loads(adapter.native.config_path.read_text())['preferred_profile']=='TestProcess'
    assert saved.vias==profile.vias and saved.native_fingerprint==profile.native_fingerprint


def test_resave_same_process_does_not_create_ambiguous_files(adapter,profile):
    p,path=onboarding.save_profile(adapter,profile,name='A',writable_lpps=profile.writable_lpps,defaults={})
    p2,path2=onboarding.save_profile(adapter,p,name='A',writable_lpps=[['wire_a','drawing']],defaults={})
    assert path==path2 and len(list(path.parent.glob('*.json')))==1


@pytest.mark.parametrize('defaults',[{'layer':['missing','drawing']},{'width_um':.0001},{'width_um':-1},{'via_definition':'missing'}])
def test_invalid_settings_do_not_change_active_connection(adapter,profile,defaults):
    original=adapter.native.config_path.read_bytes()
    with pytest.raises(ValueError):onboarding.save_profile(adapter,profile,name='Bad',writable_lpps=profile.writable_lpps,defaults=defaults)
    assert adapter.native.config_path.read_bytes()==original


def test_a_name_cannot_silently_replace_another_native_process(adapter,profile):
    onboarding.save_profile(adapter,profile,name='A',writable_lpps=profile.writable_lpps,defaults={})
    with pytest.raises(LiteError,match='PROFILE_NAME_IN_USE'):
        onboarding.save_profile(adapter,profile.model_copy(update={'native_fingerprint':'different'}),name='A',writable_lpps=profile.writable_lpps,defaults={})
