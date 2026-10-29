"""Shared application artwork and Windows taskbar identity."""
from functools import lru_cache
from pathlib import Path
import sys
import os
import subprocess
from PySide6.QtGui import QIcon

APPLICATION_ID = 'CoLayout.Lite.Workspace'
ICON_PATH = Path(__file__).resolve().parent/'assets/branding/colayout-e2.ico'


@lru_cache(maxsize=1)
def application_icon():
    return QIcon(str(ICON_PATH))


def configure_application(app):
    """Run before showing any windows; never change system-wide associations."""
    app.setWindowIcon(application_icon())
    applied=False
    if sys.platform=='win32':
        try:
            import ctypes
            from ctypes import wintypes
            # Microsoft: set the explicit identity before presenting any UI.
            setter=ctypes.WinDLL('shell32').SetCurrentProcessExplicitAppUserModelID
            setter.argtypes=(wintypes.LPCWSTR,)
            setter.restype=ctypes.c_long
            applied=setter(APPLICATION_ID)==0
        except (OSError,AttributeError):pass
    app.setProperty('colayoutWindowsIdentity',applied)


def taskbar_properties():
    """Relaunch through the maintained entry, never a stale document argument."""
    from .paths import ROOT
    executable=Path(os.environ.get('SystemRoot','C:/Windows'))/'System32/WindowsPowerShell/v1.0/powershell.exe'
    command=subprocess.list2cmdline([str(executable),'-NoProfile','-WindowStyle','Hidden','-ExecutionPolicy','Bypass',
                                    '-File',str(ROOT/'tools/project.ps1'),'-Action','start'])
    # Set ID last: Windows refreshes taskbar metadata when that property changes.
    return {2:command,3:str(ICON_PATH)+',0',4:'CoLayout',5:APPLICATION_ID}


def configure_window(window):
    if sys.platform!='win32':return False
    from .windows_properties import property_store
    hwnd=int(window.winId())
    if getattr(window,'_colayout_taskbar_hwnd',None)==hwnd:return True
    window._colayout_taskbar_hwnd=hwnd
    try:
        with property_store(hwnd=hwnd) as store:
            for key,value in taskbar_properties().items():store.set(key,value)
        window.setProperty('colayoutTaskbarIdentity',True)
        return True
    except OSError as exc:
        clear_window(window);window.setProperty('colayoutTaskbarError',str(exc));return False


def clear_window(window):
    hwnd=getattr(window,'_colayout_taskbar_hwnd',None)
    if not hwnd:return
    from .windows_properties import property_store
    try:
        with property_store(hwnd=hwnd) as store:
            for key in (5,2,3,4):store.set(key,None)
    except OSError as exc:window.setProperty('colayoutTaskbarError',str(exc))
    finally:
        window._colayout_taskbar_hwnd=None
        window.setProperty('colayoutTaskbarIdentity',False)


def identify_shortcut(path):
    from .windows_properties import property_store
    with property_store(path=path,writable=True) as store:
        store.set(5,APPLICATION_ID);store.commit()
