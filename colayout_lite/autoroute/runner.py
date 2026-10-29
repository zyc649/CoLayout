"""Cancellable subprocess runner. Plugins are local trusted code, not sandboxed."""
import os,sys,time,json,subprocess
from pathlib import Path
from ..model import LiteError

ROOT=Path(__file__).resolve().parents[2]


def python_executable():
    value=Path(sys.executable)
    sibling=value.with_name('python.exe') if value.name.lower()=='pythonw.exe' else value
    return str(sibling)


def run(argv,output,log,cancel,timeout,*,cwd=ROOT):
    if cancel.is_set():raise LiteError('ROUTING_CANCELLED')
    program=argv[3:]  # Internal callers consistently pass Python -X utf8.
    mode='module' if program[0]=='-m' else 'script'
    target=program[1:] if mode=='module' else program
    argv=argv[:3]+['-m','colayout_lite.autoroute.process_entry',mode,*target]
    flags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
    env=os.environ.copy();env['PYTHONIOENCODING']='utf-8';env['PYTHONPATH']=str(ROOT)+os.pathsep+env.get('PYTHONPATH','')
    started=time.monotonic();output=Path(output);log=Path(log)
    with log.open('wb') as stream:
        job=None
        if os.name=='nt':
            from .windows_job import Job,ENV_NAME
            from uuid import uuid4
            name='Local\\CoLayout-worker-'+uuid4().hex;job=Job(name);env[ENV_NAME]=name
        try:process=subprocess.Popen(argv,cwd=cwd,env=env,stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT,creationflags=flags,start_new_session=os.name!='nt')
        except BaseException:
            if job:job.close(terminate=True)
            raise
        try:
            while process.poll() is None:
                if cancel.is_set():raise LiteError('ROUTING_CANCELLED','已取消；工作区未修改。')
                if time.monotonic()-started>timeout:raise LiteError('ROUTING_TIMEOUT','算法/检查超过时间预算。',seconds=timeout)
                if log.stat().st_size>2*1024*1024 or output.exists() and output.stat().st_size>16*1024*1024:
                    raise LiteError('PLUGIN_OUTPUT_TOO_LARGE')
                cancel.wait(.04)
        finally:
            # The Popen PID can be only the venv launcher. The host job owns
            # the actual worker and descendants, even if that launcher exits.
            if job:job.close(terminate=True)
            if process.poll() is None:
                if os.name=='nt':process.terminate()
                else:
                    import signal
                    os.killpg(process.pid,signal.SIGTERM)
                try:process.wait(timeout=2)
                except subprocess.TimeoutExpired:process.kill();process.wait()
    if cancel.is_set():raise LiteError('ROUTING_CANCELLED')
    if not output.exists():raise LiteError('ROUTING_PROCESS_FAILED','未生成结果。',exit_code=process.returncode,log=str(log))
    if output.stat().st_size>16*1024*1024:raise LiteError('PLUGIN_OUTPUT_TOO_LARGE')
    result=json.loads(output.read_text(encoding='utf8'))
    if process.returncode or isinstance(result,dict) and result.get('error'):
        error=result.get('error',{}) if isinstance(result,dict) else {}
        raise LiteError(error.get('code','ROUTING_PROCESS_FAILED'),error.get('message','算法运行失败。'),
            details=error.get('details',{}),log=str(log),exit_code=process.returncode)
    return result


def host(stage,input_path,output_path,log,cancel,timeout=120,**options):
    argv=[python_executable(),'-X','utf8','-m','colayout_lite.autoroute.worker',stage,'--input',str(input_path),'--output',str(output_path)]
    for key,value in options.items():argv += ['--'+key,str(value)]
    return run(argv,output_path,log,cancel,timeout)
