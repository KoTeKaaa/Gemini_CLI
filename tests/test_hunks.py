import unittest

from gemini_cli.tools.local.hunks import Hunk, hunks, selected_version


class HunkTest(unittest.TestCase):
    def test_partial_zero_and_complete_selection_preserves_crlf(self):
        before = "".join(f"line{i}\r\n" for i in range(30)).encode()
        after = before.replace(b"line1\r\n", b"new1\r\n").replace(b"line25\r\n", b"new25\r\n")
        edits = hunks(before, after)
        self.assertEqual(len(edits), 2)
        self.assertEqual(selected_version(before, []), before)
        self.assertEqual(selected_version(before, edits), after)
        self.assertEqual(selected_version(before, edits[:1]), before.replace(b"line1\r\n", b"new1\r\n"))

    def test_insertion_deletion_unicode_and_no_final_newline(self):
        for before, after in ((b"", "привет".encode()), (b"remove\n", b""),
                              (b"last", b"last\n"), (b"a\nb", b"b\na")):
            with self.subTest(before=before):
                self.assertEqual(selected_version(before, hunks(before, after)), after)

    def test_overlapping_wrong_context_and_duplicate_rejected(self):
        first = Hunk(0, 2, ("a\n", "b\n"), ("x\n",))
        for edits in ([first, first], [Hunk(1, 2, ("wrong",), ())],
                      [first, Hunk(1, 2, ("b\n",), ())]):
            with self.subTest(edits=edits), self.assertRaises(ValueError):
                selected_version(b"a\nb\n", edits)
