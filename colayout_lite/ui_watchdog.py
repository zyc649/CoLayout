"""Record stalled Qt event loops without touching widgets from the observer thread."""
import faulthandler
from datetime import datetime,timezone
from pathlib import Path
from threading import Event,Thread
from time import monotonic
from PySide6.QtCore import QObject,QTimer


class UiWatchdog(QObject):
    def __init__(self,app,path,*,threshold=5.0,interval=.5):
        super().__init__(app)
        self.path=Path(path);self.threshold=threshold;self.interval=interval
        self.last=monotonic();self.stopped=Event();self.armed=Event()
        self.timer=QTimer(self);self.timer.setInterval(round(interval*1000))
        self.timer.timeout.connect(self.beat);self.timer.start()
        self.thread=Thread(target=self.observe,name='ui-heartbeat-watchdog',daemon=True)
        app.aboutToQuit.connect(self.stop);self.thread.start()

    def beat(self):
        self.last=monotonic();self.armed.set()

    def observe(self):
        recorded=False
        while not self.stopped.wait(self.interval):
            if not self.armed.is_set():continue
            delay=monotonic()-self.last
            if delay<self.threshold:
                recorded=False;continue
            if recorded:continue
            recorded=True
            try:
                self.path.parent.mkdir(parents=True,exist_ok=True)
                with self.path.open('a',encoding='utf8') as stream:
                    stream.write(f'{datetime.now(timezone.utc).isoformat()} GUI heartbeat delayed {delay:.2f}s\n')
                    stream.flush();faulthandler.dump_traceback(stream,all_threads=True)
            except (OSError,RuntimeError):
                pass  # A diagnostic failure cannot change an edit or terminate the APP.

    def stop(self):
        self.timer.stop();self.stopped.set()
