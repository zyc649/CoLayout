"""Dark tool dialogs, including the native Windows erase-before-paint stage."""
from PySide6.QtWidgets import QDialog
from ..compact_style import window_palette
from ..native_chrome import dark_titlebar,erase_background


class DarkDialog(QDialog):
    def __init__(self,parent=None):
        super().__init__(parent)
        self.setPalette(window_palette(parent.palette() if parent else self.palette()))
        self.setAutoFillBackground(True)

    def showEvent(self,event):
        self.setProperty('compactNativeTitlebar',dark_titlebar(self,True))
        super().showEvent(event)

    def nativeEvent(self,event_type,message):
        if event_type==b'windows_generic_MSG' and erase_background(message,self.palette().window().color()):
            return True,1
        return super().nativeEvent(event_type,message)
