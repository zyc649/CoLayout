"""Persist Python and Qt fatal diagnostics for console-free Windows launches."""
import faulthandler,sys,threading,traceback
from datetime import datetime
from pathlib import Path
from PySide6.QtCore import qInstallMessageHandler
from .paths import ROOT

_files=[]

def install():
    if _files:return
    folder=ROOT/'artifacts/lite/diagnostics';folder.mkdir(parents=True,exist_ok=True)
    import os
    prefix=datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+str(os.getpid())
    log=(folder/(prefix+'.log')).open('a',encoding='utf8',buffering=1)
    fault=(folder/(prefix+'-fault.log')).open('a',encoding='utf8',buffering=1)
    _files.extend([log,fault])
    from .streams import resilient
    sys.stdout=resilient(sys.stdout,folder/(prefix+'-stdout.log'))
    sys.stderr=resilient(sys.stderr,folder/(prefix+'-stderr.log'))
    faulthandler.enable(fault,all_threads=True)
    lock=threading.Lock()
    def qt_message(kind,context,message):
        with lock:log.write(f'{datetime.now().isoformat()} Qt {kind}: {message}\n')
    qInstallMessageHandler(qt_message)
    old_hook=sys.excepthook
    def exception(kind,value,tb):
        traceback.print_exception(kind,value,tb,file=log);old_hook(kind,value,tb)
    sys.excepthook=exception
    log.write('Colayout diagnostics enabled\n')
