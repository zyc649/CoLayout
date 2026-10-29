"""Two bounded read processes, immutable snapshot reuse, and a bounded result cache."""
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor,Future
from dataclasses import dataclass
from pathlib import Path
from threading import Event,Lock,Thread,get_ident
from time import monotonic
from uuid import uuid4
import json,os,subprocess
from ..model import LiteError
from ..document import document_text
from ..transactions import write_text_atomic
from ..autoroute.runner import python_executable,ROOT


@dataclass
class DeferredResponse:
    future: Future
    finish: object


def read_stamp(w,p,rid,tool):
    from ..scope_state import fingerprint,ancestors
    if tool!='capture_region':return fingerprint(w,rid)
    from ..view_scope import visible_geometry
    from ..editor import projected
    from ..model import digest
    objects=projected(w);view,visible,context=visible_geometry(w,p,rid,objects=objects)
    scopes=ancestors(w,rid)|{rid}
    # A screenshot also includes ancestor overflight and display-only overlays.
    # Sibling internal edits remain independent; visible context is not stale.
    return digest([fingerprint(w,rid),{uid:objects[uid].model_dump() for uid in sorted(context)},
        {uid:mode for uid,mode in w.instance_display.items() if uid in visible},
        [r.model_dump(exclude={'revision','object_uids'}) for r in view.direct_regions],
        {key:row.model_dump() for key,row in w.local_data.markups.items() if row.scope_id in scopes},
        {key:row.model_dump() for key,row in w.local_data.groups.items() if set(row.object_uids)&visible},
        {key:row.model_dump() for key,row in w.local_data.annotations.items()},
        {key:row.model_dump() for key,row in w.local_data.pins.items()}])


class ReadWorker:
    def __init__(self,folder,closed):
        self.folder=folder;self.closed=closed;self.process=None;self.job=None;self.log=None;self.lock=Lock()

    def start(self):
        with self.lock:
            if self.closed.is_set():raise LiteError('APP_CLOSED')
            if self.process and self.process.poll() is None:return
            env=os.environ.copy();env['PYTHONPATH']=str(ROOT)+os.pathsep+env.get('PYTHONPATH','')
            env['PYTHONIOENCODING']='utf-8'
            flags=0
            if os.name=='nt':
                from ..autoroute.windows_job import Job,ENV_NAME
                name='Local\\CoLayout-read-'+uuid4().hex;self.job=Job(name);env[ENV_NAME]=name
                flags=subprocess.CREATE_NO_WINDOW|subprocess.BELOW_NORMAL_PRIORITY_CLASS
            self.log=(self.folder/('worker-'+uuid4().hex+'.log')).open('wb')
            command=[python_executable(),'-X','utf8','-m','colayout_lite.autoroute.process_entry',
                     'module','colayout_lite.agent_tools.read_worker']
            self.process=subprocess.Popen(command,cwd=ROOT,env=env,stdin=subprocess.PIPE,
                stdout=self.log,stderr=subprocess.STDOUT,text=True,encoding='utf8',creationflags=flags)

    def run(self,request):
        output=Path(request['output']);started=monotonic()
        try:
            self.start()
            self.process.stdin.write(json.dumps(request,ensure_ascii=True)+'\n');self.process.stdin.flush()
            while not output.exists():
                if self.closed.wait(.02):raise LiteError('APP_CLOSED')
                if self.process.poll() is not None:raise LiteError('READ_WORKER_FAILED','只读工作进程已退出。')
                if monotonic()-started>60:raise LiteError('READ_TIMEOUT','只读查询超时；未修改工作区。',retryable=True,new_read_request=True)
            if output.stat().st_size>128*1024*1024:raise LiteError('READ_RESULT_TOO_LARGE')
            return json.loads(output.read_text(encoding='utf8'))
        except Exception:
            self.stop();raise
        finally:output.unlink(missing_ok=True)

    def stop(self):
        with self.lock:
            if self.job:self.job.close(terminate=True);self.job=None
            if self.process:
                if self.process.poll() is None:
                    try:self.process.terminate()
                    except OSError:pass
                try:self.process.stdin.close()
                except (OSError,ValueError):pass
                self.process=None
            if self.log:self.log.close();self.log=None


class ReadPool:
    def __init__(self,folder,*,max_workers=2,max_pending=8,cache_bytes=48*1024*1024):
        self.folder=Path(folder);self.folder.mkdir(parents=True,exist_ok=True)
        self.closed=Event();self.lock=Lock();self.workers={}
        self.executor=ThreadPoolExecutor(max_workers=max_workers,thread_name_prefix='CoLayout-read')
        self.writer=ThreadPoolExecutor(max_workers=1,thread_name_prefix='CoLayout-read-snapshot')
        self.snapshots=OrderedDict();self.inflight={};self.cache=OrderedDict();self.cached_bytes=0
        self.max_pending=max_pending;self.cache_bytes=cache_bytes

    def submit(self,w,p,region_id,tool,args):
        values=args.model_dump(mode='json',exclude={'session_token'})
        with self.lock:
            if self.closed.is_set():raise LiteError('APP_CLOSED')
            identity=(id(w),id(p));snapshot=self.snapshots.get(identity)
            if snapshot is None:
                if len(self.inflight)>=self.max_pending:raise LiteError('READ_QUEUE_FULL','只读队列已满，请稍后重新查询。',retryable=True,new_read_request=True)
                path=self.folder/(uuid4().hex+'.snapshot.json')
                future=self.writer.submit(lambda:write_text_atomic(path,document_text(w,p)))
                snapshot={'workspace':w,'profile':p,'path':path,'future':future,'users':0}
                self.snapshots[identity]=snapshot
            self.snapshots.move_to_end(identity)
            key=(str(snapshot['path']),region_id,tool,json.dumps(values,sort_keys=True))
            cached=self.cache.get(key)
            if cached and cached[0].get('result',{}).get('image_path') and not Path(cached[0]['result']['image_path']).exists():
                self.cached_bytes-=self.cache.pop(key)[1];cached=None
            if cached:
                self.cache.move_to_end(key);result=Future();result.set_result(cached[0]);return result
            if key in self.inflight:return self.inflight[key]
            if len(self.inflight)>=self.max_pending:raise LiteError('READ_QUEUE_FULL','只读队列已满，请稍后重新查询。',retryable=True,new_read_request=True)
            snapshot['users']+=1
            future=self.executor.submit(self._run,snapshot,region_id,tool,values)
            self.inflight[key]=future
        future.add_done_callback(lambda done:self._finished(key,snapshot,done))
        return future

    def _run(self,snapshot,region_id,tool,args):
        snapshot['future'].result()
        with self.lock:
            if self.closed.is_set():raise LiteError('APP_CLOSED')
            worker=self.workers.setdefault(get_ident(),ReadWorker(self.folder,self.closed))
        return worker.run({'document':str(snapshot['path']),'tool':tool,'region_id':region_id,'arguments':args,
            'images':str(self.folder.parent/'images'),'output':str(self.folder/(uuid4().hex+'.result.json'))})

    def _finished(self,key,snapshot,future):
        with self.lock:
            self.inflight.pop(key,None);snapshot['users']-=1
            if not self.closed.is_set() and not future.cancelled() and future.exception() is None:
                result=future.result()
                if result.get('ok'):
                    size=len(json.dumps(result,ensure_ascii=False).encode('utf8'))
                    if size<=self.cache_bytes:
                        self.cache[key]=(result,size);self.cached_bytes+=size
                        while len(self.cache)>8 or self.cached_bytes>self.cache_bytes:
                            _,(_,n)=self.cache.popitem(last=False);self.cached_bytes-=n
            for identity,entry in list(self.snapshots.items()):
                if len(self.snapshots)<=3:break
                if not entry['users'] and entry['future'].done():
                    self.snapshots.pop(identity)
                    try:entry['path'].unlink(missing_ok=True)
                    except OSError:pass

    def close(self):
        self.closed.set()
        with self.lock:
            workers=list(self.workers.values());entries=list(self.snapshots.values())
            self.cache.clear();self.cached_bytes=0;self.snapshots.clear()
        for worker in workers:worker.stop()
        self.executor.shutdown(wait=False,cancel_futures=True);self.writer.shutdown(wait=False,cancel_futures=True)
        def clear_snapshots():
            for entry in entries:
                try:entry['future'].result()
                except Exception:pass
                try:entry['path'].unlink(missing_ok=True)
                except OSError:pass # A still-closing OS handle must not delay UI close.
        Thread(target=clear_snapshots,daemon=True,name='CoLayout-read-cache-close').start()
