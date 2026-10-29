"""Recoverable maintenance of legacy temporary OA cells, using native receipts.

This is not a startup sweep. Ordinary source backups and unresolved work stay
in place. Completed temporary copies are archived and verified before removal.
"""
from collections import defaultdict
from pathlib import Path,PurePosixPath
import json,re,shlex
from uuid import uuid4
from .transactions import Receipt
from .process_library import write_json
from .model import LiteError

TEMPORARY=re.compile(r'^COLAYOUT_MVP_LITE_(?:PREVIEW|PROCESS16|MPP_REPRODUCTION|PDK_DRC21|GUARD19)_[A-Za-z0-9_]+$')


def candidates(receipts):
    ready={};blocked=set()
    for row in receipts:
        key=(row.library,row.cell);backup=(row.library,row.backup)
        if row.status not in ('saved','rolled_back'):blocked.update((key,backup))
        if TEMPORARY.fullmatch(row.cell):
            ready[key]={'library':row.library,'cell':row.cell,'request_id':row.request_id}
            ready[backup]={'library':row.library,'cell':row.backup,'source':row.cell,'request_id':row.request_id}
    return ready,blocked


def retained_targets(app):
    blocked=set()
    for path in Path(app).glob('artifacts/**/transactions/*.json'):
        if path.name.endswith('.workspace.json'):continue
        record=json.loads(path.read_text(encoding='utf8'))
        if record.get('status') not in ('saved_verified','rolled_back','not_applied'):
            blocked.add((record['library'],record['cell']))
            if record.get('backup'):blocked.add((record['library'],record['backup']))
    for path in Path(app).glob('artifacts/drc/jobs/*/manifest.json'):
        terminal=path.parent/'terminal.json'
        if not terminal.exists() or json.loads(terminal.read_text(encoding='utf8')).get('status') not in ('completed','failed','cancelled'):
            record=json.loads(path.read_text(encoding='utf8'));blocked.add((record['library'],record['cell']))
    return blocked


def clean(adapter,app,folder,libraries,*,apply=False,progress=print):
    from .sexpr import parse_native
    from .native_lane import channel
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=False)
    root=adapter.native.config['allowed_remote_root'];runner=adapter.native.client.ssh_runner
    def run(command,timeout=60):
        result=runner.run_command(command,timeout=timeout)
        if result.returncode:raise LiteError('TEMPORARY_ARCHIVE_FAILED',result.stderr)
        return result.stdout
    with channel(adapter.native.config_path):
        raw=run('find '+shlex.quote(root+'/.colayout-bridge')+" -maxdepth 1 -type f -name 'lite-*.receipt' -exec cat -- {} +")
        (folder/'native-receipts.sexpr').write_text(raw,encoding='utf8')
        receipts=[]
        for line in raw.splitlines():
            if not line.strip():continue
            value=parse_native(line)
            receipts.append(Receipt.parse(value,request_id=value[1],expected_hash=value[2],library=value[4],cell=value[5]))
        eligible,blocked=candidates(receipts);blocked|=retained_targets(app)
        report={'status':'inventory','apply':apply,'cells':[],'archives':[]};write_json(folder/'report.json',report)
        for key,row in sorted(eligible.items()):
            if row['library'] not in libraries:continue
            row=dict(row);report['cells'].append(row)
            if key in blocked or (row['library'],row.get('source')) in blocked:
                row['status']='protected_unresolved';continue
            try:
                source=adapter.native.call('ltTemporarySource',row['library'],row['cell'])
                if source is None:row['status']='absent';continue
                prefix=row['library']+'/'
                if not source.startswith(prefix):row['status']='foreign_source';continue
                source=source[len(prefix):]
                if row.get('source') and row['source']!=source:row['status']='source_changed';continue
                row['source']=source
                if (row['library'],source) in blocked:row['status']='protected_unresolved';continue
                info=adapter.native.call('ltTemporaryInfo',row['library'],row['cell'],source)
                row['status']=info[0];row['detail']=info[1:]
                if info[0]=='ready':
                    path=PurePosixPath(info[2])
                    if not path.is_relative_to(PurePosixPath(root)) or path.name!=row['cell'] or '..' in path.parts:
                        raise LiteError('TEMPORARY_PATH_MISMATCH')
                    row.update(counter=info[1],path=str(path))
                    adapter.native.call('ltTemporaryRelease',row['library'],row['cell'],source,info[1])
            except Exception as exc:row['status']='retained';row['error']=str(exc)
        write_json(folder/'report.json',report)
        if not apply:return report
        grouped=defaultdict(list)
        for row in report['cells']:
            if row['status']=='ready':grouped[str(PurePosixPath(row['path']).parent)].append(row)
        for libpath,rows in grouped.items():
            ident=uuid4().hex;remote=root+'/.colayout-cache/archives/'+ident
            if any(not re.fullmatch(r'COLAYOUT_MVP_LITE_[A-Za-z0-9_]+',r['cell']) for r in rows):
                raise LiteError('TEMPORARY_NAME_UNSAFE')
            run('mkdir -p -- '+shlex.quote(remote))
            names=folder/(ident+'-cells.txt');names.write_bytes(''.join(r['cell']+'\n' for r in rows).encode('utf8'))
            uploaded=adapter.native.client.upload_file(str(names),remote+'/cells.txt')
            if uploaded.errors:raise LiteError('TEMPORARY_ARCHIVE_UPLOAD_FAILED')
            archive=remote+'/cells.tar.gz'
            # GNU tar checks the archived content against the still-existing OA
            # files. Lock files are runtime state, never restored as history.
            args=" --exclude='*.cdslck*' -C "+shlex.quote(libpath)+' -T '+shlex.quote(remote+'/cells.txt')
            progress('归档并核对 '+str(len(rows))+' 个临时 cell：'+libpath)
            run('tar -czf '+shlex.quote(archive)+args)
            run('tar -dzf '+shlex.quote(archive)+args)
            digest=run('sha256sum -- '+shlex.quote(archive)).split()[0]
            if len(digest)!=64:raise LiteError('TEMPORARY_ARCHIVE_HASH_MISSING')
            proof={'path':archive,'sha256':digest,'library_path':libpath,'cells':[r['cell'] for r in rows]}
            report['archives'].append(proof);write_json(folder/'report.json',report)
            for i,row in enumerate(rows):
                result=adapter.native.call('ltTemporaryDelete',row['library'],row['cell'],row['source'],row['counter'])
                row['status']=result[0];row['cleanup_detail']=result[1:]
                write_json(folder/'report.json',report)
                if (i+1)%25==0:progress('已处理 '+str(i+1)+' / '+str(len(rows)))
        report['status']='complete';write_json(folder/'report.json',report);return report
