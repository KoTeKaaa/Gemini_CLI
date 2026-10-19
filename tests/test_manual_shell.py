import base64
from contextlib import nullcontext
import os
from pathlib import Path
import tempfile
import shutil
import subprocess
import unittest
from unittest.mock import Mock, patch

from gemini_cli.client import shell
from gemini_cli.client.shell_startup import shell_command
from gemini_cli.client.shell_startup import powershell_literal


class ManualShellTest(unittest.TestCase):
    def test_shell_selection(self):
        with patch.object(shell.shutil, 'which', side_effect=lambda item: '/bin/' + item):
            self.assertEqual(shell.select_shell(platform='posix', environ={'SHELL': 'zsh'}), '/bin/zsh')
            self.assertEqual(shell.select_shell(platform='posix', environ={}), '/bin/bash')
            self.assertEqual(shell.select_shell(platform='nt'), '/bin/pwsh')
            with self.assertRaises(ValueError):
                shell.select_shell(platform='posix', environ={'SHELL': 'fish'})
        with patch.object(shell.shutil, 'which', side_effect=[None, '/bin/powershell']):
            self.assertEqual(shell.select_shell(platform='nt'), '/bin/powershell')
        with patch.object(shell.shutil, 'which', return_value=None):
            with self.assertRaises(ValueError):
                shell.select_shell(environ={'SHELL': '/missing/bash'})

    def test_non_tty_does_not_launch(self):
        with patch.object(shell.sys.stdin, 'isatty', return_value=False), \
             patch.object(shell.subprocess, 'run') as run:
            with self.assertRaisesRegex(ValueError, 'TTY'):
                shell.launch_shell(os.getcwd())
            run.assert_not_called()

    @unittest.skipIf(os.name == 'nt', 'POSIX terminal state')
    def test_terminal_state_and_signal_restored_on_spawn_error(self):
        import termios
        previous = shell.signal.getsignal(shell.signal.SIGINT)
        with patch.object(termios, 'tcgetattr', return_value=['original']), \
             patch.object(termios, 'tcsetattr') as restore:
            with self.assertRaises(OSError):
                with shell.terminal_owner():
                    raise OSError('spawn failed')
            restore.assert_called_once_with(shell.sys.stdin.fileno(), termios.TCSADRAIN, ['original'])
        self.assertEqual(shell.signal.getsignal(shell.signal.SIGINT), previous)

    def test_launch_inherits_streams_and_reports_failure(self):
        with tempfile.TemporaryDirectory() as root, \
             patch.object(shell.sys.stdin, 'isatty', return_value=True), \
             patch.object(shell.sys.stdout, 'isatty', return_value=True), \
             patch.object(shell, 'select_shell', return_value='/bin/bash'), \
             patch.object(shell, 'terminal_owner', side_effect=nullcontext), \
             patch.object(shell.subprocess, 'run', return_value=Mock(returncode=7)) as run:
            announce = Mock()
            self.assertIsNone(shell.launch_shell(root, announce=announce))
            self.assertEqual(run.call_args.kwargs['cwd'], root)
            self.assertEqual(set(run.call_args.kwargs), {'cwd', 'env', 'check'})
            self.assertIn('7', announce.call_args.args[0])
            run.side_effect = OSError('private')
            with self.assertRaisesRegex(ValueError, 'Не удалось запустить'):
                shell.launch_shell(root, announce=announce)
            self.assertEqual(list(Path(root).iterdir()), [])

    def test_return_channel_only_accepts_existing_absolute_utf8_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            channel = root / 'return'
            self.assertIsNone(shell.read_return_directory(channel))
            target = root / "папка с пробелом ' $()"
            target.mkdir()
            channel.write_bytes(str(target).encode('utf-8'))
            self.assertEqual(shell.read_return_directory(channel), str(target.resolve()))
            target.rmdir()
            for data in [str(target).encode(), b'../relative', b'\xff', b'/a\x00b',
                         b'a' * 16385, b'__import__("os").system("false")']:
                with self.subTest(data=data[:40]):
                    channel.write_bytes(data)
                    with self.assertRaises(ValueError):
                        shell.read_return_directory(channel)

    def test_powershell_arguments_use_encoded_startup_and_profiles(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for executable in ['C:/Program Files/PowerShell/7/pwsh.exe', 'powershell.exe']:
                command, _ = shell_command(executable, root, root / "a'b")
                self.assertEqual(command[:4], [executable, '-NoLogo', '-NoExit', '-EncodedCommand'])
                script = base64.b64decode(command[4]).decode('utf-16-le')
                self.assertIn("a''b", script)
                self.assertIn('UTF8Encoding', script)
                self.assertNotIn('-NoProfile', command)

    @unittest.skipUnless(shutil.which('pwsh'), 'PowerShell unavailable')
    def test_real_powershell_return_function(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "папка ' с пробелом"
            target.mkdir()
            returned = root / 'return'
            command, _ = shell_command(shutil.which('pwsh'), root, returned)
            bootstrap = base64.b64decode(command[-1]).decode('utf-16-le')
            for arguments in ['', '--sync-dir', '--invalid']:
                with self.subTest(arguments=arguments):
                    returned.unlink(missing_ok=True)
                    script = bootstrap + '\nSet-Location -LiteralPath ' + powershell_literal(str(target))
                    script += '\nexit-to-cli ' + arguments
                    encoded = base64.b64encode(script.encode('utf-16-le')).decode('ascii')
                    result = subprocess.run([command[0], '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded],
                                            capture_output=True, timeout=15)
                    self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
                    expected = str(target.resolve()) if arguments == '--sync-dir' else None
                    self.assertEqual(shell.read_return_directory(returned), expected)


if __name__ == '__main__':
    unittest.main()
