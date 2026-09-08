# flake8: noqa: E501

import unittest

from aider.coders import Coder
from aider.coders.patch_coder import (
    ActionType,
    DiffError,
    _norm,
    find_context,
    find_context_core,
    identify_files_needed,
    peek_next_section,
)
from aider.dump import dump  # noqa: F401
from aider.io import InputOutput
from aider.models import Model
from aider.utils import GitTemporaryDirectory


class TestPatchCoderHelpers(unittest.TestCase):
    """Unit tests for the module-level parsing helpers in patch_coder.py.

    Added per BUILD_PLAN.md Phase 1 item 6 -- PatchCoder was flagged in
    ARCHITECTURE_REVIEW.md as the most intricate hand-written parser in the
    codebase with zero prior test coverage.
    """

    def test_norm_strips_cr(self):
        self.assertEqual(_norm("foo\r"), "foo")
        self.assertEqual(_norm("foo"), "foo")

    def test_find_context_core_exact_match(self):
        lines = ["a", "b", "c", "d"]
        idx, fuzz = find_context_core(lines, ["b", "c"], 0)
        self.assertEqual(idx, 1)
        self.assertEqual(fuzz, 0)

    def test_find_context_core_rstrip_tolerant_match(self):
        # Trailing whitespace differs, exact match fails, rstrip match should hit
        lines = ["a", "b  ", "c\t", "d"]
        idx, fuzz = find_context_core(lines, ["b", "c"], 0)
        self.assertEqual(idx, 1)
        self.assertEqual(fuzz, 1)

    def test_find_context_core_strip_tolerant_match(self):
        # Leading whitespace also differs -- only the strip-tolerant tier matches
        lines = ["a", "  b  ", "\tc\t", "d"]
        idx, fuzz = find_context_core(lines, ["b", "c"], 0)
        self.assertEqual(idx, 1)
        self.assertEqual(fuzz, 100)

    def test_find_context_core_no_match(self):
        lines = ["a", "b", "c"]
        idx, fuzz = find_context_core(lines, ["x", "y"], 0)
        self.assertEqual(idx, -1)
        self.assertEqual(fuzz, 0)

    def test_find_context_core_empty_context(self):
        lines = ["a", "b", "c"]
        idx, fuzz = find_context_core(lines, [], 2)
        self.assertEqual(idx, 2)
        self.assertEqual(fuzz, 0)

    def test_find_context_eof_marker_found_at_end(self):
        lines = ["a", "b", "c"]
        idx, fuzz = find_context(lines, ["b", "c"], 0, eof=True)
        self.assertEqual(idx, 1)
        self.assertEqual(fuzz, 0)

    def test_find_context_eof_marker_not_at_end_gets_fuzz_penalty(self):
        lines = ["b", "c", "x", "y"]
        idx, fuzz = find_context(lines, ["b", "c"], 0, eof=True)
        self.assertEqual(idx, 0)
        self.assertGreaterEqual(fuzz, 10_000)

    def test_identify_files_needed_update_and_delete(self):
        text = "\n".join(
            [
                "*** Begin Patch",
                "*** Update File: a.py",
                "@@",
                " context",
                "*** Delete File: b.py",
                "*** End Patch",
            ]
        )
        paths = identify_files_needed(text)
        self.assertEqual(set(paths), {"a.py", "b.py"})

    def test_identify_files_needed_ignores_add(self):
        # Add File doesn't need pre-existing content, shouldn't be "needed"
        text = "\n".join(
            [
                "*** Begin Patch",
                "*** Add File: new.py",
                "+print('hi')",
                "*** End Patch",
            ]
        )
        paths = identify_files_needed(text)
        self.assertEqual(paths, [])

    def test_peek_next_section_parses_add_and_delete_lines(self):
        lines = [
            " context1",
            "-old line",
            "+new line",
            " context2",
            "*** End Patch",
        ]
        context_lines, chunks, next_index, is_eof = peek_next_section(lines, 0)
        self.assertEqual(context_lines, ["context1", "old line", "context2"])
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].del_lines, ["old line"])
        self.assertEqual(chunks[0].ins_lines, ["new line"])
        self.assertEqual(next_index, 4)
        self.assertFalse(is_eof)

    def test_peek_next_section_detects_eof_marker(self):
        lines = [" context1", "*** End of File", "*** End Patch"]
        context_lines, chunks, next_index, is_eof = peek_next_section(lines, 0)
        self.assertTrue(is_eof)
        self.assertEqual(next_index, 2)

    def test_peek_next_section_rejects_invalid_prefix(self):
        lines = ["not a valid prefix line"]
        with self.assertRaises(DiffError):
            peek_next_section(lines, 0)


class TestPatchCoderGetEdits(unittest.TestCase):
    """Tests for PatchCoder.get_edits(), which drives the full parse pipeline."""

    def setUp(self):
        self.io = InputOutput()
        self.GPT35 = Model("gpt-3.5-turbo")

    def test_get_edits_returns_empty_list_for_blank_response(self):
        coder = Coder.create(
            self.GPT35, "patch", io=self.io, fnames=[], stream=False, use_git=False
        )
        coder.partial_response_content = ""
        self.assertEqual(coder.get_edits(), [])

    def test_get_edits_warns_and_returns_empty_for_non_patch_content(self):
        coder = Coder.create(
            self.GPT35, "patch", io=self.io, fnames=[], stream=False, use_git=False
        )
        coder.partial_response_content = "Sure, here's some regular prose, no patch at all."
        self.assertEqual(coder.get_edits(), [])

    def test_get_edits_parses_update_action(self):
        with GitTemporaryDirectory():
            fname = "foo.py"
            with open(fname, "w") as f:
                f.write("one\ntwo\nthree\n")

            coder = Coder.create(
                self.GPT35, "patch", io=self.io, fnames=[fname], stream=False, use_git=False
            )
            coder.partial_response_content = "\n".join(
                [
                    "*** Begin Patch",
                    "*** Update File: foo.py",
                    "@@",
                    " one",
                    "-two",
                    "+TWO",
                    " three",
                    "*** End Patch",
                ]
            )
            edits = coder.get_edits()
            self.assertEqual(len(edits), 1)
            path, action = edits[0]
            self.assertEqual(path, "foo.py")
            self.assertEqual(action.type, ActionType.UPDATE)
            self.assertEqual(len(action.chunks), 1)
            self.assertEqual(action.chunks[0].del_lines, ["two"])
            self.assertEqual(action.chunks[0].ins_lines, ["TWO"])

    def test_get_edits_parses_add_action(self):
        with GitTemporaryDirectory():
            coder = Coder.create(
                self.GPT35, "patch", io=self.io, fnames=[], stream=False, use_git=False
            )
            coder.partial_response_content = "\n".join(
                [
                    "*** Begin Patch",
                    "*** Add File: new_file.py",
                    "+print('hello')",
                    "*** End Patch",
                ]
            )
            edits = coder.get_edits()
            self.assertEqual(len(edits), 1)
            path, action = edits[0]
            self.assertEqual(path, "new_file.py")
            self.assertEqual(action.type, ActionType.ADD)
            self.assertEqual(action.new_content, "print('hello')")

    def test_get_edits_raises_value_error_on_conflicting_actions(self):
        with GitTemporaryDirectory():
            fname = "foo.py"
            with open(fname, "w") as f:
                f.write("content\n")

            coder = Coder.create(
                self.GPT35, "patch", io=self.io, fnames=[fname], stream=False, use_git=False
            )
            # Update then Delete on the same path -- conflicting actions
            coder.partial_response_content = "\n".join(
                [
                    "*** Begin Patch",
                    "*** Update File: foo.py",
                    "@@",
                    " content",
                    "*** Delete File: foo.py",
                    "*** End Patch",
                ]
            )
            with self.assertRaises(ValueError):
                coder.get_edits()

    def test_get_edits_tolerates_missing_sentinels_when_patch_like(self):
        with GitTemporaryDirectory():
            fname = "foo.py"
            with open(fname, "w") as f:
                f.write("one\ntwo\nthree\n")

            coder = Coder.create(
                self.GPT35, "patch", io=self.io, fnames=[fname], stream=False, use_git=False
            )
            # No "*** Begin Patch" sentinel, but content looks patch-like
            coder.partial_response_content = "\n".join(
                [
                    "*** Update File: foo.py",
                    "@@",
                    " one",
                    "-two",
                    "+TWO",
                    " three",
                ]
            )
            edits = coder.get_edits()
            self.assertEqual(len(edits), 1)


class TestPatchCoderApplyEdits(unittest.TestCase):
    """Tests for PatchCoder.apply_edits(), the actual file-mutation step."""

    def setUp(self):
        self.io = InputOutput()
        self.GPT35 = Model("gpt-3.5-turbo")

    def test_apply_edits_add_creates_file(self):
        with GitTemporaryDirectory():
            coder = Coder.create(
                self.GPT35, "patch", io=self.io, fnames=[], stream=False, use_git=False
            )
            from aider.coders.patch_coder import PatchAction

            edits = [("new_file.py", PatchAction(type=ActionType.ADD, path="new_file.py", new_content="hello"))]
            coder.apply_edits(edits)

            with open("new_file.py") as f:
                self.assertEqual(f.read(), "hello\n")

    def test_apply_edits_update_writes_changed_content(self):
        with GitTemporaryDirectory():
            fname = "foo.py"
            with open(fname, "w") as f:
                f.write("one\ntwo\nthree\n")

            coder = Coder.create(
                self.GPT35, "patch", io=self.io, fnames=[fname], stream=False, use_git=False
            )
            coder.partial_response_content = "\n".join(
                [
                    "*** Begin Patch",
                    "*** Update File: foo.py",
                    "@@",
                    " one",
                    "-two",
                    "+TWO",
                    " three",
                    "*** End Patch",
                ]
            )
            edits = coder.get_edits()
            coder.apply_edits(edits)

            with open(fname) as f:
                self.assertEqual(f.read(), "one\nTWO\nthree\n")

    def test_apply_edits_delete_removes_file(self):
        with GitTemporaryDirectory():
            fname = "gone.py"
            with open(fname, "w") as f:
                f.write("bye\n")

            coder = Coder.create(
                self.GPT35, "patch", io=self.io, fnames=[fname], stream=False, use_git=False
            )
            from aider.coders.patch_coder import PatchAction

            edits = [("gone.py", PatchAction(type=ActionType.DELETE, path="gone.py"))]
            coder.apply_edits(edits)

            import os

            self.assertFalse(os.path.exists(fname))


if __name__ == "__main__":
    unittest.main()
