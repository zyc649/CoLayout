"""Create/update one client-only folder without copying any previous agent history."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from colayout_lite.bootstrap import settings,installation_path,client,default_agent_folder
from colayout_lite.transactions import write_json_atomic
from tools.build_customer_api_kit import generated_files
from tools.publish_test_connection import publish


def content_hash(content):
    return hashlib.sha256(content).hexdigest()


def create(folder,*,update=False,offline=False):
    folder=Path(folder).expanduser().resolve()
    if folder==ROOT or ROOT.is_relative_to(folder) or folder.is_relative_to(ROOT/'colayout_lite') or folder.is_relative_to(ROOT/'templates'):
        raise ValueError('Choose a separate layout-agent folder, not source/templates or an ancestor.')
    marker=folder/'.colayout-layout-agent.json'
    existing=json.loads(marker.read_text(encoding='utf8')) if marker.is_file() else None
    if existing and not update:raise ValueError('Managed folder already exists. Use --update to preserve its identity/history.')
    if folder.exists() and not existing:
        entries=list(folder.iterdir())
        if any(p.name!='workspaces' or not p.is_dir() for p in entries):
            raise ValueError('Nonempty unmanaged folder was not changed; choose a new directory.')
    config=settings()
    live=None
    if not offline:
        live=client().call('workspace',{'action':'status'},wait_seconds=0,_http_timeout=5)
        if live['active_regions'] or not live.get('can_load',False):
            raise ValueError('Release current agents before changing their client package; no session was ended.')
    template=ROOT/'templates/layout-agent'
    contents={p.relative_to(template).as_posix():p.read_bytes() for p in template.rglob('*')
              if p.is_file() and '__pycache__' not in p.parts}
    contents.update(generated_files())
    old=(existing or {}).get('managed_hashes',{});managed=dict(old);preserved=[]
    folder.mkdir(parents=True,exist_ok=True)
    for name,content in contents.items():
        target=folder/name
        if target.exists() and content_hash(target.read_bytes()) not in (old.get(name),content_hash(content)):
            preserved.append(name);continue
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(content);managed[name]=content_hash(content)
    for name in ('runtime','outputs','requests','workspaces','feedback'):(folder/name).mkdir(exist_ok=True)
    write_json_atomic(folder/'installation.json',{'schema_version':'colayout-customer-runtime-1',
        'python_executable':config['python_executable'],'connection_mode':'local-descriptor'})
    write_json_atomic(marker,{'schema_version':'colayout-layout-agent-1','managed_hashes':managed})
    result={'folder':str(folder),'prepared':True,'connected':False,'ready':False,
        'preserved_custom_files':preserved,'history_copied':False}
    if offline:
        result['next']='Start the APP, then run this command again with --update (without --offline).'
        return result
    current=Path(config['document'])
    if not current.is_file():raise ValueError('Current APP document is unavailable; client history was preserved.')
    config.update(test_kit=str(folder),workspace_archive_root=str(folder/'workspaces'),
                  workspace_import_roots=[str(folder/'workspaces')])
    write_json_atomic(installation_path(),config)
    publication=publish(installation_path(),test_kit=folder)
    restart=Path(live['archive_folder']).resolve()!=(folder/'workspaces').resolve()
    result.update(connected=publication['connected'],restart_required=restart,ready=not restart and not preserved)
    if restart:result['next']='Close the idle APP normally, start it again, publish the connection and confirm workspace.status.archive_folder. Do not start layout work yet.'
    elif preserved:result['next']='Review preserved custom client files before handing over this folder.'
    else:result['next']='Open a separate conversation with access only to this folder; read AGENTS.md.'
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--folder',type=Path,default=default_agent_folder())
    parser.add_argument('--update',action='store_true')
    parser.add_argument('--offline',action='store_true',help='Prepare files only; do not bind/publish a live connection.')
    args=parser.parse_args()
    try:
        print(json.dumps(create(args.folder,update=args.update,offline=args.offline),ensure_ascii=False,indent=2))
        return 0
    except Exception as exc:
        print(json.dumps({'ok':False,'message':str(exc)},ensure_ascii=False))
        return 1


if __name__=='__main__':raise SystemExit(main())
