"""Portable installation state and explicit, diagnosable connection setup."""
import argparse
import json
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import subprocess
import sys

from .paths import ROOT
from .model import LiteError
from .transactions import write_json_atomic


def installation_path():
    return ROOT / '.colayout/installation.json'


def default_agent_folder():
    # A sibling avoids inheriting this source project's maintenance skills.
    return ROOT.parent / (ROOT.name+'-layout-agent')

def settings():
    path = installation_path()
    if not path.is_file():
        raise LiteError('SETUP_REQUIRED', 'Run setup.ps1 first / 请先执行 setup.ps1。')
    return json.loads(path.read_text(encoding='utf8'))


def initialize():
    """Create an empty local workspace, never an invented PDK or live layout."""
    path = installation_path()
    if path.exists():
        data = settings()
        if Path(data['app_root']).resolve() != ROOT.resolve():
            raise LiteError('INSTALLATION_MOVED', 'Installation moved; preserve its data and rebind paths explicitly.')
        return {'initialized': True, 'existing': True, 'installation': str(path)}
    from .model import Workspace, Snapshot
    from .technology import TechnologyProfile
    from .document import save_document
    from .workspace_storage import WorkspaceStorage
    connection = ROOT / 'config/colayout_lite.json'
    if not connection.exists():
        template = json.loads((ROOT / 'config/colayout_lite.example.json').read_text(encoding='utf8'))
        write_json_atomic(connection, template)
    profile = TechnologyProfile(id='unconfigured', label='待配置 / Setup required',
        native_fingerprint='unconfigured', dbu_per_micron=1000, grid=1,
        writable_lpps=(), layers=[], vias={})
    baseline = Snapshot(library='', cell='', library_path='', session='local-setup', counter='0',
        dirty=False, dbu_per_micron=1000, grid=1, objects={}, technology_fingerprint='unconfigured',
        display={'root':'setup','nodes':{'setup':['setup','','','layout','1000',None,[],[],[],[],[]]},
                 'styles':[],'unsupported':[]})
    workspace = Workspace(baseline=baseline, profile_id=profile.id, connection_config=str(connection))
    seed = ROOT / '.colayout/initial.colayout.json'
    save_document(seed, workspace, profile)
    document, _ = WorkspaceStorage().prepare(seed)
    folder = default_agent_folder()
    write_json_atomic(path, {
        'schema_version': 'colayout-installation-1', 'project_root': str(ROOT), 'app_root': str(ROOT),
        'python_executable': str(Path(sys.executable).resolve()), 'document': str(document),
        'test_kit': str(folder), 'workspace_archive_root': str(folder / 'workspaces'),
        'workspace_import_roots': [str(folder / 'workspaces')]})
    return {'initialized': True, 'existing': False, 'installation': str(path),
            'next': 'Configure the SSH connection, then start the APP and submit a PDK proposal.'}


def client():
    from .agent_tools.client import AgentClient
    return AgentClient(Path(settings()['document']).parent / 'agent-connection.json')


def status():
    return client().call('workspace', {'action': 'status'}, wait_seconds=0, _http_timeout=4)


def configure(host=None, user=None, remote_root=None, existing_env=None, replace=False, profile=None):
    initialize()
    from .document import load_document
    workspace,_ = load_document(settings()['document'])
    if workspace.baseline.objects or workspace.operations:
        raise LiteError('CONNECTION_SETUP_NOT_EMPTY',
            'Initial connection setup requires an empty workspace. Preserve the current design and use a separate installation for another server.')
    connection = ROOT / 'config/colayout_lite.json'
    cfg = json.loads(connection.read_text(encoding='utf8'))
    if not remote_root or not PurePosixPath(remote_root).is_absolute() or remote_root == '/' or '..' in PurePosixPath(remote_root).parts:
        raise LiteError('REMOTE_ROOT_REQUIRED', 'Provide an absolute, dedicated server project directory.')
    if any(c in remote_root for c in ('\n', '\r', '\0')):
        raise LiteError('INVALID_REMOTE_ROOT')
    target = ROOT / '.env'
    if target.exists() and not replace:
        raise LiteError('CONNECTION_EXISTS', 'Existing project .env preserved. Review it or explicitly use --replace while the APP is closed.')
    if existing_env and Path(existing_env).expanduser().resolve()==target.resolve():
        raise LiteError('BRIDGE_ENV_IS_OUTPUT', 'Use a separate source file; --existing-env never overwrites its source.')
    if existing_env and (host or user):
        raise LiteError('CONFLICTING_SSH_TARGET', 'Use either --existing-env or --host/--user.')
    from .bridge_environment import project_environment
    values = project_environment(ROOT,host=host,user=user,source=existing_env,profile=profile)
    from .transactions import write_text_atomic
    write_text_atomic(target, '\n'.join(k+'='+json.dumps(v, ensure_ascii=False) for k,v in values.items())+'\n')
    cfg.update(bridge_env=str(target), allowed_remote_root=remote_root)
    write_json_atomic(connection, cfg)
    return {'configured': True, 'environment': str(target), 'bridge_home':values['VB_HOME'],
            'profile':values['VB_PROFILE'], 'source_environment':str(Path(existing_env).resolve()) if existing_env else None,
            'next': 'Run doctor, then connect to reuse the selected CIW. Use --bootstrap only for a CIW that needs its first Bridge load.'}


def environment():
    from dotenv import dotenv_values
    cfg_path = ROOT / 'config/colayout_lite.json'
    if not cfg_path.is_file():
        raise LiteError('SETUP_REQUIRED', 'Run setup.ps1 first.')
    cfg = json.loads(cfg_path.read_text(encoding='utf8'))
    env = (ROOT / cfg['bridge_env']).resolve()
    if not env.is_file():
        raise LiteError('SERVER_HOST_REQUIRED', 'Configure a server first; no default/private server is assumed.')
    values = dotenv_values(env)
    host = values.get('VB_GUI_HOST') or values.get('VB_REMOTE_HOST')
    user = values.get('VB_REMOTE_USER')
    if not host or not user:
        raise LiteError('SSH_TARGET_REQUIRED', 'Set the server host and SSH username in the selected local environment.')
    return cfg, env, values, host, user


def doctor():
    cfg, env_file, values, host, user = environment()
    args = ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=8']
    if values.get('VB_JUMP_HOST'):
        jump = values['VB_JUMP_HOST']
        if values.get('VB_JUMP_USER'): jump = values['VB_JUMP_USER'] + '@' + jump
        args += ['-J', jump]
    args += [user+'@'+host, 'true']
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=15)
    except FileNotFoundError:
        raise LiteError('SSH_CLIENT_MISSING', 'Install the Windows OpenSSH client and retry.')
    except subprocess.TimeoutExpired:
        raise LiteError('SSH_UNREACHABLE', 'Check server address, VPN, firewall and SSH configuration.')
    if result.returncode:
        message = result.stderr.strip()
        if 'host key' in message.lower():
            raise LiteError('SSH_HOST_KEY_REVIEW_REQUIRED', 'Verify the server fingerprint with its owner, then connect once using ssh. Host-key verification was not bypassed.')
        if any(s in message.lower() for s in ('permission denied', 'authentication')):
            raise LiteError('SSH_AUTH_REQUIRED', 'Passwordless SSH is not ready. Configure your SSH key/agent or ask the administrator; do not put a password in chat or the repository.')
        raise LiteError('SSH_UNREACHABLE', 'SSH probe failed; check address/network/SSH config.', diagnostic=message[:1000])
    return {'ssh_ready': True, 'environment': str(env_file), 'remote_root': cfg['allowed_remote_root']}


def bridge(arguments, timeout=60):
    _, env_file, _, _, _ = environment()
    executable = Path(sys.executable).with_name('virtuoso-bridge.exe' if os.name=='nt' else 'virtuoso-bridge')
    result = subprocess.run([str(executable), *arguments, '--env', str(env_file)],
        capture_output=True, text=True, encoding='utf8', errors='replace', timeout=timeout)
    if result.returncode:
        raise LiteError('BRIDGE_COMMAND_FAILED', result.stderr[-1500:] or result.stdout[-1500:])
    return result.stdout


def windows():
    doctor()
    text = bridge(['list-windows', '--top-level', '--json'])
    decoder = json.JSONDecoder()
    for i, char in enumerate(text):
        if char != '[': continue
        try:
            data, _ = decoder.raw_decode(text[i:])
            if isinstance(data, list) and all(isinstance(row, dict) and 'window_id' in row for row in data):
                return [row for row in data if row.get('kind')=='ciw']
        except ValueError:
            pass
    raise LiteError('BRIDGE_WINDOW_LIST_UNAVAILABLE', 'Inspect the Bridge CLI output; no CIW list was returned.')


def connect(window=None, bootstrap=False):
    choices = windows()
    if not choices:
        raise LiteError('VIRTUOSO_NOT_OPEN', 'Open Virtuoso and the saved Layout sample on the server.')
    if not window and len(choices) != 1:
        return {'connected': False, 'code': 'VIRTUOSO_SELECTION_REQUIRED',
                'message': 'Choose one CIW with the user; no window was bootstrapped.', 'windows': choices}
    selected = next((row for row in choices if row['window_id']==window), None) if window else choices[0]
    if not selected:
        raise LiteError('VIRTUOSO_WINDOW_UNKNOWN', 'Refresh the window list and select a returned CIW ID.')
    bridge(['start'])
    # Reuse is read-only at the CIW. Loading setup is a separate opt-in and is
    # never an automatic recovery for authentication failures or unknown results.
    if bootstrap:bridge(['bootstrap', '--window', selected['window_id']], timeout=60)
    cfg, env_file, *_ = environment()
    from .process_setup import inspect_live
    native, live = inspect_live(env_file)
    native_pid=native.get_virtuoso_pid()
    display=selected.get('display')
    prefix=('DISPLAY='+shlex.quote(display)+' ') if display else ''
    observed=native.ssh_runner.run_command(
        prefix+'xprop -id '+shlex.quote(selected['window_id'])+' _NET_WM_PID',timeout=10)
    match=re.search(r'_NET_WM_PID(?:\([^)]*\))?\s*=\s*(\d+)',observed.stdout)
    if not match or not native_pid:
        raise LiteError('VIRTUOSO_IDENTITY_UNAVAILABLE',
            'Cannot prove that the Bridge endpoint belongs to the selected CIW. Check its PID/profile/ports manually with the upstream Bridge tools before proceeding.',
            selected_ciw=selected['window_id'],connected_pid=native_pid)
    if int(match.group(1))!=native_pid:
        raise LiteError('VIRTUOSO_INSTANCE_MISMATCH',
            'The selected CIW and Bridge endpoint are different processes. Use a separate Bridge port/profile; no native process was stopped.',
            selected_pid=int(match.group(1)),connected_pid=native_pid)
    if PurePosixPath(live['working_directory']) != PurePosixPath(cfg['allowed_remote_root']):
        raise LiteError('CONNECTED_PROJECT_MISMATCH',
            'The connected Virtuoso project differs from the configured project. Use the upstream Bridge profile/port workflow to select the intended instance; do not reset or stop another session.',
            actual=live['working_directory'], expected=cfg['allowed_remote_root'])
    return {'connected': True, 'selected_ciw': selected['window_id'], 'virtuoso_pid':native_pid, **live}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('init', 'doctor', 'windows', 'status'): sub.add_parser(name)
    p = sub.add_parser('configure')
    p.add_argument('--host'); p.add_argument('--user'); p.add_argument('--remote-root', required=True)
    p.add_argument('--existing-env', type=Path, help='Read connection settings into a project-owned .env; source and runtime state are not copied.')
    p.add_argument('--profile', help='Named profile to import from --existing-env.')
    p.add_argument('--replace', action='store_true')
    p = sub.add_parser('connect'); p.add_argument('--window')
    p.add_argument('--bootstrap', action='store_true', help='Explicit first Bridge load into the selected CIW; omit when reusing a running session.')
    args = parser.parse_args()
    try:
        if args.command=='init': result=initialize()
        elif args.command=='configure': result=configure(args.host,args.user,args.remote_root,args.existing_env,args.replace,args.profile)
        elif args.command=='doctor': result=doctor()
        elif args.command=='windows': result={'windows':windows()}
        elif args.command=='connect': result=connect(args.window,args.bootstrap)
        else: result=status()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2 if result.get('code')=='VIRTUOSO_SELECTION_REQUIRED' else 0
    except Exception as exc:
        print(json.dumps({'ok':False,'code':getattr(exc,'code','SETUP_FAILED'),
            'message':str(exc),'details':getattr(exc,'details',{})}, ensure_ascii=False, indent=2))
        return 1


if __name__=='__main__':
    raise SystemExit(main())
