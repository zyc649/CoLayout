"""Shared native task feedback; animation belongs to the widget, not the canvas."""
from time import monotonic
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QLabel,QProgressBar


class TaskActivity(QWidget):
    def __init__(self,parent=None,*,idle_title='准备',running_title='正在处理',idle_message=''):
        super().__init__(parent);self.started=None;self.outcome='idle';self.idle_title=idle_title;self.running_title=running_title
        layout=QVBoxLayout(self);layout.setContentsMargins(0,4,0,4);layout.setSpacing(5)
        row=QHBoxLayout();self.title=QLabel(idle_title);self.title.setStyleSheet('font-weight:600')
        self.elapsed=QLabel();row.addWidget(self.title);row.addStretch();row.addWidget(self.elapsed);layout.addLayout(row)
        self.bar=QProgressBar();self.bar.setFixedHeight(5);self.bar.setTextVisible(False);self.bar.hide();layout.addWidget(self.bar)
        self.message=QLabel(idle_message);self.message.setWordWrap(True);layout.addWidget(self.message)
        self.timer=QTimer(self);self.timer.setInterval(250);self.timer.timeout.connect(self.tick)

    def start(self):
        self.started=monotonic();self.outcome='running';self.title.setText(self.running_title)
        self.message.setText('准备任务…');self.bar.setRange(0,0);self.bar.show();self.timer.start();self.tick()

    def tick(self):
        seconds=int(monotonic()-self.started) if self.started is not None else 0
        self.elapsed.setText(f'{seconds//60:02d}:{seconds%60:02d}')

    def finish(self,outcome,title,message):
        self.timer.stop();self.bar.hide();self.outcome=outcome;self.title.setText(title);self.message.setText(message)
        if self.started is not None:self.tick()

    def reset(self,message):
        self.finish('idle',self.idle_title,message);self.started=None;self.elapsed.clear()
