import ctypes
import unittest
from unittest.mock import Mock, patch
from gemini_cli.client.process_windows import WindowsJob, WindowsProcess


class WindowsJobTests(unittest.TestCase):
    def test_stop_waits_for_exit_and_is_idempotent(self):
        api = Mock()
        api.CreateJobObjectW.return_value, api.OpenProcess.return_value = 11, 42
        api.AssignProcessToJobObject.return_value = api.TerminateJobObject.return_value = 1
        api.WaitForSingleObject.return_value = 0
        with patch.object(ctypes, "WinDLL", return_value=api, create=True):
            job = WindowsJob(123)
        job.stop()
        job.stop()
        api.TerminateJobObject.assert_called_once_with(11, 1)
        api.WaitForSingleObject.assert_called_once_with(42, 5000)
        job.close()
        self.assertEqual([call.args for call in api.CloseHandle.call_args_list], [(42,), (11,)])

    def test_stop_does_not_cancel_nonexistent_io(self):
        process = WindowsProcess.__new__(WindowsProcess)
        process.job, process.pty = Mock(), Mock()
        process.stop()
        process.job.stop.assert_called_once()
        process.pty.cancel_io.assert_not_called()
