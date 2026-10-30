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
    assert calls==[['start']] # Reuse never injects setup into an existing CIW.


def test_existing_environment_import_is_project_owned_and_preserves_source(installation,tmp_path):
    from dotenv import dotenv_values
    source=tmp_path/'shared.env'
    source.write_text('VB_REMOTE_HOST=layout-server.example.com\nVB_REMOTE_USER=designer\n'
        'VB_REMOTE_PORT=65432\nVB_LOCAL_PORT=65433\nVB_HOME=/shared/runtime\n'
        'VB_STATE_DIR=/shared/state\nVB_CLIENT_ID=someone-else\n'
        'VB_DAEMON_TOKEN=private-value\nVB_ALLOW_UNAUTHENTICATED_DAEMON=1\n')
    before=source.read_bytes()
    result=bootstrap.configure(existing_env=source,remote_root='/workspace/design')
    values=dotenv_values(result['environment'])
    assert Path(result['environment'])==installation/'.env'
    assert source.read_bytes()==before
    assert values['VB_REMOTE_PORT']=='65432'
    assert Path(values['VB_HOME'])==installation/'.colayout/bridge-runtime'
    assert Path(values['VB_STATE_DIR']).is_relative_to(installation)
    assert values['VB_CLIENT_ID']!='someone-else'
    assert values['VB_REMOTE_PORT_'+values['VB_PROFILE']]=='65432'
    assert 'private-value' not in (installation/'.env').read_text()
    assert 'VB_ALLOW_UNAUTHENTICATED_DAEMON' not in values
    assert not (installation/'.colayout/bridge-runtime').exists() # No copied state.
    cfg=json.loads((installation/'config/colayout_lite.json').read_text())
    assert Path(cfg['bridge_env'])==installation/'.env'
    with pytest.raises(LiteError,match='CONNECTION_EXISTS'):
        bootstrap.configure(existing_env=source,remote_root='/workspace/design')
    assert source.read_bytes()==before


def test_two_installations_have_distinct_state_and_legacy_profile_names(tmp_path,monkeypatch):
    from colayout_lite.bridge_environment import project_environment,select_environment
    from virtuoso_bridge import env
    from virtuoso_bridge.profile import resolve_profile
    from virtuoso_bridge.transport.tunnel import SSHClient
    from virtuoso_bridge.transport import tunnel
    first=project_environment(tmp_path/'one',host='layout-server.example.com',user='designer')
    second=project_environment(tmp_path/'two',host='layout-server.example.com',user='designer')
    assert first['VB_PROFILE']!=second['VB_PROFILE']
    assert first['VB_HOME']!=second['VB_HOME']
    assert first['VB_CLIENT_ID']!=second['VB_CLIENT_ID']
    global_state=tmp_path/'legacy';global_state.mkdir()
    (global_state/'state.json').write_text('{"mode":"local","port":9999}')
    monkeypatch.setattr(tunnel,'legacy_cache_state_file',lambda profile=None:
        global_state/(f'state_{profile}.json' if profile else 'state.json'))
    monkeypatch.setattr(env,'_RUNTIME_ENV_FILE',None)
    for key in second:monkeypatch.setenv(key,'ambient-value')
    path=tmp_path/'project.env'
    path.write_text('\n'.join(k+'='+json.dumps(v) for k,v in second.items()))
    select_environment(path)
    assert resolve_profile()==second['VB_PROFILE']
    assert SSHClient.read_state(resolve_profile()) is None
    assert json.loads((global_state/'state.json').read_text())['port']==9999


def test_explicit_source_profile_preserves_split_hosts_without_other_profiles(installation,tmp_path):
    from dotenv import dotenv_values
    source=tmp_path/'profiles.env'
    source.write_text('VB_GUI_HOST=unrelated.example.com\nVB_REMOTE_USER=other\n'
        'VB_REMOTE_HOST_lab=compute.example.com\nVB_GUI_HOST_lab=gui.example.com\n'
        'VB_DEPLOY_HOST_lab=deploy.example.com\nVB_REMOTE_USER_lab=designer\n'
        'VB_REMOTE_PORT_lab=65432\nVB_JUMP_HOST_lab=bastion.example.com\n'
        'VB_REMOTE_SCRATCH_ROOT=/shared/scratch\nVB_REMOTE_HOST_other=other.example.com\n')
    result=bootstrap.configure(existing_env=source,profile='lab',remote_root='/workspace/design')
    values=dotenv_values(result['environment'])
    assert values['VB_GUI_HOST']=='gui.example.com'
    assert values['VB_REMOTE_HOST']=='compute.example.com'
    assert values['VB_DEPLOY_HOST']=='deploy.example.com'
    assert values['VB_JUMP_HOST']=='bastion.example.com'
    assert values['VB_REMOTE_SCRATCH_ROOT']=='/shared/scratch'
    assert values['VB_REMOTE_USER']=='designer'
    assert 'VB_REMOTE_HOST_other' not in values and 'VB_REMOTE_HOST_lab' not in values


@pytest.mark.parametrize('body,profile,code',[
    ('VB_REMOTE_HOST_lab=host\n',None,'BRIDGE_PROFILE_REQUIRED'),
    ('VB_REMOTE_HOST=host\nVB_REMOTE_USER=user\n',None,'BRIDGE_REMOTE_PORT_REQUIRED'),
    ('VB_REMOTE_HOST=host\nVB_REMOTE_USER=user\nVB_REMOTE_PORT=bad\n',None,'INVALID_BRIDGE_PORT'),
    ('VB_REMOTE_HOST=${OTHER_HOST}\nVB_REMOTE_USER=user\nVB_REMOTE_PORT=65432\n',None,'INVALID_BRIDGE_SETTING'),
    ('VB_REMOTE_HOST_lab=host\n','missing','BRIDGE_PROFILE_UNKNOWN')])
def test_import_rejects_ambiguous_or_incomplete_target(installation,tmp_path,body,profile,code):
    source=tmp_path/'source.env';source.write_text(body)
    with pytest.raises(LiteError,match=code):
        bootstrap.configure(existing_env=source,profile=profile,remote_root='/workspace/design')
    assert not (installation/'.env').exists() and source.read_text()==body


def test_reuse_failure_never_bootstraps_or_restarts(installation,monkeypatch):
    bootstrap.configure('layout-server.example.com','designer','/workspace/design')
    monkeypatch.setattr(bootstrap,'windows',lambda:[{'window_id':'0x1'}])
    calls=[];monkeypatch.setattr(bootstrap,'bridge',lambda args,**k:calls.append(args))
    def failed(_):raise LiteError('BRIDGE_INSPECT_FAILED','Authentication failure or unknown native outcome')
    monkeypatch.setattr('colayout_lite.process_setup.inspect_live',failed)
    with pytest.raises(LiteError,match='BRIDGE_INSPECT_FAILED'):bootstrap.connect('0x1')
    assert calls==[['start']]


def test_first_ciw_load_requires_explicit_bootstrap(installation,monkeypatch):
    bootstrap.configure('layout-server.example.com','designer','/workspace/design')
    monkeypatch.setattr(bootstrap,'windows',lambda:[{'window_id':'0x1'}])
    calls=[];monkeypatch.setattr(bootstrap,'bridge',lambda args,**k:calls.append(args))
    native=SimpleNamespace(get_virtuoso_pid=lambda:12,ssh_runner=SimpleNamespace(
        run_command=lambda *a,**k:SimpleNamespace(stdout='_NET_WM_PID(CARDINAL) = 12')))
    monkeypatch.setattr('colayout_lite.process_setup.inspect_live',lambda _:(native,{'working_directory':'/workspace/design'}))
    assert bootstrap.connect('0x1',bootstrap=True)['connected']
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
