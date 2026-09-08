import sys
import unittest
from unittest.mock import patch

from aider.report import (
    exception_handler,
    get_git_info,
    get_os_info,
    get_python_info,
    report_github_issue,
)


class TestReportGithubIssue(unittest.TestCase):
    """Tests for report_github_issue(), the crash-report-to-GitHub-issue flow.

    Added per BUILD_PLAN.md Phase 1 item 6 -- this is user-facing (every
    "Uncaught X in Y line Z" issue on the upstream tracker came through
    here) and had zero prior test coverage. Confirmed via prior research
    that this flow requires explicit user confirmation before filing --
    these tests lock that behavior in so a future refactor (e.g. the
    triage-bot redesign in BUILD_PLAN.md Phase 3) can't silently make it
    file without asking.
    """

    @patch("aider.report.webbrowser.open")
    @patch("builtins.input", return_value="n")
    @patch("builtins.print")
    def test_declining_confirmation_does_not_open_browser(self, mock_print, mock_input, mock_open):
        report_github_issue("some crash text", title="Test Bug", confirm=True)
        mock_open.assert_not_called()

    @patch("aider.report.webbrowser.open")
    @patch("builtins.input", return_value="y")
    @patch("builtins.print")
    def test_accepting_confirmation_opens_browser(self, mock_print, mock_input, mock_open):
        mock_open.return_value = True
        report_github_issue("some crash text", title="Test Bug", confirm=True)
        mock_open.assert_called_once()

    @patch("aider.report.webbrowser.open")
    @patch("builtins.input", return_value="")
    @patch("builtins.print")
    def test_blank_confirmation_defaults_to_yes(self, mock_print, mock_input, mock_open):
        # report_github_issue's own docstring/prompt implies bare Enter == yes
        mock_open.return_value = True
        report_github_issue("some crash text", title="Test Bug", confirm=True)
        mock_open.assert_called_once()

    @patch("aider.report.webbrowser.open")
    @patch("builtins.print")
    def test_confirm_false_opens_without_prompting(self, mock_print, mock_open):
        mock_open.return_value = True
        with patch("builtins.input") as mock_input:
            report_github_issue("some crash text", title="Test Bug", confirm=False)
            mock_input.assert_not_called()
        mock_open.assert_called_once()

    @patch("aider.report.webbrowser.open")
    @patch("builtins.input", return_value="y")
    @patch("builtins.print")
    def test_issue_url_contains_encoded_title_and_system_info(
        self, mock_print, mock_input, mock_open
    ):
        mock_open.return_value = True
        report_github_issue("crash details here", title="Uncaught ValueError in foo.py line 12")
        called_url = mock_open.call_args[0][0]
        self.assertIn("Uncaught+ValueError", called_url.replace("%20", "+"))
        self.assertTrue(called_url.startswith("http"))

    @patch("aider.report.webbrowser.open")
    @patch("builtins.input", return_value="y")
    @patch("builtins.print")
    def test_default_title_used_when_none_given(self, mock_print, mock_input, mock_open):
        mock_open.return_value = True
        report_github_issue("crash details here")
        called_url = mock_open.call_args[0][0]
        self.assertIn("Bug", called_url)


class TestSystemInfoHelpers(unittest.TestCase):
    def test_get_python_info_returns_nonempty_string(self):
        info = get_python_info()
        self.assertIn("Python implementation", info)
        self.assertIn("Virtual environment", info)

    def test_get_os_info_returns_nonempty_string(self):
        info = get_os_info()
        self.assertTrue(info.startswith("OS:"))

    def test_get_git_info_does_not_raise_without_git(self):
        # Should degrade gracefully (returns a fallback string) rather than
        # raising, even if git isn't on PATH in the test environment.
        info = get_git_info()
        self.assertIsInstance(info, str)
        self.assertTrue(info)


class TestExceptionHandler(unittest.TestCase):
    """Tests for exception_handler(), aider's global excepthook."""

    def setUp(self):
        # exception_handler() sets sys.excepthook = None as a deliberate
        # side effect (to avoid re-entrant crash reports). Save/restore it
        # so calling exception_handler() directly in these tests doesn't
        # leak a broken global excepthook into other tests (observed:
        # subsequent subprocess-spawning tests failed with
        # "RuntimeError: sys.excepthook is None" without this).
        self._orig_excepthook = sys.excepthook

    def tearDown(self):
        sys.excepthook = self._orig_excepthook

    def _raise_nested(self):
        def inner():
            raise ValueError("boom")

        inner()

    @patch("aider.report.report_github_issue")
    def test_exception_handler_builds_title_with_type_file_and_line(self, mock_report):
        try:
            self._raise_nested()
        except ValueError:
            exc_type, exc_value, exc_tb = sys.exc_info()

        with patch("aider.report.sys.__excepthook__"):
            exception_handler(exc_type, exc_value, exc_tb)

        mock_report.assert_called_once()
        _issue_text, kwargs = mock_report.call_args
        title = mock_report.call_args.kwargs.get("title") or mock_report.call_args[0][1]
        self.assertIn("Uncaught ValueError", title)
        self.assertIn("test_report.py", title)

    @patch("aider.report.report_github_issue")
    def test_exception_handler_traceback_uses_basenames_not_full_paths(self, mock_report):
        try:
            self._raise_nested()
        except ValueError:
            exc_type, exc_value, exc_tb = sys.exc_info()

        with patch("aider.report.sys.__excepthook__"):
            exception_handler(exc_type, exc_value, exc_tb)

        issue_text = mock_report.call_args[0][0]
        # Full absolute path to this test file should not leak into the
        # reported traceback -- only the basename.
        self.assertNotIn(__file__, issue_text)
        self.assertIn("test_report.py", issue_text)

    def test_keyboard_interrupt_bypasses_reporting(self):
        try:
            raise KeyboardInterrupt()
        except KeyboardInterrupt:
            exc_type, exc_value, exc_tb = sys.exc_info()

        with patch("aider.report.report_github_issue") as mock_report:
            with patch("aider.report.sys.__excepthook__") as mock_default_hook:
                exception_handler(exc_type, exc_value, exc_tb)
                mock_report.assert_not_called()
                mock_default_hook.assert_called_once()


if __name__ == "__main__":
    unittest.main()
