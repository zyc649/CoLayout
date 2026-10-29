"""Small view-only orthogonal point capture. No geometry/model publication."""
from PySide6.QtCore import QObject,QEvent,Qt,Signal


class PathCapture(QObject):
    active_changed=Signal(bool)
    def __init__(self,window,changed,finished):
        super().__init__(window);self.window=window;self.changed=changed;self.finished=finished
        self.active=False;self.points=[];self.cursor=None;self.key=None
        window.canvas.viewport().installEventFilter(self);window.canvas.installEventFilter(self)

    def start(self):
        self.cancel();e=self.window.editor;self.key=(id(e.w),e.scope_id)
        self.active=True;self.active_changed.emit(True);self.window.canvas.setFocus();self.window.canvas.setCursor(Qt.CursorShape.CrossCursor)

    def cancel(self):
        self.active=False;self.active_changed.emit(False);self.points=[];self.cursor=None;self.window.canvas.unsetCursor();self.changed([])

    def end(self):
        points=list(self.points)
        if len(points)<2:return
        self.cancel();self.finished(points)

    def eventFilter(self,obj,event):
        if not self.active:return False
        e=self.window.editor
        if self.window.busy or (id(e.w),e.scope_id)!=self.key:self.cancel();return False
        kind=event.type()
        if kind in (QEvent.Type.MouseMove,QEvent.Type.MouseButtonPress,QEvent.Type.MouseButtonDblClick):
            pos=self.window.canvas.mapToScene(event.position().toPoint());grid=e.profile.grid
            point=(round(pos.x()/grid)*grid,round(-pos.y()/grid)*grid)
            if self.points:
                x,y=self.points[-1];xx,yy=point
                point=(xx,y) if abs(xx-x)>=abs(yy-y) else (x,yy)
            self.cursor=point
            if kind!=QEvent.Type.MouseMove:
                if event.button()==Qt.MouseButton.LeftButton:
                    if not self.points or self.points[-1]!=point:self.points.append(point)
                    if kind==QEvent.Type.MouseButtonDblClick:self.end();return True
                elif event.button()==Qt.MouseButton.RightButton:
                    if self.points:self.points.pop()
            self.changed(self.points+([point] if not self.points or self.points[-1]!=point else []));return True
        if kind==QEvent.Type.MouseButtonRelease:return True
        if kind==QEvent.Type.KeyPress:
            if event.key() in (Qt.Key.Key_Return,Qt.Key.Key_Enter):self.end();return True
            if event.key()==Qt.Key.Key_Escape:self.cancel();return True
        return False
