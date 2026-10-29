"""A small action-icon animation; no canvas redraw or workspace state."""
from PySide6.QtCore import QObject,QTimer
from .studio_icons import icon


class SyncIndicator(QObject):
    def __init__(self,action,color,parent,*,idle_icon='sync'):
        super().__init__(parent);self.action=action;self.color=color;self.angle=0
        self.idle_icon=idle_icon
        self.timer=QTimer(self);self.timer.setInterval(50);self.timer.timeout.connect(self.tick)

    def set_active(self,active):
        if active==self.timer.isActive():return
        if active:self.timer.start();self.tick()
        else:self.timer.stop();self.angle=0;self.action.setIcon(icon(self.idle_icon,self.color))

    def tick(self):
        self.angle=(self.angle+18)%360
        self.action.setIcon(icon('sync',self.color,angle=self.angle,active=True))
