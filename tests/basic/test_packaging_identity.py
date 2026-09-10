"""Verifies the package's distribution identity and CLI entry points --
guards against exactly the kind of drift found during a Phase 0 audit:
pyproject.toml's package name and [project.urls]/[project.scripts]
silently still pointing at upstream aider-AI/aider instead of this fork,
long after the rename was believed to have happened.

Reads pyproject.toml as plain text (not a TOML parser) deliberately --
tomllib is stdlib-only on Python >=3.11 and this project still supports
3.10, where a TOML parser would be an extra runtime dependency not
otherwise needed just for this test. pyproject.toml's relevant lines
are simple `key = "value"` pairs, so a targeted regex is fully reliable
here without pulling in tomli.
"""

import re
import unittest
from pathlib import Path

PYPROJECT_PATH = Path(__file__).resolve().parent.parent.parent / "pyproject.toml"


class TestPackagingIdentity(unittest.TestCase):
    def setUp(self):
        self.text = PYPROJECT_PATH.read_text(encoding="utf-8")

    def test_package_name_is_forgepair(self):
        match = re.search(r'^name\s*=\s*"([^"]+)"', self.text, re.MULTILINE)
        self.assertIsNotNone(match, "could not find [project] name = ... in pyproject.toml")
        self.assertEqual(match.group(1), "forgepair")

    def test_homepage_points_at_forgepair_repo_not_upstream(self):
        match = re.search(r'^Homepage\s*=\s*"([^"]+)"', self.text, re.MULTILINE)
        self.assertIsNotNone(
            match, "could not find [project.urls] Homepage = ... in pyproject.toml"
        )
        homepage = match.group(1)
        self.assertIn("TVick64889/forgepair", homepage)
        self.assertNotIn("Aider-AI/aider", homepage)

    def test_both_aider_and_forgepair_cli_entry_points_exist(self):
        scripts_section = re.search(r"\[project\.scripts\]\n(.*?)\n\n", self.text, re.DOTALL)
        self.assertIsNotNone(scripts_section, "could not find [project.scripts] section")
        body = scripts_section.group(1)

        aider_match = re.search(r'^aider\s*=\s*"([^"]+)"', body, re.MULTILINE)
        forgepair_match = re.search(r'^forgepair\s*=\s*"([^"]+)"', body, re.MULTILINE)
        self.assertIsNotNone(aider_match, "no 'aider' entry point in [project.scripts]")
        self.assertIsNotNone(forgepair_match, "no 'forgepair' entry point in [project.scripts]")

        # Both must resolve to the same target so neither command's
        # behavior can silently drift from the other over time.
        self.assertEqual(aider_match.group(1), forgepair_match.group(1))
        self.assertEqual(aider_match.group(1), "aider.main:main")


if __name__ == "__main__":
    unittest.main()
