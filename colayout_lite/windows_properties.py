"""Small IPropertyStore binding for our own window and shortcut metadata.

Uses documented Shell property APIs; no registry/cache edits or Explorer restart.
https://learn.microsoft.com/windows/win32/api/shellapi/nf-shellapi-shgetpropertystoreforwindow
"""
from contextlib import contextmanager
import ctypes as C
from ctypes import wintypes as W
from uuid import UUID


class GUID(C.Structure):
    _fields_=[('data1',C.c_uint32),('data2',C.c_uint16),('data3',C.c_uint16),('data4',C.c_ubyte*8)]

    @classmethod
    def parse(cls,text):return cls.from_buffer_copy(UUID(text).bytes_le)


class PropertyKey(C.Structure):
    _fields_=[('fmtid',GUID),('pid',W.DWORD)]


class CountedPointer(C.Structure):
    _fields_=[('count',C.c_uint32),('pointer',C.c_void_p)]


class Value(C.Union):
    _fields_=[('pointer',C.c_void_p),('counted',CountedPointer),('integer',C.c_int64)]


class PropVariant(C.Structure):
    _fields_=[('vt',C.c_ushort),('reserved',C.c_ushort*3),('value',Value)]


APP_PROPERTIES=GUID.parse('9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3')
PROPERTY_STORE=GUID.parse('886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99')


def check(hr):
    # S_FALSE is successful no-change, e.g. reapplying a shortcut's existing ID.
    # Still reject truncation instead of publishing incomplete identity strings.
    if hr not in (0,1):raise OSError(f'Windows property store HRESULT 0x{hr & 0xffffffff:08X}')


class PropertyStore:
    def __init__(self,pointer):self.pointer=pointer

    def method(self,index,restype,*arguments):
        table=C.cast(self.pointer,C.POINTER(C.POINTER(C.c_void_p))).contents
        return C.WINFUNCTYPE(restype,C.c_void_p,*arguments)(table[index])

    def set(self,pid,text):
        key=PropertyKey(APP_PROPERTIES,pid);value=PropVariant()
        if text is not None:
            buffer=C.create_unicode_buffer(text)
            value.vt=31;value.value.pointer=C.addressof(buffer)  # VT_LPWSTR, borrowed for SetValue.
        check(self.method(6,C.c_long,C.POINTER(PropertyKey),C.POINTER(PropVariant))(self.pointer,C.byref(key),C.byref(value)))

    def get(self,pid):
        key=PropertyKey(APP_PROPERTIES,pid);value=PropVariant()
        check(self.method(5,C.c_long,C.POINTER(PropertyKey),C.POINTER(PropVariant))(self.pointer,C.byref(key),C.byref(value)))
        try:
            if value.vt==0:return None
            if value.vt!=31:raise ValueError(f'Expected string property, got VT={value.vt}')
            return C.wstring_at(value.value.pointer)
        finally:
            clear=C.WinDLL('ole32').PropVariantClear
            clear.argtypes=(C.POINTER(PropVariant),);clear.restype=C.c_long;clear(C.byref(value))

    def commit(self):check(self.method(7,C.c_long)(self.pointer))

    def close(self):
        if self.pointer:self.method(2,W.ULONG)(self.pointer);self.pointer=None


@contextmanager
def property_store(*,hwnd=None,path=None,writable=False):
    if (hwnd is None)==(path is None):raise ValueError('Choose one window or shortcut')
    ole=C.WinDLL('ole32');initialize=ole.CoInitializeEx
    initialize.argtypes=(C.c_void_p,W.DWORD);initialize.restype=C.c_long
    hr=initialize(None,2);uninitialize=hr in (0,1)
    if hr not in (0,1,-2147417850):check(hr)  # Existing MTA is also initialized.
    pointer=C.c_void_p();store=None
    try:
        shell=C.WinDLL('shell32')
        if hwnd is not None:
            getter=shell.SHGetPropertyStoreForWindow
            getter.argtypes=(W.HWND,C.POINTER(GUID),C.POINTER(C.c_void_p));getter.restype=C.c_long
            check(getter(hwnd,C.byref(PROPERTY_STORE),C.byref(pointer)))
        else:
            getter=shell.SHGetPropertyStoreFromParsingName
            getter.argtypes=(W.LPCWSTR,C.c_void_p,W.DWORD,C.POINTER(GUID),C.POINTER(C.c_void_p));getter.restype=C.c_long
            check(getter(str(path),None,2 if writable else 0,C.byref(PROPERTY_STORE),C.byref(pointer)))
        store=PropertyStore(pointer);yield store
    finally:
        if store:store.close()
        if uninitialize:ole.CoUninitialize()
