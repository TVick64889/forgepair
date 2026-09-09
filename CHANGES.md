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

## Phase 2 -- Governance (2026-09-08)

NEW
- Contributor merge tiers documented in CONTRIBUTING.md: low-risk
  changes (model metadata, docs, dependency bumps, test-only changes)
  vs. changes requiring deeper review (core chat/edit loop, git
  commit/attribution logic, edit-application pipeline, CI/release
  automation itself).
- Continuous-release automation added (currently dry-run): computes
  and reports what the next release version would be on every merge to
  main, directly targeting the exact problem that hurt upstream aider
  (commits sat on main for months with no corresponding release).
  Not live yet -- reports the number, doesn't publish -- until there's
  a real package to publish.
- Weekly automated check that the model-name lookup lists (see Phase 1)
  haven't gone stale, opening an issue if they have. Closes the gap
  Phase 1 explicitly flagged: regenerating the lists was fixed, but
  nothing was scheduled to actually run the regeneration.
- Branch protection enabled on `main`: required status checks (full
  test suite across 5 Python versions on both Windows and Ubuntu, plus
  linting and a Docker build check) must pass before anything can
  merge -- including for the repo owner. Verified directly by
  attempting a direct push (correctly rejected) and by running a real
  pull request through the full flow to a real merge.

IMPROVED
- Fixed a real CI bug in the process of setting this up: the automated
  Docker build check was still configured (leftover from upstream) to
  push images to Docker Hub using credentials that don't exist for
  this project, so it failed on every single run since the fork was
  created. Changed it to build-only -- it still verifies the Dockerfile
  works, just doesn't try to publish anywhere. (Publishing real Docker
  images is a distribution decision for closer to an actual release,
  not something to wire up speculatively now.)
- That same Docker check was also very slow (20+ minutes, sometimes
  longer). The slow part was building for a second CPU architecture
  (arm64) using software emulation, which is much slower than it needs
  to be for a check that's just confirming "does this still build."
  Narrowed it to one architecture plus build caching -- same check,
  same coverage of the thing that matters, about 4x faster (~6 minutes).
- Found and fixed a subtler problem while testing branch protection:
  several of the required checks had filters that skipped them
  entirely for certain kinds of changes (like README-only edits).
  That's fine on its own, but combined with "this check is required
  to merge," it meant some pull requests could get permanently stuck
  with no way to pass, because the check required to unblock them
  would just never run. Confirmed this by deliberately opening a test
  PR that touched only documentation and watching it get stuck.
  Removed those filters so every required check always runs.

---

## Phase 3 -- Issue triage redesign (2026-09-08)

NEW
- Feature requests now get automated triage help for the first time.
  Previously only bug reports got any automated grouping at all;
  feature requests relied entirely on a human noticing duplicates.
  Similar open feature requests are now automatically detected and
  flagged with a comment linking them together, so duplicate asks are
  visible without reading the entire backlog.
- A single, always-current "known issues" page (a pinned, auto-updated
  GitHub issue) lists the most-reported recurring bugs and any related
  feature-request clusters, ranked by how many people have hit them.
  Anyone can check it before filing a new report.

IMPROVED
- Fixed the core problem with the original duplicate-bug-report
  handling: it used to close new reports of a known crash and quietly
  point people at the original issue -- even if that original issue
  was never actually fixed. Now, a new report is only closed as a
  duplicate once there's real evidence the original was resolved
  (a linked fix). If it wasn't, the group is flagged as high-impact
  instead, so a bug hit by many people becomes MORE visible over time,
  not less.

REPAIRED
- Found and fixed a real, previously-invisible bug while verifying
  this system end-to-end against live data: the "which report came
  first" comparison never worked correctly because of a timezone
  mismatch (comparing this server's local time against GitHub's UTC
  timestamps), so the original bot's duplicate-detection logic never
  actually found a "first" report to point at -- confirmed by testing
  it directly with real filed issues. Fixed across all four places in
  the script with this same timezone bug.
- Enabled GitHub Issues on the project repository, which had been
  off (a default for new forks) and would have silently prevented any
  of this automation from working at all.

DEFERRED (tracked, not forgotten)
- The known-issues dashboard's text-generation logic is written inline
  inside the function that also calls GitHub's API, rather than as its
  own separable piece. That made it harder to test on its own -- it
  could only be verified by actually running it against the real repo
  (which was done, and confirmed working), not by a fast, isolated
  test. Worth cleaning up if this script is touched again, but not
  worth doing as a standalone change right now.

---

## Phase 4 -- Approval-gated apply mode (2026-09-09)

NEW
- New `--confirm-edits` option. When turned on, ForgePair shows you
  which file it's about to change and asks for a yes/no before writing
  anything to disk -- one prompt per file, not per individual change,
  so you're not click-through-fatigued on a big multi-file edit. Off
  by default, so nothing changes unless you turn it on.
- Works correctly in scripted/non-interactive use too: if you've also
  set "always say yes" mode and nobody's there to answer the prompt,
  an unconfirmed file's edit is safely skipped rather than either
  silently applying anyway or hanging forever waiting for an answer
  that will never come.

REPAIRED
- N/A this phase -- implemented directly against an existing, already
  well-tested extension point in the codebase, no bugs found needing
  a fix along the way.

---

## Phase 5 -- Honest failure handling on provider errors (2026-09-09)

REPAIRED
- Fixed a real, previously-reported bug: sometimes an AI provider would
  respond but send back nothing usable -- no answer, no error -- often
  during a rate limit or outage. Aider would just... stop, showing
  "0 received" with zero explanation, leaving the user wondering what
  happened or whether it was their own fault. Now this is treated like
  any other connection problem: you get a clear message saying what
  happened, and it automatically retries a few times with increasing
  waits before finally giving up -- the same way it already handles
  other provider hiccups, just extended to cover this case too.
- The bug turned out to be worse in one of the two response modes
  (non-streaming) than the other: the streaming mode at least printed
  a warning (though it still didn't retry), while the non-streaming
  mode failed completely silently with no warning of any kind. Both
  are fixed the same way now.

---

## Phase 6 -- MCP client support (2026-09-09)

NEW
- Native MCP (Model Context Protocol) client support via a new "agent"
  mode (`--edit-format agent`). Declare MCP servers in a `.mcp.json`
  file (same schema as Claude Code/Claude Desktop, so anyone who's
  configured MCP for those tools will recognize it immediately) and
  aider will connect to them, discover their tools, and let the model
  call them mid-conversation -- reading files, running scripts,
  querying external services, or anything else an MCP server exposes,
  not just the built-in file-edit workflow.
- Every MCP tool call requires explicit approval before it runs,
  regardless of `--yes-always` or `--confirm-edits` -- MCP tools can
  have side effects well beyond editing a file in your repo, so the
  blast radius is less predictable and always gets a confirmation
  prompt.
- New `--mcp-config-file` flag to point at a specific `.mcp.json` file;
  otherwise aider searches home directory, git root, and cwd (same
  search order as `.aider.conf.yml`/`.env`), merging by server name
  with the more specific file winning.
- `${ENV_VAR}` interpolation in `.mcp.json` values (same syntax as
  Claude Code/Claude Desktop), so a server requiring an API key or
  auth token can be configured -- and the file safely committed --
  without ever writing the secret itself into the file.

IMPROVED
- Fixed a real gap in the existing tool-calling plumbing: aider's
  streaming response handler only ever read the older, deprecated
  single-function-call shape from providers, never the current
  multi-tool `tool_calls` shape -- so under the default `--stream`
  mode, any response that used the modern tool-calling format was
  silently dropped and misread as an empty/failed response. Fixed as
  part of building MCP support, but benefits any future tool-calling
  work, not just MCP.

DEFERRED
- MCP "resources" and "prompts" (only "tools" are implemented so far) --
  a server that primarily exposes resources or prompt templates rather
  than callable tools would connect successfully but show nothing
  usable today.
- Authentication/custom headers for remote HTTP MCP servers -- only
  stdio (local subprocess) and unauthenticated HTTP servers can be
  connected to; most real hosted MCP servers require a bearer token or
  API key, which isn't wired up yet.
- GitHub Copilot as a model provider, general non-MCP tool-calling,
  IDE integration contract, and the remaining reproducible bug fixes
  (SPEC.md §7 items 4-7) -- explicitly lower priority, tracked as
  Phase 7.

VERIFIED
- Live demo run 2026-09-09: aider (--edit-format agent) against
  @modelcontextprotocol/server-filesystem (a real, commonly-used MCP
  server, 14 tools) and a real Anthropic model (claude-haiku-4-5),
  real billed API calls. The model listed a directory, then
  autonomously read a file it found there in a second sequential tool
  call, each individually gated by a real approval prompt, both
  results correctly fed back and reflected in its final answer.

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
