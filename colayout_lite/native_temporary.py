"""Exact ownership and bounded cleanup for successful native temporary work.

Only copies created inside this scope are disposable. Failed/unknown scopes,
ordinary user workspaces and their recovery backups are never swept by name.
"""
from functools import wraps
from uuid import uuid4
from .transactions import write_json_atomic


class TemporaryCopies:
    def __init__(self,adapter):
        self.adapter=adapter;self.rows=[];self.previous=None
        self.path=adapter.state/'temporary-copies'/(uuid4().hex+'.json')

    def save(self,status):
        write_json_atomic(self.path,{'status':status,'cells':self.rows})

    def __enter__(self):
        self.previous=getattr(self.adapter,'_temporary_copies',None)
        self.adapter._temporary_copies=self
        return self

    def track(self,library,cell,source):
        if not any(r['library']==library and r['cell']==cell for r in self.rows):
            self.rows.append({'library':library,'cell':cell,'source':source,'status':'created'})
            self.save('active')

    def finish(self,success):
        self.adapter._temporary_copies=self.previous
        if not self.rows:return
        if not success:
            self.save('retained_for_recovery');return
        self.save('cleanup_pending')
        for row in reversed(self.rows):
            try:
                info=self.adapter.native.call('ltTemporaryInfo',row['library'],row['cell'],row['source'])
                if info[0]=='absent':row['status']='already_absent'
                elif info[0]=='ready':
                    result=self.adapter.native.call('ltTemporaryDelete',row['library'],row['cell'],row['source'],info[1])
                    row['status']=result[0];row['detail']=result[1:]
                else:row['status']='retained';row['detail']=info
            except Exception as exc:
                row['status']='retained';row['error']=str(exc)
            self.save('cleanup_pending')
        self.save('complete' if all(r['status'] in ('deleted','already_absent') for r in self.rows) else 'needs_attention')

    def __exit__(self,kind,value,traceback):
        # Cleanup failure must not turn a published edit into an unknown result.
        try:self.finish(kind is None)
        except Exception:
            self.adapter._temporary_copies=self.previous
        return False


def track(adapter,library,cell,source):
    scope=getattr(adapter,'_temporary_copies',None)
    if scope is not None:scope.track(library,cell,source)


def temporary_scope(method):
    @wraps(method)
    def wrapped(self,*args,**kwargs):
        with TemporaryCopies(self):return method(self,*args,**kwargs)
    return wrapped
