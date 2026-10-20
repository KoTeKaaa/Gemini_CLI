import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from gemini_cli.tools.local.workspace import plan_text_file, read_binary_snapshot, file_identity


class WorkspaceSnapshotTest(unittest.TestCase):
    def test_windows_plan_uses_descriptor_change_time(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'file'
            path.write_bytes(b'data')
            original = os.stat(path)
            opened = SimpleNamespace(**{key: getattr(original, key) for key in
                       ('st_dev', 'st_ino', 'st_mode', 'st_size', 'st_mtime_ns', 'st_ctime_ns')})
            opened.st_ctime_ns += 100
            with patch('os.name', 'nt'), patch('os.O_BINARY', getattr(os, 'O_BINARY', 0), create=True), \
                 patch('os.fstat', return_value=opened):
                _, identity = plan_text_file(root, 'file')
            self.assertEqual(identity, file_identity(opened))
            self.assertNotEqual(identity, file_identity(original))

    def test_binary_snapshot_preserves_control_z_and_line_endings(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'file'
            raw = b'before\r\n\x1aafter\r\n'
            path.write_bytes(raw)
            expected = plan_text_file(root, 'file')
            self.assertEqual(read_binary_snapshot(root, 'file', expected), raw)
            path.write_bytes(b'changed')
            with self.assertRaises(ValueError):
                read_binary_snapshot(root, 'file', expected)
