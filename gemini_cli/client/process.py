"""Bounded output and owned process groups for commands and live sessions."""
import codecs
import errno
import os
import signal
import struct
import subprocess
import threading
import time


class ProcessLog:
    def __init__(self, limit=65536):
        self.limit = limit
        self._text = ""
        self.truncated = False
        self.lock = threading.Lock()

    def append(self, text):
        with self.lock:
            self.truncated |= len(self._text) + len(text) > self.limit
            self._text = (self._text + text)[-self.limit:]

    def read(self):
        with self.lock:
            return ("[Начало вывода удалено]\n" if self.truncated else "") + self._text


class ManagedProcess:
    def __init__(self, command, cwd, *, pty=False, env=None, limit=65536):
        self.stdout, self.stderr = ProcessLog(limit), ProcessLog(limit)
        self.master = None
        self._closed = False
        self._readers = []
        if pty:
            if os.name != "posix":
                raise OSError("POSIX PTY недоступен")
            import pty as posix_pty
            self.master, slave = posix_pty.openpty()
            try:
                self.process = subprocess.Popen(command, shell=isinstance(command, str),
                    cwd=cwd, env=env, stdin=slave, stdout=slave, stderr=slave,
                    start_new_session=True)
            except BaseException:
                os.close(self.master)
                raise
            finally:
                os.close(slave)
            self._reader(self.master, self.stdout)
        else:
            self.process = subprocess.Popen(command, shell=isinstance(command, str),
                cwd=cwd, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, start_new_session=os.name == "posix")
            self._reader(self.process.stdout, self.stdout)
            self._reader(self.process.stderr, self.stderr)

    def _reader(self, source, log):
        def read():
            decoder = codecs.getincrementaldecoder("utf-8")("replace")
            try:
                while True:
                    chunk = os.read(source if isinstance(source, int) else source.fileno(), 4096)
                    if not chunk:
                        break
                    log.append(decoder.decode(chunk))
            except OSError as error:
                if error.errno not in (errno.EIO, errno.EBADF):
                    log.append("\n[Ошибка чтения процесса]")
            finally:
                log.append(decoder.decode(b"", final=True))
        worker = threading.Thread(target=read, daemon=True)
        self._readers.append(worker)
        worker.start()

    def poll(self):
        return self.process.poll()

    def write(self, text):
        data = text.encode("utf-8")
        if self.master is not None:
            os.write(self.master, data)
        else:
            self.process.stdin.write(data)
            self.process.stdin.flush()

    def resize(self, rows, columns):
        if self.master is not None:
            import fcntl
            import termios
            fcntl.ioctl(self.master, termios.TIOCSWINSZ,
                        struct.pack("HHHH", max(1, rows), max(1, columns), 0, 0))

    def stop(self):
        if os.name == "posix":
            # Kill the owned group even if the shell already exited.
            try:
                os.killpg(self.process.pid, signal.SIGTERM)
                time.sleep(.05)
                os.killpg(self.process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        elif self.poll() is None:
            subprocess.run(["taskkill", "/PID", str(self.process.pid), "/T", "/F"],
                           capture_output=True, timeout=5)
        self.process.wait(timeout=5)

    def wait(self, *, timeout=120, cancelled=lambda: False):
        deadline = time.monotonic() + timeout
        while self.poll() is None:
            if cancelled():
                self.stop()
                return "cancelled"
            if time.monotonic() >= deadline:
                self.stop()
                return "timeout"
            time.sleep(.03)
        for reader in self._readers:
            reader.join(.2)
        return "completed"

    def close(self):
        if self._closed:
            return
        self._closed = True
        self.stop()
        if self.master is not None:
            os.close(self.master)
        for pipe in (self.process.stdin, self.process.stdout, self.process.stderr):
            if pipe:
                pipe.close()
        for reader in self._readers:
            reader.join(.3)
