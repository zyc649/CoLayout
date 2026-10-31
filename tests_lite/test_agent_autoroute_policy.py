"""Human-published process permission gates route_region, not editing helpers."""
from types import SimpleNamespace

import pytest

from colayout_lite.agent_tools.session import AgentSession
from colayout_lite.model import LiteError
from colayout_lite.process_configuration import ProcessConfiguration
from colayout_lite.process_library import ProcessLibrary, write_json
from colayout_lite.process_package import ProcessPackage, encode, decode
from colayout_lite.process_api import invoke
from colayout_lite.regions.actions import RegionActions
from tests_lite.test_regions import region_editor, profile


@pytest.fixture
def service(tmp_path,profile):
    store=ProcessLibrary(tmp_path)
    path=tmp_path/'config/technologies/tech.json';profile.save(path)
    connection=tmp_path/'config/connection.json'
    write_json(connection,{'bridge_env':'.env','allowed_remote_root':'/workspace/design',
        'preferred_profile':profile.id,'profiles_directory':str(path.parent)})
    store.register(profile,path,connection,confirmed=True)
    return ProcessConfiguration(store)


def toggle(service,profile,enabled):
    package=service.load(profile.key)
    service.save_settings(profile.key,package.model_copy(update={'agent_autoroute_enabled':enabled}),package.fingerprint())


def test_legacy_defaults_off_and_human_settings_persist_per_process(service,profile):
    assert not service.agent_autoroute_enabled(profile)
    assert not service.load(profile.key).agent_autoroute_enabled
    toggle(service,profile,True)
    reopened=ProcessConfiguration(ProcessLibrary(service.store.root))
    assert reopened.agent_autoroute_enabled(profile)
    assert reopened.load(profile.key).agent_autoroute_enabled
    assert not reopened.agent_autoroute_enabled(profile.model_copy(update={'configuration_id':'other'}))
    assert not reopened.agent_autoroute_enabled(profile.model_copy(update={'native_fingerprint':'other'}))
    toggle(service,profile,False)
    assert not reopened.agent_autoroute_enabled(profile)


def test_package_roundtrip_preserves_explicit_flag_but_omission_is_disabled(profile):
    p=ProcessPackage(technology=profile)
    assert not decode(encode(p)).agent_autoroute_enabled
    assert 'agent_autoroute_enabled' not in p.model_dump(mode='json')
    assert decode(encode(p.model_copy(update={'agent_autoroute_enabled':True}))).agent_autoroute_enabled


def test_agent_cannot_enable_or_disable_permission_or_spoof_human_client(service,profile,monkeypatch):
    package=ProcessPackage(technology=profile)
    monkeypatch.setattr(ProcessPackage,'require_complete',lambda p:p) # No native configuration needed for proposal permission tests.
    def submit(raw):
        return invoke(service,SimpleNamespace(action='submit',package=raw,sample={'library':'L','cell':'C'},connection_id=None,
            project_root=None,verification_id=None),'human-settings','request')
    raw=package.model_dump(mode='json');raw['agent_autoroute_enabled']=True
    with pytest.raises(LiteError,match='AGENT_PERMISSION_UI_ONLY'):submit(raw)
    assert not service.store.drafts()
    toggle(service,profile,True)
    raw['agent_autoroute_enabled']=False
    with pytest.raises(LiteError,match='AGENT_PERMISSION_UI_ONLY'):submit(raw)
    result=submit(package.model_dump(mode='json')) # Omitted permission preserves human choice.
    path,record=service.proposal(result['proposal_id'])
    assert record['package']['agent_autoroute_enabled']
    original=path.read_bytes()
    toggle(service,profile,False)
    assert submit(package.model_dump(mode='json'))==result
    assert path.read_bytes()==original and not service.agent_autoroute_enabled(profile)


def test_live_discovery_and_execution_follow_permission_without_disabling_helpers(region_editor,service,tmp_path,monkeypatch):
    e=region_editor;rid=RegionActions(e).create((-1000,-1000,7000,7000),'region')
    session=AgentSession(e,None,tmp_path/'agent',autoroute_enabled=lambda:service.agent_autoroute_enabled(e.profile))
    try:
        def call(tool,args):return session.invoke(tool,args,client_id='layout')
        token=call('claim_region',{'region_id':rid,'agent_name':'layout'})['result']['session_token']
        names=lambda:{row['name'] for row in call('tools',{})['result']['tools']}
        assert 'route_region' not in names()
        edit=call('tools',{'tool':'edit_region'})['result']['tools'][0]['usage']['actions']
        assert {'arrange','align','create_auto_vias','create_multilayer_path'}<=edit.keys()
        before=e.w
        calls=[]
        monkeypatch.setattr(session.operations,'route_region',lambda lease,args:calls.append(args.action) or {'action':args.action})
        for action in ('generate','recheck','apply'):
            result=call('route_region',{'session_token':token,'action':action,'expected_revision':e.w.revision})
            assert result['error']['code']=='AGENT_AUTOROUTE_DISABLED'
        assert e.w is before and not calls and not session.jobs
        toggle(service,e.profile,True)
        assert 'route_region' in names()
        assert call('route_region',{'session_token':token,'action':'generate','expected_revision':e.w.revision})['ok']
        toggle(service,e.profile,False)
        assert 'route_region' not in names()
        assert call('route_region',{'session_token':token,'action':'apply','job_id':'old','candidate_id':'old'})['error']['code']=='AGENT_AUTOROUTE_DISABLED'
        # Existing jobs can still be inspected/discarded; no new work is granted.
        for action in ('status','discard'):
            assert call('route_region',{'session_token':token,'action':action,'job_id':'old'})['ok']
        assert calls==['generate','status','discard']
        from colayout_lite.autoroute.plugins import Registry
        assert Registry(tmp_path/'human.json').resolve(['builtin.astar']) # Human engine is unchanged.
    finally:session.close()


def test_missing_or_unconfirmed_registry_never_grants_access(service,profile):
    assert not service.agent_autoroute_enabled(None)
    entries=service.store.entries();entries[profile.key].update(agent_autoroute_enabled=True,confirmed=False)
    write_json(service.store.path,{'entries':entries})
    assert not service.agent_autoroute_enabled(profile)


def test_human_checkbox_roundtrip_changes_only_agent_permission(profile):
    from PySide6.QtCore import Qt,QPoint
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from colayout_lite.process_editor import ConfigurationEditor
    app=QApplication.instance() or QApplication([])
    widget=ConfigurationEditor()
    package=ProcessPackage(technology=profile)
    widget.set_package(package)
    widget.resize(1000,760);widget.show();app.processEvents()
    try:
        assert not widget.agent_autoroute.isChecked()
        original=widget.value()
        QTest.mouseClick(widget.agent_autoroute,Qt.MouseButton.LeftButton,pos=QPoint(8,widget.agent_autoroute.height()//2))
        changed=widget.value()
        assert changed.agent_autoroute_enabled and widget.is_dirty()
        assert changed.model_copy(update={'agent_autoroute_enabled':False})==original
        widget.set_package(changed)
        assert widget.agent_autoroute.isChecked() and not widget.is_dirty()
        QTest.mouseClick(widget.agent_autoroute,Qt.MouseButton.LeftButton,pos=QPoint(8,widget.agent_autoroute.height()//2))
        assert not widget.value().agent_autoroute_enabled
    finally:widget.close()


@pytest.mark.parametrize('mode',['enabled','disabled','missing_required','foreign_tool'])
def test_client_publication_accepts_only_the_optional_route_difference(tmp_path,monkeypatch,mode):
    from tools import publish_test_connection as publication
    names=set(publication.TOOLS)
    if mode=='disabled':names.remove('route_region')
    if mode=='missing_required':names.remove('edit_region')
    if mode=='foreign_tool':names.add('unrelated')
    path=tmp_path/'descriptor.json';path.write_text('{"url":"http://localhost"}')
    monkeypatch.setattr(publication,'AgentClient',lambda _:SimpleNamespace(call=lambda *a,**k:{'tools':[{'name':n} for n in names]}))
    if mode in ('enabled','disabled'):assert publication.probe(path)[1]==sorted(names)
    else:
        with pytest.raises(RuntimeError,match='contract differs'):publication.probe(path)
