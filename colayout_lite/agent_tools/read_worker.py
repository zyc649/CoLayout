"""Persistent read-only process; owns its Qt canvas, never the human window."""
import json,sys,traceback
from collections import OrderedDict
from pathlib import Path


def main():
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QCoreApplication,QEvent
    from ..document import load_document
    from ..transactions import write_json_atomic
    from ..transport import NativeTransport
    from .contract import Capture,Inspect
    from .capture import capture
    from .inspection import net_request
    def forbidden(*args,**kwargs):raise RuntimeError('Read worker cannot contact native EDA')
    NativeTransport.__init__=forbidden
    app=QApplication([]);app.setStyle('Fusion')
    documents=OrderedDict()
    for line in sys.stdin:
        request=json.loads(line);path=request['document'];output=Path(request['output'])
        try:
            if path not in documents:
                documents[path]=load_document(path)
                while len(documents)>2:documents.popitem(last=False)
            documents.move_to_end(path);w,p=documents[path]
            args={**request['arguments'],'session_token':'read-only-snapshot'}
            if request['tool']=='capture_region':
                result=capture(w,p,request['region_id'],Capture.model_validate(args),request['images'])
            elif request['tool']=='inspect_region':
                result=net_request(w,p,request['region_id'],Inspect.model_validate(args))
            else:raise ValueError('Unsupported read worker tool')
            response={'ok':True,'result':result}
        except Exception as exc:
            traceback.print_exc(file=sys.stderr)
            response={'ok':False,'error':{'code':getattr(exc,'code','READ_WORKER_FAILED'),
                'message':str(exc),'details':getattr(exc,'details',{})}}
        finally:
            QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
            app.processEvents()
        write_json_atomic(output,response,compact=True)
    return 0


if __name__=='__main__':raise SystemExit(main())
