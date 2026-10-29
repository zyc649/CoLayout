"""Own the lifetime of a Windows algorithm process tree before executing code.

Runner workers join the host-owned job before target code. Standalone entry
retains a non-inheritable self-owned fallback job.
This is lifecycle management, NOT a filesystem/network/security sandbox.
"""
import os,sys,runpy
from pathlib import Path

_job_resources=None


def own_process_tree():
    global _job_resources
    if os.name!='nt':return
    from .windows_job import ENV_NAME, Job, join
    name=os.environ.get(ENV_NAME)
    if name:
        join(name)
    else:
        job=Job();job.assign_current();_job_resources=job



def main():
    own_process_tree()
    mode,target,*arguments=sys.argv[1:]
    sys.argv=[target,*arguments]
    if mode=='module':runpy.run_module(target,run_name='__main__',alter_sys=True)
    elif mode=='script':
        sys.path.insert(0,str(Path(target).parent));runpy.run_path(target,run_name='__main__')
    else:raise ValueError('Unknown worker target')

if __name__=='__main__':main()
