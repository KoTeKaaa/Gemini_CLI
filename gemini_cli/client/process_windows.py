"""Explicit ConPTY backend; imported only on Windows, no shell fallback."""
import ctypes
from ctypes import wintypes
import os
import subprocess
import threading
import time
from .process import ManagedProcess, ProcessLog


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


class WindowsProcess(ManagedProcess):
    def __init__(self, command, cwd, *, env=None, limit=65536):
        from winpty import PTY
        argv = [os.environ.get("COMSPEC", "cmd.exe"), "/Q", "/K", command] if isinstance(command, str) else command
        self.stdout, self.stderr = ProcessLog(limit), ProcessLog(limit)
        self._readers, self._closed = [], False
        self.pty = PTY(80, 24, backend=0)
        environment = "\0".join(f"{key}={value}" for key, value in (env or os.environ).items()) + "\0"
        self.pty.spawn(argv[0], cwd=cwd, env=environment,
                       cmdline=" " + subprocess.list2cmdline(argv[1:]))
        try:
            self.job = WindowsJob(self.pty.pid)
        except BaseException:
            subprocess.run(["taskkill", "/PID", str(self.pty.pid), "/T", "/F"],
                           capture_output=True, timeout=5)
            raise
        def read():
            try:
                while not self._closed:
                    chunk = self.pty.read(blocking=False)
                    if chunk:
                        self.stdout.append(chunk)
                    elif not self.pty.isalive():
                        break
                    else:
                        time.sleep(.02)
            except EOFError:
                pass
            except Exception:
                if not self._closed and self.job.poll() is None:
                    raise
        worker = threading.Thread(target=read, daemon=True)
        self._readers.append(worker)
        worker.start()

    def poll(self):
        return self.job.poll()

    def write(self, text):
        self.pty.write(text)

    def resize(self, rows, columns):
        self.pty.set_size(max(1, columns), max(1, rows))

    def stop(self):
        self.job.stop()

    def close(self):
        if self._closed:
            return
        self.stop()
        self._closed = True
        for reader in self._readers:
            reader.join(1)
        self.job.close()


def start_process(command, cwd, *, pty=False, **kwargs):
    if os.name == "nt" and pty:
        return WindowsProcess(command, cwd, **kwargs)
    return ManagedProcess(command, cwd, pty=pty, **kwargs)
