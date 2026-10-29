"""Optional per-window title-bar appearance; never changes Windows settings.

Windows DWM contract: https://learn.microsoft.com/windows/win32/api/dwmapi/ne-dwmapi-dwmwindowattribute
Unsupported platforms/builds retain their normal system title bar.
"""
import sys
from functools import lru_cache


def dark_titlebar(window,enabled):
    if sys.platform!='win32':return False
    try:
        import ctypes
        from ctypes import wintypes
        setter=ctypes.WinDLL('dwmapi').DwmSetWindowAttribute
        setter.argtypes=(wintypes.HWND,wintypes.DWORD,ctypes.c_void_p,wintypes.DWORD)
        setter.restype=ctypes.c_long
        value=wintypes.BOOL(bool(enabled))
        return setter(int(window.winId()),20,ctypes.byref(value),ctypes.sizeof(value))==0
    except (OSError,AttributeError):return False


@lru_cache(maxsize=1)
def _background_api():
    import ctypes as C
    from ctypes import wintypes as W
    user=C.WinDLL('user32');gdi=C.WinDLL('gdi32')
    user.GetClientRect.argtypes=(W.HWND,C.POINTER(W.RECT));user.GetClientRect.restype=W.BOOL
    user.FillRect.argtypes=(W.HDC,C.POINTER(W.RECT),W.HBRUSH);user.FillRect.restype=C.c_int
    gdi.CreateSolidBrush.argtypes=(W.DWORD,);gdi.CreateSolidBrush.restype=W.HBRUSH
    gdi.DeleteObject.argtypes=(W.HGDIOBJ,);gdi.DeleteObject.restype=W.BOOL
    return user,gdi


def erase_background(message,color):
    """Fill this dialog's invalid client area before Qt's first backing-store paint.

    A dark QPalette does not handle Win32 WM_ERASEBKGND. Do not alter the shared
    Qt window class brush or the user's Windows theme. Release each GDI brush.
    https://learn.microsoft.com/windows/win32/winmsg/wm-erasebkgnd
    """
    if sys.platform!='win32':return False
    try:
        import ctypes as C
        from ctypes import wintypes as W
        msg=W.MSG.from_address(int(message))
        if msg.message!=0x14 or not msg.wParam:return False
        user,gdi=_background_api();rect=W.RECT()
        if not user.GetClientRect(msg.hWnd,C.byref(rect)):return False
        brush=gdi.CreateSolidBrush(color.red()|(color.green()<<8)|(color.blue()<<16))
        if not brush:return False
        try:return bool(user.FillRect(msg.wParam,C.byref(rect),brush))
        finally:gdi.DeleteObject(brush)
    except (OSError,AttributeError,TypeError,ValueError):return False
