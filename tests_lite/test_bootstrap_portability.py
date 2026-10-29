"""First-run diagnostics and client isolation use only synthetic local data."""
import json
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace
import pytest
from colayout_lite import bootstrap
from colayout_lite.model import LiteError
from colayout_lite.document import load_document

SOURCE=Path(__file__).resolve().parents[1]


@pytest.fixture
def installation(tmp_path,monkeypatch):
    root=tmp_path/'source with spaces';(root/'config').mkdir(parents=True)
    shutil.copyfile(SOURCE/'config/colayout_lite.example.json',root/'config/colayout_lite.example.json')
    monkeypatch.setattr(bootstrap,'ROOT',root)
    bootstrap.initialize()
    return root


def test_init_preserves_existing_document_and_does_not_invent_a_pdk(installation):
    data=bootstrap.settings();path=Path(data['document']);before=path.read_bytes()
    assert bootstrap.initialize()['existing']
    assert path.read_bytes()==before
    w,p=load_document(path)
    assert not w.baseline.objects and not p.writable_lpps and p.native_fingerprint=='unconfigured'
    assert Path(data['test_kit']).parent==installation.parent
    assert not Path(data['test_kit']).is_relative_to(installation)


def test_missing_host_is_actionable_without_network(installation,monkeypatch):
    monkeypatch.setattr(bootstrap.subprocess,'run',lambda *a,**k:pytest.fail('Unexpected SSH'))
    with pytest.raises(LiteError,match='SERVER_HOST_REQUIRED'):bootstrap.doctor()
    with pytest.raises(LiteError,match='SERVER_HOST_REQUIRED'):
        bootstrap.configure(user='designer',remote_root='/workspace/design')


@pytest.mark.parametrize('message,code',[
    ('Permission denied (publickey).','SSH_AUTH_REQUIRED'),
    ('Host key verification failed.','SSH_HOST_KEY_REVIEW_REQUIRED'),
    ('Connection timed out','SSH_UNREACHABLE')])
def test_ssh_failures_never_disable_host_verification(installation,monkeypatch,message,code):
    bootstrap.configure('layout-server.example.com','designer','/workspace/design')
    calls=[]
    def run(args,**kwargs):
        calls.append(args);return SimpleNamespace(returncode=255,stderr=message)
    monkeypatch.setattr(bootstrap.subprocess,'run',run)
    with pytest.raises(LiteError,match=code):bootstrap.doctor()
    assert 'BatchMode=yes' in calls[0] and not any('StrictHostKeyChecking=no' in a for a in calls[0])


def test_multiple_windows_require_selection_without_bootstrap(installation,monkeypatch):
    monkeypatch.setattr(bootstrap,'windows',lambda:[{'window_id':'0x1'},{'window_id':'0x2'}])
    monkeypatch.setattr(bootstrap,'bridge',lambda *a,**k:pytest.fail('Must ask before loading CIW'))
    result=bootstrap.connect()
    assert not result['connected'] and result['code']=='VIRTUOSO_SELECTION_REQUIRED'


@pytest.mark.parametrize('pid,working,expected',[(12,'/workspace/design',None),
    (99,'/workspace/design','VIRTUOSO_INSTANCE_MISMATCH'),(12,'/elsewhere','CONNECTED_PROJECT_MISMATCH')])
def test_connection_checks_selected_process_and_project(installation,monkeypatch,pid,working,expected):
    bootstrap.configure('layout-server.example.com','designer','/workspace/design')
    monkeypatch.setattr(bootstrap,'windows',lambda:[{'window_id':'0x1','display':':0'}])
    calls=[];monkeypatch.setattr(bootstrap,'bridge',lambda args,**k:calls.append(args) or '')
    native=SimpleNamespace(get_virtuoso_pid=lambda:pid,ssh_runner=SimpleNamespace(
        run_command=lambda *a,**k:SimpleNamespace(stdout='_NET_WM_PID(CARDINAL) = 12')))
    monkeypatch.setattr('colayout_lite.process_setup.inspect_live',lambda _:(native,{'working_directory':working,'layouts':[]}))
    if expected:
        with pytest.raises(LiteError,match=expected):bootstrap.connect('0x1')
    else:assert bootstrap.connect('0x1')['virtuoso_pid']==12
    assert calls==[['start'],['bootstrap','--window','0x1']]


def test_local_recovery_keeps_unknown_evidence_without_a_bridge_env(installation):
    from colayout_lite.sync_recovery import restore_pending_state
    from colayout_lite.transport import load_connection
    from colayout_lite.paths import ROOT
    w,p=load_document(bootstrap.settings()['document'])
    config=Path(w.connection_config)
    data=json.loads(config.read_text())
    # This is an isolated absolute runtime path, not a native connection.
    data['state_directory']=str(installation/'native')
    config.write_text(json.dumps(data),encoding='utf8')
    pending=installation/'native/workspaces'/f'{w.id}.json';pending.parent.mkdir(parents=True)
    saved=w.model_copy(update={'state':'indeterminate','last_result':{'request_id':'unchanged-request'}})
    saved.save(pending,portable=True)
    actual=restore_pending_state(w)
    assert actual.state=='indeterminate' and actual.last_result==saved.last_result
    with pytest.raises(LiteError,match='BRIDGE_ENV_MISSING'):load_connection(config)


def test_client_folder_update_preserves_pending_identity_and_custom_files(installation,monkeypatch):
    from tools import create_layout_agent as tool
    monkeypatch.setattr(tool,'ROOT',installation)
    shutil.copytree(SOURCE/'templates/layout-agent',installation/'templates/layout-agent')
    folder=installation.parent/'layout-only'
    assert not tool.create(folder,offline=True)['connected']
    sentinel=folder/'runtime/pending-request.json';sentinel.write_text('keep original')
    identity=folder/'runtime/client-state.json';identity.write_text('keep identity')
    custom=folder/'README.md';custom.write_text('user note')
    result=tool.create(folder,update=True,offline=True)
    assert sentinel.read_text()=='keep original' and identity.read_text()=='keep identity'
    assert custom.read_text()=='user note' and 'README.md' in result['preserved_custom_files']
    assert not any((folder/name).exists() for name in ('.env','colayout_lite','virtuoso-bridge-lite','.agents/skills/virtuoso'))


def test_nonempty_foreign_folder_is_not_overwritten(installation,monkeypatch):
    from tools import create_layout_agent as tool
    monkeypatch.setattr(tool,'ROOT',installation)
    folder=installation.parent/'existing';folder.mkdir();(folder/'work.txt').write_text('keep')
    with pytest.raises(ValueError,match='unmanaged'):tool.create(folder,offline=True)
    assert list(p.name for p in folder.iterdir())==['work.txt']
