"""Loopback transport only. Every tool is dispatched through the live Qt APP."""

import json, secrets
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Event, Thread, Lock
from PySide6.QtCore import QObject, Signal, Slot, Qt, QTimer
from collections import deque
from ..transactions import write_json_atomic


class QtDispatcher(QObject):
    requested = Signal(object)
    rejected = Signal(object)
    completed = Signal(object,object)

    def __init__(self, invoke, parent=None, *, audit=None, queue_timeout=5.0,
                 execution_timeout=90.0, max_pending=64,invoke_async=None):
        super().__init__(parent)
        self.invoke = invoke
        self.invoke_async = invoke_async
        self.closed = False
        self.pending = []
        self.lock = Lock()
        self.audit = audit
        self.queue_timeout = queue_timeout
        self.execution_timeout = execution_timeout
        self.max_pending = max_pending
        self.ready = deque()
        self.executing = False
        self.pump = QTimer(self)
        self.pump.setSingleShot(True)
        self.pump.timeout.connect(self.drain_one)
        self.requested.connect(self.enqueue, Qt.ConnectionType.QueuedConnection)
        self.rejected.connect(self.notice, Qt.ConnectionType.QueuedConnection)
        self.completed.connect(self.finish_deferred,Qt.ConnectionType.QueuedConnection)

    @Slot(object)
    def enqueue(self, request):
        with self.lock:
            if self.closed or request['done'].is_set():
                if request in self.pending:self.pending.remove(request)
                return
        self.ready.append(request)
        if not self.executing and not self.pump.isActive():self.pump.start(0)

    @Slot()
    def drain_one(self):
        # A queued burst must not monopolize the GUI event loop. Every call
        # still publishes/saves/audits synchronously before its response.
        if self.closed or self.executing:return
        self.executing=True
        try:
            if self.ready:self.execute(self.ready.popleft())
        finally:
            self.executing=False
        if self.ready and not self.closed:self.pump.start(0)

    @Slot(object)
    def notice(self, event):
        if self.audit and not self.closed:
            self.audit(event)

    @Slot(object)
    def execute(self, request):
        # Claim the call atomically against a transport-side queue timeout.
        with self.lock:
            if self.closed or request['done'].is_set():
                if request in self.pending:self.pending.remove(request)
                return
            request['running'] = True
            request.setdefault('started', Event()).set()
        deferred=False
        try:
            response = (self.invoke_async or self.invoke)(
                request['tool'],
                request['arguments'],
                client_id=request['client_id'],
                request_id=request['request_id'],
                source='http',
            )
            from .read_pool import DeferredResponse
            if isinstance(response,DeferredResponse):
                deferred=True
                from weakref import ref
                request['deferred_response']=response
                reference=ref(response)
                def finished(unused):
                    value=reference()
                    if value is None:return
                    try:self.completed.emit(request,value)
                    except RuntimeError:pass # The host has already closed.
                response.future.add_done_callback(finished)
            else:request['response']=response
        except Exception as exc:
            request['response'] = {
                'ok': False,
                'error': {'code': 'DISPATCH_ERROR', 'message': str(exc)},
            }
        finally:
            if not deferred:self.finish_request(request)

    def finish_request(self,request):
        with self.lock:
            request.pop('deferred_response',None)
            request['done'].set()
            if request in self.pending:self.pending.remove(request)

    @Slot(object,object)
    def finish_deferred(self,request,response):
        if self.closed:return
        try:request['response']=response.finish()
        except Exception as exc:request['response']={'ok':False,'error':{'code':'DISPATCH_ERROR','message':str(exc)}}
        finally:self.finish_request(request)

    @staticmethod
    def not_started(payload, code, message):
        return {'ok': False, 'request_id': payload['request_id'], 'error': {
            'code': code, 'message': message,
            'details': {'request_not_started': True, 'retryable': code != 'APP_CLOSED',
                        'job_id': payload.get('arguments', {}).get('job_id')}}}

    def call(self, payload):
        request = {**payload, 'done': Event(), 'started': Event(), 'running': False}
        with self.lock:
            if self.closed:
                return self.not_started(payload, 'APP_CLOSED', 'APP 已关闭，本次请求未执行。')
            if len(self.pending) >= self.max_pending:
                return self.not_started(payload, 'APP_QUEUE_FULL',
                    'APP 请求队列已满，本次请求未执行。稍后用同一 request_id 重试；已有任务继续核对原 job_id。')
            self.pending.append(request)
        self.requested.emit(request)
        if not request['started'].wait(self.queue_timeout):
            with self.lock:
                if not request['running'] and not request['done'].is_set():
                    request['response'] = self.not_started(payload, 'APP_QUEUE_TIMEOUT',
                        '界面暂未处理本次请求，本次请求未执行。此结论不代表之前的任务未采用；恢复后继续查询原 job_id，勿重复编辑。')
                    request['done'].set()
                    # Keep its admission slot until Qt consumes the queued
                    # signal. Otherwise a hung GUI can accumulate unbounded
                    # expired signals even though callers already returned.
                if request['done'].is_set():return request['response']
        if not request['done'].wait(self.execution_timeout):
            return {
                'ok': False,
                'error': {
                    'code': 'OUTCOME_UNKNOWN',
                    'message': '保留同一 request_id 查询；不要另发重复编辑。',
                },
            }
        return request['response']

    def close(self):
        self.pump.stop();self.ready.clear()
        with self.lock:
            self.closed = True
            for request in self.pending:
                request.pop('deferred_response',None)
                if request.get('running'):
                    request['response'] = {'ok': False, 'error': {'code': 'OUTCOME_UNKNOWN',
                        'message': '请求已开始执行，关闭时结果仍需核对；保留同一 request_id，勿重复编辑。'}}
                elif not request['done'].is_set():
                    request['response'] = self.not_started(request, 'APP_CLOSED', 'APP 已关闭，排队请求未执行。')
                request['done'].set()
                request.setdefault('started', Event()).set()
            self.pending.clear()


class AgentHTTPServer:
    def __init__(self, dispatcher, connection_file, *, port=0):
        self.dispatcher = dispatcher
        self.token = secrets.token_urlsafe(32)
        owner = self
        self.path = Path(connection_file)
        if self.path.exists():
            old = json.loads(self.path.read_text(encoding='utf8'))
            if not str(old.get('schema_version', '')).startswith('colayout-agent-connection-'):
                raise ValueError('Not an Agent connection file')

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def reply(self, data, status=200):
                raw = json.dumps(data, ensure_ascii=False, allow_nan=False).encode('utf8')
                try:
                    self.send_response(status)
                    self.send_header('Content-Type', 'application/json; charset=utf-8')
                    self.send_header('Content-Length', str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, TimeoutError):
                    # The result is already journaled. A disconnected caller
                    # must reconcile that call, not re-execute an edit here.
                    pass

            def do_POST(self):
                if not secrets.compare_digest(
                    self.headers.get('Authorization', ''), 'Bearer ' + owner.token
                ):
                    owner.dispatcher.rejected.emit(
                        {'event': 'transport_rejected', 'path': self.path, 'code': 'UNAUTHORIZED'}
                    )
                    self.reply({'ok': False, 'error': {'code': 'UNAUTHORIZED'}}, 401)
                    return
                if self.path != '/call':
                    self.reply({'ok': False, 'error': {'code': 'NOT_FOUND'}}, 404)
                    return
                try:
                    self.connection.settimeout(15)
                    size = int(self.headers.get('Content-Length', '0'))
                    if not 0 < size <= 2_000_000:
                        raise ValueError('Invalid request size')
                    raw = self.rfile.read(size)
                    payload = json.loads(
                        raw,
                        parse_constant=lambda value: (_ for _ in ()).throw(
                            ValueError('Non-finite JSON')
                        ),
                    )
                    if not isinstance(payload, dict) or set(payload) != {
                        'tool',
                        'arguments',
                        'request_id',
                        'client_id',
                    }:
                        raise ValueError('Expected v2 call envelope')
                    for key in ('tool', 'request_id', 'client_id'):
                        if not isinstance(payload[key], str) or not 1 <= len(payload[key]) <= 200:
                            raise ValueError('Invalid ' + key)
                    if not isinstance(payload['arguments'], dict):
                        raise ValueError('arguments must be an object')
                except Exception as exc:
                    owner.dispatcher.rejected.emit(
                        {
                            'event': 'transport_rejected',
                            'path': self.path,
                            'code': 'INVALID_REQUEST',
                            'message': str(exc),
                            'request': locals().get('raw', b'').decode('utf8', errors='replace'),
                        }
                    )
                    self.reply(
                        {'ok': False, 'error': {'code': 'INVALID_REQUEST', 'message': str(exc)}},
                        400,
                    )
                    return
                self.reply(owner.dispatcher.call(payload))

            def do_GET(self):
                self.reply(
                    {
                        'ok': False,
                        'error': {
                            'code': 'API_V2_REQUIRED',
                            'message': 'Use the authenticated /call endpoint; region claim is required.',
                        },
                    },
                    410,
                )

        self.server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
        self.server.daemon_threads = True
        self.url = f'http://127.0.0.1:{self.server.server_port}'
        self.publish_connection(self.path)
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def publish_connection(self, path):
        self.path = Path(path)
        write_json_atomic(
            self.path,
            {
                'schema_version': 'colayout-agent-connection-2',
                'url': self.url,
                'token': self.token,
                'protocol': 'region-v2',
            },
        )

    def close(self):
        self.dispatcher.close()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)


# Explicit Python client remains GUI-free.
from .client import AgentClient, RemoteToolError
