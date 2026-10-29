"""Persistent asynchronous jobs for UI and agents; no implicit layout commits."""
from uuid import uuid4
import subprocess,sys,os
from ..paths import ROOT
from ..model import LiteError
from .job_storage import read_json, write_json, read_result
from .models import validate_context


BASE=ROOT/'artifacts/drc/jobs'

def job_folder(job_id):
    import re
    if not re.fullmatch('[a-f0-9]{32}',job_id):raise LiteError('INVALID_DRC_JOB_ID')
    return BASE/job_id


def start(w,technology,profile,region,engine,*,scope_id=...,result_limit=None):
    if result_limit is not None and (type(result_limit) is not int or not 1000<=result_limit<=1000000 or engine!='calibre'):
        raise LiteError('INVALID_DRC_RESULT_LIMIT')
    if engine not in ('local','calibre'):raise LiteError('UNKNOWN_DRC_ENGINE')
    if w.state in ('submitting','indeterminate','conflict'):raise LiteError('DRC_WORKSPACE_REQUIRES_RECOVERY')
    validate_context(w,technology,profile)
    if engine=='calibre' and profile.remote is None:raise LiteError('REMOTE_DRC_NOT_CONFIGURED')
    remote_scope={}
    if engine=='calibre':
        from .blackboxes import server_scope
        windows,scope=server_scope(w,technology,region,scope_id)
        remote_scope={'waive_regions_um':windows,'scope':scope}
    uid=uuid4().hex;folder=job_folder(uid);folder.mkdir(parents=True)
    w.save(folder/'workspace.json');technology.save(folder/'technology.json');profile.save(folder/'profile.json')
    request={'job_id':uid,'engine':engine,'region':region.model_dump(),'document_id':w.id,'revision':w.revision}
    if scope_id is not ...:request['scope_id']=scope_id
    if result_limit is not None:request['result_limit']=result_limit
    request.update(remote_scope)
    write_json(folder/'request.json',request)
    initial={'job_id':uid,'status':'queued','message':'任务已排队','engine':engine,
             'stage':'queued','drc_completed':False,'result_available':False}
    write_json(folder/'state.json',initial)
    with (folder/'worker.log').open('w',encoding='utf8') as log:
        process=subprocess.Popen([sys.executable,'-X','utf8','-m','colayout_lite.drc.worker',uid],cwd=ROOT,
            stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    try:
        write_json(folder/'launcher.json',{'pid':process.pid})
        from ..model import digest
        write_json(BASE/'documents'/(digest(w.id)+'.json'),{'job_id':uid})
    except Exception as exc:
        # Popen already succeeded: preserve its identity and stop that worker,
        # never turn a launcher receipt failure into an anonymous retry.
        cancelled=False
        try:
            (folder/'cancel.flag').touch();cancelled=True
        except OSError:
            pass
        details={**getattr(exc,'details',{}),'native_job_id':uid,
                 'cancellation_requested':cancelled,'drc_completed':None,'result_available':None,
                 'next_action':'contact_maintenance'}
        raise LiteError(getattr(exc,'code','DRC_LAUNCH_RECEIPT_FAILED'),str(exc),**details) from exc
    # Return the known launch receipt, not a racing read of the worker's state.
    return initial


def latest(document_id):
    from ..model import digest
    path=BASE/'documents'/(digest(document_id)+'.json')
    return read_json(path)['job_id'] if path.exists() else None


def status(job_id):
    folder=job_folder(job_id)
    terminal=folder/'terminal.json'
    if terminal.exists():return read_json(terminal)
    try:
        state=read_json(folder/'state.json')
    except LiteError:
        # A terminal receipt may have arrived while the polled file was locked.
        if terminal.exists():return read_json(terminal)
        raise
    launcher=folder/'launcher.json'
    if state['status'] not in ('completed','failed','cancelled') and launcher.exists():
        # This project helper uses OpenProcess on Windows, never os.kill(pid,0).
        from virtuoso_bridge.transport.tunnel import _pid_is_alive
        pid=read_json(launcher)['pid']
        if not _pid_is_alive(pid):
            # Re-read after observing exit to avoid racing the final atomic write.
            if terminal.exists():return read_json(terminal)
            state=read_json(folder/'state.json')
            if state['status'] not in ('completed','failed','cancelled'):
                message='DRC 后台进程异常退出，未发布有效检查结论；请联系维护人员。'
                state={**state,'status':'failed','message':message,'error':{
                    'code':'DRC_WORKER_EXITED','message':message,'details':{
                        'failure_kind':'worker_exit','stage':state.get('stage','unknown'),
                        'drc_completed':state.get('drc_completed'), 'result_available':False,
                        'retryable':False,'next_action':'contact_maintenance'}}}
    return state


def result(job_id):
    return read_result(job_folder(job_id)/'result.json')


def cancel(job_id):
    (job_folder(job_id)/'cancel.flag').touch();return status(job_id)
