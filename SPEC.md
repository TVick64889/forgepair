# ForgePair — Product Spec

Status: draft v1
Date: 2026-09-08
Author: Thomas (via Hermes research/design session)

## 1. One-line pitch

The same terminal-native, git-integrated, model-agnostic AI pair-programming
tool aider users already like, minus the two things a solo-maintainer
project structurally can't sustain at scale: governance that doesn't
bottleneck on one person, and a feature/bug backlog that actually gets
worked instead of dedup-closed into silence — plus the handful of
specific, heavily-requested capabilities (MCP, approval gating, honest
error handling) real users have been asking for since 2024 with nowhere
to go.

## 2. Origin / evidence base

This spec is a direct response to a diagnostic of aider-AI/aider
(github.com/Aider-AI/aider), done across three passes:

- **Repo/metadata pass** (GitHub API): stars, commit cadence, PR backlog,
  contributor concentration.
- **Source code pass** (cloned repo, read `aider/models.py`,
  `aider/resources/model-settings.yml`, `aider/report.py`,
  `scripts/issues.py`, `.github/workflows/issues.yml`): how model support,
  crash reporting, and issue triage actually work today (not assumed).
- **Issue/request content pass** (GitHub search + issue bodies): read the
  actual top feature requests and bug reports by reaction count, not just
  titles/counts.

Key findings that drove this spec (verified, not assumed):

- Last commit to aider's `main`: 108 days old at time of research (May 22,
  2026 → Sept 8, 2026). Last PyPI release: Feb 12, 2026 — older than the
  last commit, so recent work never shipped.
- Of 82 commits to main since Jan 2026, 71 (87%) were from a single author
  (paul-gauthier). Everyone else: 1–4 commits each.
- 488 open PRs; oldest open PRs date to July 2024 (2+ years unmerged).
- 1,856 open issues, but a large share are auto-filed real user crash
  reports (via `aider/report.py`'s `exception_handler`, which does prompt
  for confirmation before filing — these are real users, not bot spam).
  A 12-hour cron bot (`scripts/issues.py`) dedups by *exact title match*
  and closes duplicates pointing at the oldest issue with that title —
  without verifying the oldest issue was ever actually fixed. Recurrence
  count is discarded instead of used as a priority/severity signal.
  Feature requests get zero equivalent triage automation — they live or
  die entirely on the founder manually applying a label.
- Aider's dynamic model-metadata system (fetch from litellm's
  `model_prices_and_context_window.json` + OpenRouter API, 24h cache) is
  well-designed and NOT a source of the "model support lags" complaint —
  that turned out to be a UX-polish issue (a small hardcoded fast-path
  list used only to skip an import), not a functional blocker. This part
  of aider's architecture should be reused, not redesigned.
- The OpenRouter metadata fallback path *does* have a real fragility:
  it regex-scrapes rendered HTML from the OpenRouter model page when the
  API cache misses, and fails silently (returns `{}`, falls back to
  generic defaults) if the page markup changes — no visible warning to
  the maintainers or users.
- Top unresolved feature requests, by community reaction count (all
  still open, no implementation, as of this research):
  - MCP (Model Context Protocol) support — issues #3314 (196 👍) and
    #2525 (137 👍), open since Feb/Dec 2024–2025, no implementation.
  - GitHub Copilot as a model provider — #2227, 118 👍, 215 comments
    (the most-discussed open issue in the repo), since Nov 2024.
  - IDE-native presence — VS Code extension request since 2023 (#68,
    26 👍), PyCharm (#483, 34 👍), Emacs (#1913, 62 👍).
  - Approval-gated "confirm each change before applying" mode — #649,
    41 👍, 40 comments, since June 2024. Diffs are shown but not gated.
  - Tool/function-calling integration — #2672, 44 👍.
  - Community-authored roadmap thread "Inspiration from Claude Code"
    (#3362, 50 👍, 50 comments) — users explicitly asking the project to
    catch up to modern agentic-tool UX (deeper planning modes, compound
    git operations like "rebase and resolve conflicts" as one action).
- Real unresolved bugs with reproductions, not just crash-report noise:
  - #3264: on OpenRouter free-tier rate-limit, aider shows **zero**
    error — silently returns 0 tokens with no explanation, no retry.
  - #211: GitPython incompatibility with git index-version-3 repos,
    open since 2023.
  - Provider-specific bugs sitting unfixed with real stack traces
    (ollama_chat ignoring `--timeout`, `UnicodeEncodeError` on surrogate
    characters, various uncaught exceptions with low reaction counts
    that fall below the fix threshold given current maintainer capacity).

## 3. What to keep from aider (don't rebuild what already works)

- Terminal-first, git-native workflow as the primary interface. This is
  aider's actual strength and differentiator — don't dilute it by making
  an IDE plugin the primary experience.
- Apache 2.0 licensing model.
- Dynamic model metadata architecture: fetch pricing/context-window/
  capability data at runtime from a live source (litellm's JSON feed,
  provider APIs), cached locally, rather than hardcoding it in the
  package. Reuse this pattern; extend it, don't replace it.
- Repo-mapping via tree-sitter for large-codebase context — proven
  approach, no evidence it needs redesign.
- Model-agnostic design (works with Claude, GPT, DeepSeek, local models,
  etc. via litellm-style abstraction) — this is aider's edge vs.
  single-vendor tools (Claude Code, etc.) and should stay central.

## 4. What to fix — Governance (root cause of the stale/backlog problem)

**Problem:** single maintainer is the only path to merge, review, and
release. When that person's bandwidth drops, the whole project stalls —
commits stop, PRs queue for years, releases lag behind commits by months.

**Design:**

- Tiered merge rights. A "trusted contributor" tier gets scoped merge
  permissions for low-risk categories only: model metadata updates,
  docs, dependency bumps, test additions. Architecture-affecting changes
  still require designated maintainer review.
- CI as the actual gate for routine changes: merge queue + required
  checks (tests, lint, type-check) — if green, a trusted contributor's
  PR in an approved category merges without waiting on one person's
  personal availability.
- Continuous release: every merge to main auto-tags and publishes to
  PyPI (semantic-release style). Prevents the "commits exist but were
  never shipped" gap seen in aider (commits in May, last release in
  Feb).
- No feature of this governance model should require paying anyone —
  it's a process/automation design, not a "hire more people" plan.

## 5. What to fix — Issue/request triage

**Problem:** current bot dedups by exact title match and closes new
reports pointing at an unverified "canonical" issue; recurrence count is
discarded rather than treated as a severity signal; feature requests get
no automated triage at all.

**Design:**

- Duplicate-count-weighted severity: N reports of the same underlying
  crash within a rolling window auto-applies an escalating severity
  label (e.g. `high-impact`) and notifies the trusted-contributor pool,
  instead of silently closing into a possibly-still-broken issue.
- Verify-before-redirect: before marking a new report "duplicate," check
  whether the canonical issue has a linked fix/commit. If not, don't
  suppress the new report — let volume visibly build.
- Similarity-based clustering (not just exact title match) extended to
  feature requests, so enhancements get the same triage assistance bug
  reports currently get, instead of depending entirely on one person's
  manual labels.
- Public "known issues, ranked by report count" view generated from the
  same triage data — lets users self-check before filing yet another
  duplicate, cutting volume at the source.

## 6. What to fix — Model metadata fragility

- Replace the OpenRouter HTML-scraping fallback with OpenRouter's actual
  `/api/v1/models` JSON endpoint. Scraping is fragile-by-design (breaks
  silently on markup changes, degrades to generic defaults with no
  visible warning).
- Auto-refresh the small hardcoded provider fast-path lists (used today
  only to skip an import when resolving which env var a model needs)
  from the same live metadata source already being fetched, instead of
  hand-maintained Python string lists that visibly drift and generate
  needless "unknown model" warnings for users.

## 7. What to ship — Feature backlog (validated demand, not guesses)

Priority order based on community reaction counts and staleness:

1. **Native MCP client support.** Single largest unaddressed gap vs.
   modern agentic coding tools (Claude Code, Cursor, etc.). ~330
   combined reactions across duplicate aider threads, 1.5+ years
   unaddressed.
2. **Approval-gated "confirm before apply" mode.** Diff-and-approve as
   an atomic, blocking gate per change — not just diff display after
   the fact. Real trust/control gap for users running aider against
   production or shared codebases.
3. **Honest failure handling on provider errors.** Never silently
   return 0 tokens / no response on rate-limit or API failure — surface
   the error, retry with backoff, and tell the user what happened.
4. **GitHub Copilot as a model provider.** Most-discussed open request
   in aider's history (215 comments); users have existing subscriptions
   they want to route through the tool.
5. **Tool/function-calling support**, aligned with how modern LLM APIs
   expose structured tool use — currently a gap vs. competitors.
6. **IDE presence roadmap** (not necessarily full extensions at launch):
   at minimum, a documented integration path for VS Code / editor
   plugins to shell out to the CLI, addressing a 2023-era unmet request
   without diluting the terminal-first core experience.
7. **Fix the specific reproducible bugs** identified above: git
   index-version-3 compatibility, ollama_chat timeout handling, and a
   clean-up pass on the backlog of uncaught exceptions with real repro
   info that never got attention due to maintainer bandwidth.

## 8. Explicit non-goals (things not to chase)

- Becoming an IDE-first product — terminal/CLI stays the primary
  interface; IDE integration is a secondary surface via shell-out, not
  a rewrite.
- Changing the license or governance to a corporate/for-profit model as
  a prerequisite — the governance fix here is process automation
  (tiered merge, CI gating, continuous release), not "raise money and
  hire a team."
- Rebuilding the dynamic model-metadata fetch architecture — it works;
  only the OpenRouter scraping fallback and the hardcoded fast-path
  lists need fixing.

## 9. Naming / availability research (done 2026-09-08)

Chosen name: **ForgePair**

Rationale: "Forge" signals building/crafting code; "Pair" directly
signals lineage from pair-programming / aider's core metaphor. Short,
pronounceable, reads naturally as both a product name and a CLI command
(`forgepair`).

Availability checked and confirmed clear:
- GitHub: `forgepair` user/org unclaimed (404), `forgepair/forgepair`
  repo unclaimed (404).
- npm: `forgepair` package name unclaimed (404 on registry lookup).
- PyPI: `forgepair` package name unclaimed (404 on registry lookup).
- Domains: forgepair.com, forgepair.dev, forgepair.ai, forgepair.io all
  show no DNS record (unregistered as of check date).
- Web search (DuckDuckGo): zero results for "forgepair" — no existing
  brand, product, or company collision found.

Rejected alternatives:
- **Pairloom** — clean on registry/package checks, but is already an
  active, distinct brand: a live iOS dating/matchmaking app
  (pairloom.app, App Store listing), plus an unrelated e-commerce tool
  (pairloomshop.com) and a founder/operator networking site
  (pairloom.io). Real collision risk, avoided despite clean namespace
  checks — a reminder that registry availability alone isn't sufficient
  vetting.
- Other candidates screened and left available but not chosen:
  cadencecli, wayfare-cli, ledgerpair, codetandem, quorum-cli,
  convoy-cli, pairforge (pairforge itself was GitHub-taken).

## 10. Open questions for next pass

- Actual technical design for MCP client integration (what surface does
  aider's Coder/edit-format abstraction need to expose to MCP tools?).
- Concrete spec for the approval-gated mode: per-hunk vs. per-file vs.
  per-message granularity; how it interacts with `--yes`/non-interactive
  runs.
- Whether to fork aider's codebase directly (Apache 2.0 permits this
  cleanly) vs. build fresh — forking preserves the tree-sitter repo-map
  and litellm integration work already proven out, likely the faster
  path to parity before adding differentiators.
- Governance bootstrapping: who holds initial maintainer/tiered-merge
  authority before a real contributor base exists.
