"""Agent-side client: loopback APP only, no Editor, files or Virtuoso bridge."""

import json
import time
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler
from uuid import uuid4


class RemoteToolError(RuntimeError):
    def __init__(self, response):
        self.response = response
        self.code = response.get('error', {}).get('code', 'API_ERROR')
        super().__init__(json.dumps(response.get('error', response), ensure_ascii=False))


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError('The local APP API must not redirect requests')


class AgentClient:
    def __init__(self, connection_file):
        data = json.loads(Path(connection_file).read_text(encoding='utf8'))
        if data.get('schema_version') != 'colayout-agent-connection-2':
            raise ValueError('需要新版 APP 的 agent-connection.json；不接受 Bridge 或 v1 连接。')
        url = urlsplit(data['url'])
        if (
            url.scheme != 'http'
            or url.hostname not in ('127.0.0.1', 'localhost', '::1')
            or url.username
            or url.password
            or url.path not in ('', '/')
            or url.query
            or url.fragment
        ):
            raise ValueError('Agent API must address the local APP')
        self.url = data['url']
        self.token = data['token']
        self.client_id = uuid4().hex
        self.session_token = None
        self.revision = None
        self.opener = build_opener(ProxyHandler({}), NoRedirect())
        from threading import RLock
        self._call_lock=RLock()

    def call(self, tool, arguments=None, *, request_id=None, wait_seconds=15, _http_timeout=95):
        # Each Agent owns an independent client; accidental same-client calls
        # are serialized so session/revision bookkeeping cannot race.
        with self._call_lock:
            return self._call(tool,arguments,request_id=request_id,wait_seconds=wait_seconds,_http_timeout=_http_timeout)

    def _call(self, tool, arguments=None, *, request_id=None, wait_seconds=15, _http_timeout=95):
        if isinstance(wait_seconds,bool) or not isinstance(wait_seconds,(int,float)) or not 0<=wait_seconds<=60:
            raise ValueError('wait_seconds must be between 0 and 60')
        args = dict(arguments or {})
        if tool not in ('claim_region', 'tools', 'reference_cases','workspace','process_configuration') and 'session_token' not in args:
            args['session_token'] = self.session_token
        payload = {
            'tool': tool,
            'arguments': args,
            'client_id': self.client_id,
            'request_id': request_id or uuid4().hex,
        }
        req = Request(
            self.url + '/call',
            data=json.dumps(payload, ensure_ascii=False, allow_nan=False).encode('utf8'),
            headers={'Authorization': 'Bearer ' + self.token, 'Content-Type': 'application/json'},
        )
        with self.opener.open(req, timeout=_http_timeout) as reply:
            response = json.load(reply)
        revision=response.get('revision',self.revision)
        same_lease=self.session_token is not None and (tool!='claim_region' or response.get('result',{}).get('session_token')==self.session_token)
        # Idempotent replay returns the original response. It must not rewind
        # a later observed revision of this lease after an async edit adopted.
        self.revision=max(self.revision,revision) if same_lease and type(self.revision) is int and type(revision) is int else revision
        if not response.get('ok'):
            raise RemoteToolError(response)
        result = response['result']
        if tool == 'claim_region':
            self.session_token = result['session_token']
        elif tool == 'release_region':
            self.session_token = None
        if wait_seconds:
            result=self._wait_result(tool,args,result,wait_seconds)
        return result

    def _wait_result(self, tool, args, result, seconds):
        status=result
        if status.get('state') not in ('queued','running') or not status.get('job_id'):
            return result
        polling_tool=tool
        if polling_tool not in ('check_region','server_drc_region','route_region','edit_region'):
            return result
        deadline=time.monotonic()+seconds
        interval=.25
        while status.get('state') in ('queued','running') and time.monotonic()<deadline:
            time.sleep(min(interval,max(0,deadline-time.monotonic())))
            interval=min(2,interval*2)
            if time.monotonic()>=deadline:break
            query={'mode' if polling_tool=='edit_region' else 'action':'status','job_id':status['job_id']}
            if args.get('session_token'):query['session_token']=args['session_token']
            if polling_tool=='server_drc_region':
                query.update({k:args[k] for k in ('exclude_categories','include_waived','offset','limit') if k in args})
            try:
                status=self.call(polling_tool,query,wait_seconds=0,_http_timeout=max(.1,deadline-time.monotonic()))
            except Exception as exc:
                # The original edit/start already succeeded. A status failure
                # must not tell the caller to repeat that original mutation.
                status={**status,'wait_error':str(exc),'message':'初始请求已执行；等待查询失败，保留 job_id 继续查询，不要重复编辑。'}
                if polling_tool=='edit_region':status.update(edit_applied=None,outcome='unknown')
                break
        if status.get('state') in ('queued','running') and time.monotonic()>=deadline:
            status={**status,'wait_timed_out':True}
        return status

    def wait(self, tool, job_id, *, seconds=30):
        """Bounded software-managed waiting; never repeats a mutating request."""
        if tool not in ('check_region','server_drc_region','route_region','edit_region'):
            raise ValueError('Unsupported job tool')
        return self.call(tool,{'mode' if tool=='edit_region' else 'action':'status','job_id':job_id},wait_seconds=seconds)

    def connect(self, region_id, agent_name):
        return self.call('claim_region', {'region_id': region_id, 'agent_name': agent_name})

    def tools(self, tool=None, action=None):
        return self.call('tools',{k:v for k,v in {'tool':tool,'action':action}.items() if v is not None})['tools']

    def workspace(self, action='status', **arguments):
        """Save/load a complete local document; load requires all leases released."""
        if action in ('save','load'):
            if action=='load' and self.session_token:
                raise ValueError('Release this client region before loading a workspace')
            if 'expected_document_id' not in arguments or 'expected_revision' not in arguments:
                current=self.call('workspace',{'action':'status'},wait_seconds=0)
                arguments.setdefault('expected_document_id',current['document_id'])
                arguments.setdefault('expected_revision',current['revision'])
        return self.call('workspace',{'action':action,**arguments},wait_seconds=0)
