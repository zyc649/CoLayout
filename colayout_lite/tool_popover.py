"""Small modeless tool palette; parameters disappear when canvas drawing begins."""
from PySide6.QtCore import Qt,QEvent,QPoint
from PySide6.QtWidgets import QDialog,QVBoxLayout,QToolButton
from .panel_chrome import header


class ToolPopover(QDialog):
    def __init__(self,window,title,panel,cancel):
        super().__init__(window,Qt.WindowType.Tool|Qt.WindowType.FramelessWindowHint)
        self.owner=window;self.panel=panel;self.cancel=cancel;self.setObjectName('toolPopover')
        self.setWindowTitle(title);self.setMinimumWidth(310)
        self.setStyleSheet('QDialog#toolPopover { background:#292b2f; border:1px solid #555963; }')
        layout=QVBoxLayout(self);layout.setContentsMargins(1,1,1,1);layout.setSpacing(0)
        self.header=header(title,self.reject,self);layout.addWidget(self.header);layout.addWidget(panel)
        self.close_button=self.header.findChild(QToolButton)
        window.canvas.viewport().installEventFilter(self)

    def widget(self):return self.panel

    def show_near(self,button=None):
        for other in self.owner.findChildren(ToolPopover):
            if other is not self and not getattr(other.panel,'_running',False):other.hide()
        self.close_button.setEnabled(not getattr(self.panel,'_running',False))
        self.adjustSize()
        anchor=button.mapToGlobal(QPoint(0,button.height()+3)) if button else self.owner.canvas.viewport().mapToGlobal(QPoint(12,12))
        available=self.owner.screen().availableGeometry()
        self.move(min(anchor.x(),available.right()-self.width()),min(anchor.y(),available.bottom()-self.height()))
        self.show();self.raise_()

    def eventFilter(self,obj,event):
        if self.isVisible() and event.type()==QEvent.Type.MouseButtonPress and event.button()==Qt.MouseButton.LeftButton:
            if self.owner.canvas.region_select or getattr(getattr(self.panel,'capture',None),'active',False):self.dismiss_for_drawing()
            elif not getattr(self.panel,'_running',False):self.hide()
        return False

    def dismiss_for_drawing(self):super().hide()

    def hide(self):
        if not getattr(self.panel,'_running',False):self.cancel()
        super().hide()

    def reject(self):
        if getattr(self.panel,'_running',False):return
        self.cancel();super().reject()

    def closeEvent(self,event):
        if getattr(self.panel,'_running',False):event.ignore();return
        self.cancel();super().closeEvent(event)
