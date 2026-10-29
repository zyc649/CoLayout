"""pythonw smoke: icon sizes, inherited dialog icon, native taskbar identity."""
import argparse,json,sys,traceback
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import Qt,QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QHBoxLayout,QLabel,QMainWindow,QPushButton,QVBoxLayout,QWidget
from colayout_lite.app_identity import APPLICATION_ID,configure_application,application_icon,configure_window,clear_window,taskbar_properties
from colayout_lite.presentation.dark_dialog import DarkDialog
from tools.build_app_icon import SIZES


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,required=True);args=parser.parse_args()
    args.out.mkdir(parents=True,exist_ok=True)
    app=QApplication([]);app.setStyle('Fusion');configure_application(app)
    window=QMainWindow();window.setWindowTitle('CoLayout icon verification');window.resize(760,290)
    central=QWidget();window.setCentralWidget(central);layout=QVBoxLayout(central)
    layout.addWidget(QLabel('当前应用图标 · Windows icon sizes'));row=QHBoxLayout();layout.addLayout(row)
    icon=application_icon()
    for size in (16,24,32,48,64,128):
        column=QVBoxLayout();label=QLabel();label.setPixmap(icon.pixmap(size,size));column.addWidget(label)
        column.addWidget(QLabel(str(size)+' px'));row.addLayout(column)
    button=QPushButton('Open dialog');layout.addWidget(button)
    dialog=DarkDialog(window);dialog.setWindowTitle('CoLayout inherited dialog icon');QVBoxLayout(dialog).addWidget(QLabel('Inherited application icon'))
    button.clicked.connect(dialog.show);report={}
    if sys.platform=='win32':
        from colayout_lite.windows_properties import property_store
        with property_store(hwnd=int(window.winId())) as store:
            report['before_window_properties']={str(key):store.get(key) for key in (2,3,4,5)}
        assert configure_window(window)
    window.show()
    def verify():
        try:
            assert not icon.isNull()
            assert {(s.width(),s.height()) for s in icon.availableSizes()}=={(n,n) for n in SIZES}
            assert all(not icon.pixmap(n,n).isNull() for n in SIZES)
            QTest.mouseClick(button,Qt.MouseButton.LeftButton);app.processEvents()
            assert dialog.isVisible() and not window.windowIcon().isNull() and not dialog.windowIcon().isNull()
            if sys.platform=='win32':
                import ctypes
                from ctypes import wintypes
                getter=ctypes.WinDLL('shell32').GetCurrentProcessExplicitAppUserModelID
                getter.argtypes=(ctypes.POINTER(wintypes.LPWSTR),);getter.restype=ctypes.c_long
                value=wintypes.LPWSTR();assert getter(ctypes.byref(value))==0
                try:assert value.value==APPLICATION_ID
                finally:
                    free=ctypes.WinDLL('ole32').CoTaskMemFree;free.argtypes=(ctypes.c_void_p,);free.restype=None;free(value)
                assert app.property('colayoutWindowsIdentity')
                with property_store(hwnd=int(window.winId())) as store:
                    values={key:store.get(key) for key in (2,3,4,5)}
                assert values==taskbar_properties()
                report['window_properties']=values
            dialog.close();window.grab().save(str(args.out/'sizes.png'))
            report.update(status='passed',sizes=list(SIZES),pythonw=Path(sys.executable).stem=='pythonw',dialog_inherited=True,native_identity=app.property('colayoutWindowsIdentity'))
        except Exception:report.update(status='failed',error=traceback.format_exc())
        (args.out/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
        if report['status']=='failed':clear_window(window);window.close();app.quit()
    def finish():
        if (args.out/'close.flag').exists():clear_window(window);window.close();app.quit()
    timer=QTimer(window);timer.timeout.connect(finish);timer.start(250)
    QTimer.singleShot(200,verify);app.exec()


if __name__=='__main__':main()
