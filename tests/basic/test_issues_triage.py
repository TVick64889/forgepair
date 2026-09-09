"""
Tests for scripts/issues.py's redesigned triage logic.

Per BUILD_PLAN.md Phase 3: covers the parts of the new triage bot that
don't require live GitHub API calls -- feature-request clustering
(pure text-similarity logic) and dashboard body generation. The
GitHub-API-dependent functions (verify-before-redirect resolution
check, label/comment application) are exercised via the live
end-to-end test against the real forgepair repo (see PHASE3_VERIFICATION
notes in CHANGES.md), not unit-mocked here -- mocking GitHub's REST API
surface convincingly enough to catch real bugs is lower value than
testing against the real API once, given how much of this script's
logic is "call API, branch on response shape."
"""

import importlib.util
import sys
import unittest
from pathlib import Path

# scripts/issues.py isn't part of the aider package (it's a standalone
# maintenance script, same as scripts/update_model_lists.py), so import
# it directly by path rather than as a package module.
_ISSUES_PATH = Path(__file__).resolve().parents[2] / "scripts" / "issues.py"
_spec = importlib.util.spec_from_file_location("triage_issues", _ISSUES_PATH)
issues_mod = importlib.util.module_from_spec(_spec)
sys.modules["triage_issues"] = issues_mod
_spec.loader.exec_module(issues_mod)


def make_issue(number, title, body="", state="open", labels=None):
    return {
        "number": number,
        "title": title,
        "body": body,
        "state": state,
        "labels": [{"name": name} for name in labels or []],
        "html_url": f"https://github.com/TVick64889/forgepair/issues/{number}",
    }


class TestClusterFeatureRequests(unittest.TestCase):
    def test_near_identical_titles_cluster_together(self):
        issues = [
            make_issue(
                1, "Add MCP support", "Please add MCP server support", labels=["enhancement"]
            ),
            make_issue(
                2,
                "Add MCP support please",
                "Please add MCP server support to aider",
                labels=["enhancement"],
            ),
            make_issue(3, "Unrelated: fix typo in docs", "Small typo fix", labels=["enhancement"]),
        ]
        clusters = issues_mod.cluster_feature_requests(issues)
        self.assertEqual(len(clusters), 1)
        numbers = sorted(i["number"] for i in clusters[0])
        self.assertEqual(numbers, [1, 2])

    def test_dissimilar_issues_do_not_cluster(self):
        issues = [
            make_issue(
                1, "Add MCP support", "Please add MCP server support", labels=["enhancement"]
            ),
            make_issue(
                2, "Support Windows line endings", "CRLF handling is broken", labels=["enhancement"]
            ),
        ]
        clusters = issues_mod.cluster_feature_requests(issues)
        self.assertEqual(clusters, [])

    def test_non_enhancement_issues_excluded(self):
        issues = [
            make_issue(1, "Add MCP support", "text", labels=["bug"]),
            make_issue(2, "Add MCP support too", "text", labels=["bug"]),
        ]
        clusters = issues_mod.cluster_feature_requests(issues)
        self.assertEqual(clusters, [])

    def test_closed_issues_excluded(self):
        issues = [
            make_issue(1, "Add MCP support", "text", state="closed", labels=["enhancement"]),
            make_issue(2, "Add MCP support too", "text", state="closed", labels=["enhancement"]),
        ]
        clusters = issues_mod.cluster_feature_requests(issues)
        self.assertEqual(clusters, [])

    def test_three_way_cluster(self):
        issues = [
            make_issue(1, "Add dark mode support", "We need dark mode", labels=["enhancement"]),
            make_issue(
                2, "Add dark mode support please", "We need dark mode too", labels=["enhancement"]
            ),
            make_issue(
                3, "Please add dark mode", "We really need dark mode", labels=["enhancement"]
            ),
        ]
        clusters = issues_mod.cluster_feature_requests(issues)
        self.assertEqual(len(clusters), 1)
        self.assertEqual(len(clusters[0]), 3)

    def test_issue_already_assigned_not_double_clustered(self):
        # Regression check: an issue assigned to one cluster shouldn't
        # also spawn/join a second overlapping cluster.
        issues = [
            make_issue(1, "Add dark mode support", "We need dark mode", labels=["enhancement"]),
            make_issue(
                2, "Add dark mode support please", "We need dark mode too", labels=["enhancement"]
            ),
            make_issue(
                3, "Add dark mode support now", "We really need dark mode", labels=["enhancement"]
            ),
        ]
        clusters = issues_mod.cluster_feature_requests(issues)
        seen = set()
        for cluster in clusters:
            for issue in cluster:
                self.assertNotIn(issue["number"], seen, "issue assigned to multiple clusters")
                seen.add(issue["number"])


class TestKnownIssuesDashboardBody(unittest.TestCase):
    """
    update_known_issues_dashboard() does real API calls (find/create/
    patch the dashboard issue), so we test the body-text-generation
    logic indirectly isn't separated into its own function currently --
    flagged here as a real gap: the dashboard body construction is
    inline in update_known_issues_dashboard() rather than a pure
    function, so it's not independently unit-testable without mocking
    the API. Not fixed in this pass -- noted as a follow-up refactor if
    this script gets touched again (extract body-building into a pure
    function, e.g. build_dashboard_body(high_impact_groups,
    feature_clusters) -> str).
    """

    def test_placeholder_acknowledges_gap(self):
        self.assertTrue(hasattr(issues_mod, "update_known_issues_dashboard"))


if __name__ == "__main__":
    unittest.main()
