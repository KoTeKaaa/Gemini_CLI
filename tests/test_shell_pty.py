"""Реальные интерактивные процессы в Linux PTY, без профилей пользователя."""

import errno
import json
import os
from pathlib import Path
import select
import shutil
import signal
import tempfile
import time
import unittest

from gemini_cli.client.shell import launch_shell


@unittest.skipIf(os.name == 'nt', 'POSIX PTY; Windows Terminal проверяется отдельно')
class ShellPtyTest(unittest.TestCase):
    def session(self, executable, commands, directory, home):
        import pty
        import termios
        import fcntl
        import struct
        pid, fd = pty.fork()
        if pid == 0:
            try:
                os.environ.update(HOME=home, ZDOTDIR=home, SHELL=executable, TERM='xterm')
                before = termios.tcgetattr(0)
                result = launch_shell(directory)
                restored = before == termios.tcgetattr(0)
                print('RESULT=' + json.dumps([result, restored]), flush=True)
                os._exit(0)
            except BaseException as exc:
                print('ERROR=' + repr(exc), flush=True)
                os._exit(1)
        output = bytearray()
        transcript = bytearray()
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack('HHHH', 30, 120, 0, 0))
        deadline = time.monotonic() + 20

        def receive_until(marker):
            while marker not in output:
                if time.monotonic() > deadline:
                    self.fail('PTY timeout: ' + (transcript + output).decode(errors='replace')[-2800:])
                if select.select([fd], [], [], 0.1)[0]:
                    try:
                        chunk = os.read(fd, 65536)
                    except OSError as exc:
                        if exc.errno == errno.EIO:
                            self.fail('PTY closed: ' + output.decode(errors='replace')[-1800:])
                        raise
                    if not chunk:
                        self.fail('PTY EOF')
                    output.extend(chunk)
        try:
            # Маркер печатает оболочка после завершения startup, не родитель.
            os.write(fd, b"echo READY_'123'\r")
            receive_until(b'READY_123\r\n')
            for command, marker in commands:
                start = len(output)
                os.write(fd, command)
                # Убираем старый вывод, чтобы каждый marker относился к текущей команде.
                previous = output[:start]
                transcript = previous
                del output[:start]
                receive_until(marker)
                output[:0] = previous
            receive_until(b'RESULT=')
            # JSON и перевод строки могут прийти следующим чтением.
            while b'\n' not in output[output.index(b'RESULT='):]:
                if time.monotonic() > deadline:
                    self.fail('Missing result newline: ' + repr(output[-1000:]))
                if select.select([fd], [], [], 0.1)[0]:
                    output.extend(os.read(fd, 65536))
            line = bytes(output).split(b'RESULT=')[1].split(b'\r\n')[0]
            return json.loads(line), output.decode(errors='replace')
        finally:
            os.close(fd)
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            os.waitpid(pid, 0)

    def test_bash_zsh_interactive_controls_and_sync(self):
        for name in ['bash', 'zsh']:
            executable = shutil.which(name)
            if not executable:
                continue
            with self.subTest(shell=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                home = root / 'home'
                home.mkdir()
                target = root / 'папка с пробелом'
                target.mkdir()
                profile = home / ('.bashrc' if name == 'bash' else '.zshrc')
                profile.write_text("export PROFILE_MARKER=profile_ok\n", encoding='utf-8')
                original = profile.read_bytes()
                commands = [
                    (b'echo $PROFILE_MARKER\r', b'profile_ok\r\n'),
                    (b'cd \xd0\xbf\t\recho CD_\'OK\'\r', b'CD_OK\r\n'),
                    (b'clear\recho CLEAR_\'OK\'\r', b'CLEAR_OK\r\n'),
                    (b'sh -c \'echo START_"SLEEP"; exec sleep 30\'\r', b'START_SLEEP\r\n'),
                    (b'\x03', b'^C'),
                    (b'echo INTERRUPT_\'OK\'\r', b'INTERRUPT_OK\r\n'),
                    (b'exit-to-cli --invalid\recho STILL_\'HERE\'\r', b'STILL_HERE\r\n'),
                    (b'exit-to-cli --sync-dir\r', b'RESULT='),
                ]
                result, _ = self.session(executable, commands, str(root), str(home))
                self.assertEqual(result, [str(target), True])
                self.assertEqual(profile.read_bytes(), original)

    def test_plain_exit_and_exit_to_cli_do_not_sync(self):
        for name in ['bash', 'zsh']:
            executable = shutil.which(name)
            if not executable:
                continue
            for command in [b'exit\r', b'exit-to-cli\r']:
                with self.subTest(shell=name, command=command), tempfile.TemporaryDirectory() as root:
                    result, _ = self.session(executable, [(command, b'RESULT=')], root, root)
                    self.assertEqual(result, [None, True])

    @unittest.skipUnless(shutil.which('zsh'), 'zsh unavailable')
    def test_zsh_honors_profile_directory_changed_by_zshenv(self):
        import shlex
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            profiles = root / 'custom profiles'
            profiles.mkdir()
            (root / '.zshenv').write_text('export ZDOTDIR=' + shlex.quote(str(profiles)) + '\n')
            (profiles / '.zshrc').write_text('export PROFILE_MARKER=custom_profile_ok\n')
            result, _ = self.session(shutil.which('zsh'), [
                (b'echo $PROFILE_MARKER\r', b'custom_profile_ok\r\n'),
                (b'exit-to-cli\r', b'RESULT=')], str(root), str(root))
            self.assertEqual(result, [None, True])

    def test_refused_exit_cancels_directory_sync(self):
        for name in ['bash', 'zsh']:
            executable = shutil.which(name)
            if not executable:
                continue
            with self.subTest(shell=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                (root / 'first').mkdir()
                (root / 'second').mkdir()
                commands = [
                    (b'sleep 60 & job=$!; kill -STOP "$job"; '
                     b'until [ -n "$(jobs -s)" ]; do sleep 0.01; done; echo STOP_\'READY\'\r',
                     b'STOP_READY\r\n'),
                    (b'cd first; exit-to-cli --sync-dir; echo EXIT_\'REFUSED\'\r', b'EXIT_REFUSED\r\n'),
                    (b'cd ../second; kill -KILL "$job"; '
                     + (b'wait -f "$job"' if name == 'bash' else b'wait "$job"')
                     + b'; exit\r', b'RESULT='),
                ]
                result, _ = self.session(executable, commands, str(root), str(root))
                self.assertEqual(result, [None, True])


if __name__ == '__main__':
    unittest.main()
