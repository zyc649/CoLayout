"""Small observable view widgets, independent of workspace/model operations."""
from PySide6.QtCore import Signal,Qt,QSize
from PySide6.QtWidgets import QLabel


class StatusLabel(QLabel):
    text_changed=Signal(str)

    def setText(self,text):
        previous=self.text();super().setText(text)
        if text!=previous:self.text_changed.emit(text)


class ElidedLabel(QLabel):
    def __init__(self,text='',parent=None):
        super().__init__(parent);self.full_text=text;self.setMinimumWidth(0)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setText(text)

    def setText(self,text):
        self.full_text=text;self.setToolTip(text)
        line=' '.join(str(text).split())
        super().setText(self.fontMetrics().elidedText(line,Qt.TextElideMode.ElideRight,max(20,self.width())))

    def resizeEvent(self,event):
        super().resizeEvent(event);self.setText(self.full_text)

    def sizeHint(self):
        # Expanding labels use spare space, not space reserved for commands.
        # QLabel's text-dependent hint otherwise pushes trailing toolbar
        # actions into overflow before the caption gets a chance to elide.
        return QSize(0,super().sizeHint().height())

    def minimumSizeHint(self):
        return QSize(0,super().minimumSizeHint().height())
