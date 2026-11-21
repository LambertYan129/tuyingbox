from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes


if sys.platform == 'win32':
    user32 = ctypes.WinDLL('user32', use_last_error=True)
    user32.GetDpiForWindow.argtypes = (wintypes.HWND,)
    user32.GetDpiForWindow.restype = wintypes.UINT
    user32.MonitorFromWindow.argtypes = (wintypes.HWND, wintypes.DWORD)
    user32.MonitorFromWindow.restype = wintypes.HANDLE
    user32.GetMonitorInfoW.argtypes = (wintypes.HANDLE, wintypes.LPVOID)
    user32.GetMonitorInfoW.restype = wintypes.BOOL
    user32.SetProcessDpiAwarenessContext.argtypes = (ctypes.c_void_p,)
    user32.SetProcessDpiAwarenessContext.restype = wintypes.BOOL
else:
    user32 = None


class MonitorInfo(ctypes.Structure):
    _fields_ = [('size', wintypes.DWORD), ('monitor', wintypes.RECT),
                ('work', wintypes.RECT), ('flags', wintypes.DWORD)]


def enable_dpi_awareness():
    if user32 is not None:
        # The EXE sets this in its manifest; this also covers running from source.
        user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))


class Display:
    def __init__(self, root):
        self.root = root
        self.hwnd = root.winfo_id()

    def dpi(self):
        if user32 is not None:
            return user32.GetDpiForWindow(self.hwnd) or 96
        return round(self.root.winfo_fpixels('1i'))

    def work_size(self):
        if user32 is not None:
            monitor = user32.MonitorFromWindow(self.hwnd, 2)
            info = MonitorInfo(size=ctypes.sizeof(MonitorInfo))
            if user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
                return info.work.right - info.work.left, info.work.bottom - info.work.top
        return self.root.winfo_screenwidth(), self.root.winfo_screenheight()
