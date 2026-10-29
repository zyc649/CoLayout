"""Host-owned Windows job: covers the real worker behind a venv launcher.

The worker joins before running target code. An already-closed host job cannot
be reopened, so a late-starting worker fails before spawning target children.
See https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects
"""
import ctypes as c
from ctypes import wintypes as w

ENV_NAME='COLAYOUT_RUNNER_JOB'

class Basic(c.Structure):
    _fields_=[('process_time',c.c_longlong),('job_time',c.c_longlong),('flags',w.DWORD),
        ('minimum',c.c_size_t),('maximum',c.c_size_t),('active',w.DWORD),
        ('affinity',c.c_size_t),('priority',w.DWORD),('scheduling',w.DWORD)]
class IO(c.Structure):
    _fields_=[(name,c.c_ulonglong) for name in ('read','write','other','read_bytes','write_bytes','other_bytes')]
class Extended(c.Structure):
    _fields_=[('basic',Basic),('io',IO),('process_memory',c.c_size_t),('job_memory',c.c_size_t),
        ('peak_process',c.c_size_t),('peak_job',c.c_size_t)]

def kernel():
    k=c.WinDLL('kernel32',use_last_error=True)
    for name,args,result in [
        ('CreateJobObjectW',[c.c_void_p,w.LPCWSTR],w.HANDLE),
        ('OpenJobObjectW',[w.DWORD,w.BOOL,w.LPCWSTR],w.HANDLE),
        ('SetInformationJobObject',[w.HANDLE,c.c_int,c.c_void_p,w.DWORD],w.BOOL),
        ('GetCurrentProcess',[],w.HANDLE),
        ('IsProcessInJob',[w.HANDLE,w.HANDLE,c.POINTER(w.BOOL)],w.BOOL),
        ('AssignProcessToJobObject',[w.HANDLE,w.HANDLE],w.BOOL),
        ('TerminateJobObject',[w.HANDLE,w.UINT],w.BOOL),
        ('CloseHandle',[w.HANDLE],w.BOOL)]:
        fn=getattr(k,name);fn.argtypes=args;fn.restype=result
    return k

class Job:
    def __init__(self,name=None):
        self.kernel=kernel();self.handle=self.kernel.CreateJobObjectW(None,name)
        if not self.handle:raise c.WinError(c.get_last_error())
        limit=Extended();limit.basic.flags=0x2000  # KILL_ON_JOB_CLOSE
        if not self.kernel.SetInformationJobObject(self.handle,9,c.byref(limit),c.sizeof(limit)):
            error=c.get_last_error();self.close();raise c.WinError(error)
    def assign_current(self):
        k=self.kernel;inside=w.BOOL()
        if not k.IsProcessInJob(k.GetCurrentProcess(),self.handle,c.byref(inside)):raise c.WinError(c.get_last_error())
        if not inside.value and not k.AssignProcessToJobObject(self.handle,k.GetCurrentProcess()):raise c.WinError(c.get_last_error())
    def close(self,*,terminate=False):
        if not self.handle:return
        handle=self.handle;self.handle=None
        try:
            if terminate and not self.kernel.TerminateJobObject(handle,1):raise c.WinError(c.get_last_error())
        finally:self.kernel.CloseHandle(handle)

def join(name):
    k=kernel();handle=k.OpenJobObjectW(1,False,name)  # ASSIGN_PROCESS; not inherited
    if not handle:raise c.WinError(c.get_last_error())
    try:
        if not k.AssignProcessToJobObject(handle,k.GetCurrentProcess()):raise c.WinError(c.get_last_error())
    finally:k.CloseHandle(handle)
