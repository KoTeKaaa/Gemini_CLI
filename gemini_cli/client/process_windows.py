"""Owned Windows process jobs for confirmed local commands."""
import ctypes
from ctypes import wintypes


class WindowsJob:
    def __init__(self, pid):
        api = self.api = ctypes.WinDLL("kernel32", use_last_error=True)
        api.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        api.CreateJobObjectW.restype = wintypes.HANDLE
        api.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        api.OpenProcess.restype = wintypes.HANDLE
        api.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        api.AssignProcessToJobObject.restype = wintypes.BOOL
        api.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        api.TerminateJobObject.restype = wintypes.BOOL
        api.CloseHandle.argtypes = [wintypes.HANDLE]
        api.CloseHandle.restype = wintypes.BOOL
        api.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        api.WaitForSingleObject.restype = wintypes.DWORD
        api.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        api.GetExitCodeProcess.restype = wintypes.BOOL
        self.handle = api.CreateJobObjectW(None, None)
        process = api.OpenProcess(0x100000 | 0x1000 | 0x0100 | 0x0001, False, pid)
        self.process_handle, self.stopped = process, False
        try:
            if not self.handle or not process or not api.AssignProcessToJobObject(self.handle, process):
                raise ctypes.WinError(ctypes.get_last_error())
        except BaseException:
            if self.handle:
                api.CloseHandle(self.handle)
            if process:
                api.CloseHandle(process)
            raise

    def poll(self):
        if self.api.WaitForSingleObject(self.process_handle, 0) == 258:
            return None
        code = wintypes.DWORD()
        if not self.api.GetExitCodeProcess(self.process_handle, ctypes.byref(code)):
            raise ctypes.WinError(ctypes.get_last_error())
        return code.value

    def stop(self):
        if not self.handle or self.stopped:
            return
        if not self.api.TerminateJobObject(self.handle, 1):
            raise ctypes.WinError(ctypes.get_last_error())
        if self.api.WaitForSingleObject(self.process_handle, 5000) != 0:
            raise TimeoutError("Процесс Windows не завершился после остановки Job Object")
        self.stopped = True

    def close(self):
        if self.handle:
            self.api.CloseHandle(self.process_handle)
            self.process_handle = None
            self.api.CloseHandle(self.handle)
            self.handle = None
