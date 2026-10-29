"""CLI over the unmodified public SDK; serializes one customer session on disk."""
import argparse
import base64
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import sys
from datetime import datetime, timezone
from uuid import uuid4

from colayout_client import AgentClient, RemoteToolError
from service import KIT, CONNECTION, write_json

STATE = KIT / 'runtime/client-state.json'
PENDING = KIT / 'runtime/pending-request.json'
LOG = KIT / 'outputs/api-calls.jsonl'


def select_client(name):
    """A named agent owns its session, pending request, CLI lock and outputs."""
    global STATE,PENDING,LOG
    if name is None:return
    import re
    reserved={'con','aux','prn','nul'}|{prefix+str(n) for prefix in ('com','lpt') for n in range(1,10)}
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}',name) or name.lower() in reserved:
        raise ValueError('--client must be a distinct safe name (letters, digits, underscore or hyphen)')
    runtime=KIT/'runtime' if name=='default' else KIT/'runtime/clients'/name
    output=KIT/'outputs' if name=='default' else KIT/'outputs/clients'/name
    STATE=runtime/'client-state.json';PENDING=runtime/'pending-request.json';LOG=output/'api-calls.jsonl'


def redact(value):
    if isinstance(value, dict):
        return {k: ('<redacted>' if k in ('token', 'session_token') else redact(v))
                for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


def record(event):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open('a', encoding='utf8') as stream:
        stream.write(json.dumps({'time': datetime.now(timezone.utc).isoformat(),
                                 **redact(event)}, ensure_ascii=False) + '\n')
        stream.flush()
        os.fsync(stream.fileno())


@contextmanager
def exclusive_cli():
    import msvcrt
    path = STATE.parent / 'cli.lock'
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as stream:
        if stream.tell() == 0:
            stream.write(b'0')
            stream.flush()
        stream.seek(0)
        try:
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise RuntimeError('本测试包已有 API 调用正在执行，请等待；不能并行操作同一客户端。') from exc
        try:
            yield
        finally:
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


def fingerprint(client):
    return hashlib.sha256((client.url + '\n' + client.token).encode()).hexdigest()


def save_client(client):
    write_json(STATE, {'fingerprint': fingerprint(client), 'client_id': client.client_id,
                       'session_token': client.session_token, 'revision': client.revision})


def load_client():
    client = AgentClient(CONNECTION)
    if STATE.exists():
        state = json.loads(STATE.read_text(encoding='utf8'))
        if state['fingerprint'] != fingerprint(client):
            raise RuntimeError('APP 连接已改变。确认旧 APP 已退出后运行 api.py reset-after-restart，再重新 claim。')
        client.client_id = state['client_id']
        client.session_token = state['session_token']
        client.revision = state['revision']
    return client


def call(tool=None, arguments=None, *, retry=False, wait_seconds=15):
    client = load_client()
    if retry:
        if not PENDING.exists():
            raise RuntimeError('没有待核对请求。')
        request = json.loads(PENDING.read_text(encoding='utf8'))
        if request['client_id'] != client.client_id:
            raise RuntimeError('待核对请求不属于当前客户端。')
    else:
        if PENDING.exists():
            raise RuntimeError('上次调用结果未知。先运行 api.py retry，不能换 ID 另发操作。')
        args = dict(arguments or {})
        if tool not in ('tools', 'claim_region', 'reference_cases', 'workspace', 'process_configuration'):
            if not client.session_token:
                raise RuntimeError('请先使用用户提供的区域 ID claim。')
            args.setdefault('session_token', client.session_token)
        request = {'tool': tool, 'arguments': args, 'client_id': client.client_id,
                   'request_id': uuid4().hex}
        save_client(client)
        write_json(PENDING, request)
    record({'event': 'request', **request, 'retry': retry})
    try:
        result = client.call(request['tool'], request['arguments'], request_id=request['request_id'],wait_seconds=wait_seconds)
    except RemoteToolError as exc:
        record({'event': 'response', 'request_id': request['request_id'], 'response': exc.response})
        save_client(client)
        if exc.code not in ('OUTCOME_UNKNOWN', 'AUDIT_UNAVAILABLE', 'DISPATCH_ERROR'):
            PENDING.unlink(missing_ok=True)
        raise
    except Exception as exc:
        record({'event': 'transport_error', 'request_id': request['request_id'], 'error': repr(exc)})
        raise  # Keep exact body/id for retry, including successful-but-unrecorded responses.
    save_client(client)
    response = {'ok': True, 'request_id': request['request_id'],
                'revision': client.revision, 'result': result}
    record({'event': 'response', **response})
    PENDING.unlink(missing_ok=True)
    write_json(LOG.parent / 'last-response.json', redact(response))
    return response


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--client',help='并行 Agent 的独立会话名；每个 Agent 固定使用不同名称。省略沿用原会话。')
    sub = parser.add_subparsers(dest='action', required=True)
    tools=sub.add_parser('tools',help='发现工具及具体编辑动作的参数、单位和状态语义')
    tools.add_argument('--tool');tools.add_argument('--action',dest='tool_action')
    workspace=sub.add_parser('workspace',help='保存当前 APP 工作区或从文件加载；加载前需释放所有区域')
    workspace.add_argument('operation',choices=['status','list','save','load'])
    workspace.add_argument('--name');workspace.add_argument('--path')
    workspace.add_argument('--offset',type=int,default=0);workspace.add_argument('--limit',type=int,default=50)
    claim = sub.add_parser('claim'); claim.add_argument('region_id'); claim.add_argument('--name', required=True)
    inspect = sub.add_parser('inspect'); inspect.add_argument('kind', choices=['layout', 'net', 'rules', 'reference', 'terminals'])
    select=inspect.add_mutually_exclusive_group()
    for flag in ('--net','--component','--uid','--pin-id'):
        select.add_argument(flag,**({'action':'append','help':'layout/reference: 可重复指定对象；net: 只允许一个对象。'} if flag=='--uid' else {}))
    inspect.add_argument('--bounds',type=float,nargs=4);inspect.add_argument('--layers',nargs='+')
    inspect.add_argument('--members',action='store_true');inspect.add_argument('--point',type=float,nargs=2)
    inspect.add_argument('--layer');inspect.add_argument('--query-ref')
    inspect.add_argument('--summary',action='store_true');inspect.add_argument('--uids',nargs='+');inspect.add_argument('--pin-ids',nargs='+')
    inspect.add_argument('--parameters',nargs='*',help='reference 原生参数名；显式空列表省略全部参数，保留端子/绑定')
    inspect.add_argument('--instance-name');inspect.add_argument('--terminal');inspect.add_argument('--name-source',choices=['layout','schematic'])
    raw = sub.add_parser('call'); raw.add_argument('tool'); raw.add_argument('--args', type=Path, required=True)
    raw.add_argument('--wait-seconds',type=float,default=15,help='SDK 自动等待后台任务，0–60 秒；不会重放编辑')
    capture = sub.add_parser('capture'); capture.add_argument('--output', type=Path)
    capture.add_argument('--size',type=int,help='PNG 长边上限，默认 2560，最高 4096')
    capture.add_argument('--width',type=int);capture.add_argument('--height',type=int)
    capture.add_argument('--bounds',nargs=4,type=float,metavar=('XMIN','YMIN','XMAX','YMAX'))
    capture.add_argument('--layers',nargs='+');capture.add_argument('--style',choices=['native','outline'],default='native')
    target=capture.add_mutually_exclusive_group()
    target.add_argument('--net');target.add_argument('--pin-id');target.add_argument('--uid');target.add_argument('--component')
    capture.add_argument('--query-ref');capture.add_argument('--point',nargs=2,type=float);capture.add_argument('--layer')
    capture.add_argument('--highlight',choices=['auto','none','net','component'],default='auto')
    capture.add_argument('--fit',choices=['target','region'],default='target')
    capture.add_argument('--hide-pin-names',action='store_true');capture.add_argument('--hide-instance-names',action='store_true')
    capture.add_argument('--net-names',action='store_true')
    for command in (inspect,capture):
        command.add_argument('--markup-id');command.add_argument('--padding-um',type=float,default=0)
        command.add_argument('--clip-to-region',action='store_true')
    wait=sub.add_parser('wait',help='有限等待后台检查/生成；超时返回当前状态，不重复启动')
    wait.add_argument('tool',choices=['check_region','server_drc_region','route_region','edit_region'])
    wait.add_argument('job_id');wait.add_argument('--seconds',type=float,default=30)
    release = sub.add_parser('release'); release.add_argument('--outcome', choices=['done', 'cancelled', 'handoff'], default='cancelled')
    release.add_argument('--note',default='',help='阶段交接说明；不会替代完整验收')
    sub.add_parser('retry'); sub.add_parser('reset-after-restart')
    args = parser.parse_args()
    select_client(args.client)
    if args.action=='capture' and args.output is None:args.output=LOG.parent/'region.png'
    with exclusive_cli():
        if args.action == 'reset-after-restart':
            client = AgentClient(CONNECTION)
            if STATE.exists() and json.loads(STATE.read_text(encoding='utf8'))['fingerprint'] == fingerprint(client):
                raise RuntimeError('连接未改变，拒绝丢弃现有会话；请正常 release 或请人通过 APP 释放。')
            # Preserve uncertain history. This resets only the local client, never a live lease.
            record({'event': 'reset_after_restart', 'old_state': json.loads(STATE.read_text(encoding='utf8')) if STATE.exists() else None,
                    'pending': json.loads(PENDING.read_text(encoding='utf8')) if PENDING.exists() else None})
            save_client(client); PENDING.unlink(missing_ok=True)
            print('本地客户端已重置；请重新获取用户提供的操作区 ID。旧未知请求不自动重放。')
            return
        if args.action == 'tools': response = call('tools',{k:v for k,v in {'tool':args.tool,'action':args.tool_action}.items() if v})
        elif args.action == 'workspace':
            options={'action':args.operation}
            if args.operation in ('save','load'):
                status=call('workspace',{'action':'status'})['result']
                options.update(expected_document_id=status['document_id'],expected_revision=status['revision'])
            if args.name is not None:options['name']=args.name
            if args.path is not None:options['path']=args.path
            if args.operation=='list':options.update(offset=args.offset,limit=args.limit)
            response=call('workspace',options)
        elif args.action == 'claim': response = call('claim_region', {'region_id': args.region_id, 'agent_name': args.name})
        elif args.action == 'inspect':
            options={'kind':args.kind}
            object_target=None
            if args.uid:
                if args.kind in ('layout','reference'):
                    args.uids=list(dict.fromkeys([*(args.uids or []),*args.uid]))
                elif args.kind=='net' and len(args.uid)==1:
                    object_target=args.uid[0]
                else:
                    raise ValueError('--uid: layout/reference 可用 --uids UID1 UID2；net 查询只允许一个 --uid。')
            for key in ('instance_name','terminal','name_source','markup_id','padding_um','clip_to_region'):
                value=getattr(args,key)
                if value:options[key]=value
            for key,value in (('net',args.net),('bounds_um',args.bounds),('layers',args.layers),('uids',args.uids),('pin_ids',args.pin_ids)):
                if value is not None:options[key]=value
            if args.summary:options['detail']='summary'
            if args.parameters is not None:options['parameter_names']=args.parameters
            if args.members:options['include_members']=True
            for kind,value in (('component',args.component),('object',object_target),('pin',args.pin_id)):
                if value:options['target']={'kind':kind,'id':value,**{k:v for k,v in (('point_um',args.point),('layer',args.layer),('query_ref',args.query_ref)) if v is not None}}
            if 'target' not in options and any(v is not None for v in (args.point,args.layer,args.query_ref)):
                raise ValueError('--point/--layer/--query-ref 需要对应的 --uid 或 --component 选择。')
            response=call('inspect_region',options)
        elif args.action == 'call': response = call(args.tool, json.loads(args.args.read_text(encoding='utf-8-sig')),wait_seconds=args.wait_seconds)
        elif args.action == 'wait': response = call(args.tool,{'mode' if args.tool=='edit_region' else 'action':'status','job_id':args.job_id},wait_seconds=args.seconds)
        elif args.action == 'release': response = call('release_region', {'outcome': args.outcome,**({'note':args.note} if args.note else {})})
        elif args.action == 'retry': response = call(retry=True)
        else:
            options={'style':args.style,'pin_names':not args.hide_pin_names,'instance_names':not args.hide_instance_names,
                     'net_names':args.net_names,'highlight':args.highlight,'fit':args.fit}
            for key in ('markup_id','padding_um','clip_to_region'):
                value=getattr(args,key)
                if value:options[key]=value
            if args.size:options.update(width=args.size,height=args.size)
            for key,value in (('width',args.width),('height',args.height),('bounds_um',args.bounds),('layers',args.layers)):
                if value is not None:options[key]=value
            for kind,value in (('net',args.net),('pin',args.pin_id),('object',args.uid),('component',args.component)):
                if value:
                    options['target']={'kind':kind,'id':value,**{key:v for key,v in
                        (('query_ref',args.query_ref),('point_um',args.point),('layer',args.layer)) if v is not None}}
            response = call('capture_region',options)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_bytes(base64.b64decode(response['result']['image_base64'], validate=True))
            response = {'ok': True, 'revision': response['revision'], 'image': str(args.output.resolve()),
                        'bounds_um': response['result']['bounds_um'],'width':response['result']['width'],
                        'height':response['result']['height'],'highlight':response['result']['highlight'],
                        'display':response['result']['display'],
                        **{k:response['result'][k] for k in ('location','context') if k in response['result']}}
        print(json.dumps(redact(response), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
