# ForgePair — Changes from Upstream aider

Status: living document, updated as work happens (not just at release
time). Source of truth for the eventual README "what's new" section.

This file tracks how ForgePair differs from upstream aider-AI/aider.
It is distinct from HISTORY.md (aider's own pre-fork release log, kept
as-is for historical record and continued in that style for ForgePair's
own future releases going forward).

Format: each entry is tagged NEW / IMPROVED / REPAIRED / REMOVED, dated,
with the phase it happened in and (where relevant) the aider issue
number or ARCHITECTURE_REVIEW.md/BUILD_PLAN.md section it addresses.
Entries are written for a README audience (why it matters), with
implementation detail kept minimal -- see git log / BUILD_PLAN.md for
that.

---

## Phase 0 -- Fork setup (2026-09-08)

NEW
- Forked from aider-AI/aider at commit 5dc9490bb (2026-05-22) under the
  ForgePair name. Full commit history preserved; `upstream` remote kept
  configured for pulling future upstream fixes.

---

## Phase 1 -- Cleanup (2026-09-08)

REMOVED
- Three unreachable legacy edit-format coders (`EditBlockFunctionCoder`,
  `WholeFileFunctionCoder`, `SingleWholeFileFunctionCoder`) deleted.
  These could not be selected via any `--edit-format` value and had no
  test coverage -- pure dead weight, no user-facing change.
- The OpenRouter model-metadata HTML-scraping fallback removed. It
  scraped the OpenRouter website's rendered page and broke silently
  whenever OpenRouter changed their page layout, with no visible
  warning. OpenRouter model pricing/context-window info now comes
  exclusively from OpenRouter's official `/api/v1/models` JSON API
  (which was already the primary path and is unaffected).

IMPROVED
- Removed dead conditional-import branches in the repo-map (codebase
  context) system related to an old, no-longer-reachable tree-sitter
  binding path -- simplification only, no behavior change. (Verified
  carefully: a related fallback that looked similar was found to still
  be load-bearing for 11 languages including PHP, TypeScript, and
  Kotlin, and was deliberately left untouched.)
- Model-name fast-lookup lists (used to quickly identify which API key
  a model needs) are now generated from live model-provider data via a
  maintenance script instead of hand-typed and manually kept up to
  date. Running the script once already caught and removed several
  model names (`o1-preview`, `o1-mini`, and others) that no longer
  exist with any provider -- the old list was already stale before this
  fix landed.

REPAIRED
- Added test coverage for the custom "patch" edit format (the newest,
  most complex file-editing engine in the codebase), which previously
  had zero tests despite being one of the most intricate parsers in the
  project. 22 new tests.
- Added test coverage for the crash-reporting flow (what happens when
  aider hits an unexpected internal error), which previously had zero
  tests despite being fully user-facing. 12 new tests. Confirmed and
  locked in the existing behavior that this flow always asks for
  explicit confirmation before sending anything -- it never files a
  report silently.
- Found and fixed a test-isolation bug introduced while adding the
  above: the crash handler intentionally disables Python's global error
  hook as part of its own error handling, and calling it directly in a
  test leaked that disabled state into unrelated, later tests. Fixed
  with proper setup/teardown.
- Verified the browser-based GUI (`aider --gui`) actually works
  end-to-end -- installed it, launched a real server, and confirmed it
  serves a working page and passes its own internal health check. This
  had never been covered by any automated test and its status was
  previously unknown; it is now confirmed functional.

DEFERRED (tracked, not forgotten)
- Two experimental fuzzy text-matching strategies in the file-editing
  engine (only reachable via a commented-out internal debug tool) were
  investigated but left as-is pending a real decision -- not clearly
  dead, not clearly load-bearing. Revisit if that file is touched for a
  feature.
- Automatic, recurring refresh of the model-name lookup lists (see
  IMPROVED above) is not yet wired up to run on its own -- currently a
  manual/on-demand script. Scheduling this via CI is tracked as an
  explicit action item in Phase 2 (governance), not dropped.

---

## Template for future entries

## Phase N -- <name> (date)

NEW
- ...

IMPROVED
- ...

REPAIRED
- ...

REMOVED
- ...

DEFERRED
- ...
