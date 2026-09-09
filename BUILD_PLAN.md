# ForgePair — Build Plan

Status: draft v1
Date: 2026-09-08
Depends on: SPEC.md, ARCHITECTURE_REVIEW.md (read both first — this plan
assumes their findings and doesn't re-derive them)

Approach: fork aider-AI/aider (Apache 2.0), per the fork-vs-rebuild
decision in ARCHITECTURE_REVIEW.md §10/§12. Every phase below cites the
specific finding it's acting on so the plan stays traceable to evidence,
not assumption.

---

## Phase 0 — Fork setup and baseline verification

Goal: get a clean, working copy under ForgePair's own name, prove it
still runs, before changing anything.

1. Fork github.com/Aider-AI/aider to a new `forgepair/forgepair` GitHub
   repo (name/availability already confirmed in SPEC.md §9).
2. Clone locally to C:\projects\forgepair\src (separate from the
   read-only research clone at hermes-work\aider-src).
3. Rename the package identity: `pyproject.toml` (`name = "aider-chat"`
   → `forgepair`, update `[project.scripts]` entry point), top-level
   `aider/` package could stay as an internal module name initially to
   minimize churn, or be renamed — decide based on how much import-path
   noise you're willing to eat in the first PR. Recommend: keep internal
   module name as-is for phase 0, rename only the distribution/CLI-command
   name. Revisit internal renaming later once the fork is stable.
4. Update `pyproject.toml` homepage URL, README branding, `CNAME` file
   (website), `aider/urls.py` (points at Aider-AI's GitHub — needs to
   point at ForgePair's own issue tracker once the triage system in
   Phase 3 exists).
5. Install dependencies (`requirements.txt`), run the full existing test
   suite (36 files, 12,264 lines, per ARCHITECTURE_REVIEW.md §11.7) and
   confirm it passes clean on the fork before any modification. This is
   the baseline — if something's already broken pre-fork, you need to
   know that before attributing any future failure to your own changes.
6. Do NOT yet touch CI/release automation — first get a manual,
   understood build/test/install cycle working locally.

Exit criteria: `pip install -e .`, `forgepair` (or `aider` if not yet
renamed) launches against a scratch git repo, full test suite green.

---

## Phase 1 — Cleanup pass (remove confirmed dead weight before building on top)

Goal: don't build new features on top of known-dead or known-fragile
code. Everything here is already confirmed, not speculative — see
ARCHITECTURE_REVIEW.md citations.

1. Delete the three confirmed-dead coder files (§11.5): 
   `aider/coders/editblock_func_coder.py`,
   `aider/coders/wholefile_func_coder.py`,
   `aider/coders/single_wholefile_func_coder.py`, plus their matching
   `*_prompts.py` files. Confirmed unreachable via `Coder.create()`,
   zero test coverage, safe removal.
2. Resolve the two-tree-sitter-binding-path situation (ARCHITECTURE_REVIEW
   §10 item 1: `CACHE_VERSION = 3` vs `4` depending on `USING_TSL_PACK`
   in repomap.py). Pick one binding path (recommend the newer
   `tree-sitter-language-pack`, since it's the one actively gaining
   cache-version support) and drop the legacy path, or explicitly
   document why both must stay if there's a real compatibility reason
   not yet uncovered.
3. Replace the OpenRouter HTML-scraping fallback (`models.py`,
   `fetch_openrouter_model_info`, confirmed fragile in earlier research
   pass) with OpenRouter's actual `/api/v1/models` JSON endpoint. Keep
   the existing `OpenRouterModelManager` cache structure — just swap
   the data source.
4. Auto-refresh the hardcoded `OPENAI_MODELS`/`ANTHROPIC_MODELS`
   fast-path lists (models.py lines 33-96) from the same live metadata
   source already being fetched (`ModelInfoManager`), instead of
   hand-maintained Python string lists. This is cosmetic-only
   (confirmed: these lists don't gate functionality, only fast-path env
   var lookup — see prior research), so it's low-risk, do it early to
   remove a recurring PR-noise source.
5. Decide and document the fate of the two unused-but-present fuzzy
   strategies in `search_replace.py` (`dmp_apply`, char-level, and
   `git_cherry_pick_sr_onto_so`) — confirmed present but not wired into
   `editblock_strategies`/`udiff_strategies` (§11.3). Either delete if
   truly dead, or add them to the live strategy chain with tests if
   they were a deliberate future improvement someone didn't finish.

   DONE (re-audited and resolved 2026-09-09): re-confirmed neither
   function had any test coverage, any caller outside each other, or
   any caller outside the debug/benchmark harness at the bottom of the
   file (`proc()`/`main()`) -- and even there, both were already
   commented out of the harness's own default `strategies` list.
   `dmp_apply` was also functionally superseded by `dmp_lines_apply`
   (already in the live strategy chains) -- same diff-match-patch
   approach, operating on lines instead of raw characters. Deleted
   both, plus `map_patches()` (only ever called by `dmp_apply`, now
   orphaned) and the now-stale references to both in `proc()`'s
   `short_names`/`strategies` locals. Verified the debug/benchmark
   harness (`proc()`) still runs correctly end-to-end after the
   removal -- ran it directly against a real search/replace/original
   fixture set, got real 'pass' results across all four preproc
   variants of the remaining `dmp_lines_apply` strategy, not just an
   import-time smoke check. Full search/replace-related test suite (29
   tests) and pre-commit (isort/black/flake8/codespell) pass clean.
6. Write the two confirmed missing test files (§11.7 gap list):
   `test_patch.py` for `patch_coder.py` (flagged as the highest-risk
   untested complex code in the whole codebase) and `test_report.py`
   for the crash-reporting flow (needed anyway before Phase 3 reworks
   it).
7. Runtime-verify `gui.py` (§11.6, unconfirmed liveness): actually
   launch it against a scratch repo. Decide explicitly: carry forward,
   fix, or drop for v1. Don't leave it in an unknown state.

Exit criteria: dead code removed, fragile scraping path replaced,
two new test files passing, gui.py status explicitly resolved
(not just noted as "unknown").

---

## Phase 2 — Governance infrastructure (SPEC.md §4)

Goal: make sure the thing that killed the original project's velocity
(single-maintainer bottleneck) can't happen here, before there's a
backlog to get stuck.

1. Define contributor tiers in a CONTRIBUTING.md: what counts as
   "low-risk" (model metadata/docs/dependency bumps/tests) vs. requires
   deeper review (anything touching base_coder.py, repo.py's commit/
   attribution logic, or the edit-application pipeline for any coder).
2. Set up branch protection + required status checks on the default
   branch (tests must pass, lint must pass) so CI is a hard gate, not
   advisory.
3. Set up a merge queue (GitHub's native merge queue, or a bot-based
   equivalent) so approved, green PRs in the low-risk tier merge without
   waiting on a single person's calendar.
4. Wire continuous release: a GitHub Action that runs on every merge to
   main, bumps version (setuptools_scm is already in place per
   pyproject.toml — it auto-derives version from git tags, so this is
   mostly "auto-tag on merge" plus a PyPI publish step), and publishes.
   This directly prevents the exact aider failure mode (commits existed,
   last PyPI release was 3+ months older than last commit).
5. Recruit/assign at least one other trusted-tier contributor before
   Phase 3+ work starts generating a PR backlog — governance
   infrastructure with nobody but you using it doesn't test the theory.

TRACKED SUB-ITEM (do not skip): schedule scripts/update_model_lists.py
(added in Phase 1 item 4) to run automatically via CI on a recurring
basis (e.g. weekly), either failing a build / opening an issue when
`--check` finds drift, or auto-opening a PR with the regenerated lists
for review. Without this, Phase 1's fix only solved the *mechanism* of
model-list staleness (accurate regeneration), not the *trigger*
(something has to actually run it) -- confirmed as an open gap during
Phase 1 review, explicitly deferred to here rather than dropped.
STATUS: DONE -- see .github/workflows/model-list-freshness.yml.

TRACKED SUB-ITEM (do not skip): upgrade the pinned black version in
`.pre-commit-config.yaml` (currently 23.3.0, incompatible with Python
3.12+) to something modern. Deferred during Phase 2 because it
reformats a large amount of unrelated pre-existing code (confirmed by
test-running it) -- needs its own isolated, reviewed PR, not bundled
into other work. Workaround documented in CONTRIBUTING.md
(persistent Python 3.11 .venv-precommit/) in the meantime.
STATUS: NOT DONE -- workaround only, real fix still outstanding.

TRACKED SUB-ITEM (do not skip): fix the flaky pandoc-download test
failures in tests/scrape/test_scrape.py (5 tests). Root cause is
pypandoc.download_pandoc() intermittently failing with "Invalid pandoc
version latest." in CI (observed on Ubuntu 3.10 and Windows 3.10) --
not a bug in aider's own code (try_pandoc() in aider/scrape.py handles
the failure correctly). These tests became actively blocking once
branch protection made them required (see main tracked-item list
above), so they were skipped with unittest.skip() and a documented
reason rather than fixed, to unblock merges. Real fix options noted in
the test file itself: pin/vendor a known pandoc version instead of
"latest", or mock pypandoc entirely instead of hitting the real
download path in these tests.
STATUS: NOT DONE -- workaround only (tests skipped), real fix still
outstanding.

TRACKED SUB-ITEM (informational, not a defect): Docker Hub publishing
is intentionally NOT configured. docker-release.yml (tag-triggered)
and the DOCKERHUB_USERNAME/DOCKERHUB_PASSWORD secrets it needs remain
unset by deliberate decision (discussed directly) -- no Docker Hub
account exists for ForgePair yet and there's no current user demand
for a pullable image. docker-build-test.yml was changed to build-only
specifically so CI doesn't depend on this. Revisit when closer to an
actual release; at that point also switch to a scoped Docker Hub
access token rather than a raw username/password, per the same
dry-run-then-flip-live pattern already used for PyPI/continuous-release.
STATUS: DEFERRED BY DESIGN -- not a bug, revisit before any real release.

TRACKED SUB-ITEM (informational, not a defect): branch protection's
required-checks list uses the name `build (X.Y)` (once per Python
version), which is shared identically by both ubuntu-tests.yml and
windows-tests.yml -- GitHub requires ALL check runs matching a
required name to pass, not just one, so this correctly requires both
OS's test runs; confirmed directly (a PR was blocked until both
Windows and Ubuntu legs passed). Noted here only so this isn't
mistaken for a misconfiguration later if someone notices the shared
name and assumes only one OS is actually being gated.
STATUS: WORKING AS INTENDED -- documented for future clarity, no action needed.

Exit criteria: a PR from a second contributor, in a defined low-risk
category, merges via the queue without you personally clicking merge,
and a release auto-publishes from that merge.

---

## Phase 3 — Issue/request triage redesign (SPEC.md §5)

Goal: replace the dedup-and-silently-close bot with one that treats
recurrence as a severity signal and gives feature requests the same
triage feature bug reports get.

1. Port `scripts/issues.py`'s cron structure (12h GitHub Action,
   confirmed working mechanism) but change the duplicate-handling logic:
   - Before closing a new report as duplicate, check whether the
     canonical issue has a linked closing commit/PR. If not, don't
     close — instead increment a report-count and escalate a severity
     label once a threshold is crossed.
   - Add a "known issues, ranked by report count" generated page (could
     be a simple auto-updated markdown/JSON file served off the repo,
     or a GitHub issue pinned and periodically rewritten) fed by the
     same duplicate-detection data.
2. Extend triage to feature requests: cluster open enhancement-labeled
   issues by embedding similarity on title+body (a small script using
   any local/cheap embedding model — this doesn't need to be
   sophisticated, just better than "exact title match only," which is
   what bug-report clustering currently uses and feature requests get
   nothing).
3. Keep `report.py`'s existing crash-reporter UX as-is (confirmed in
   research: it already requires explicit user confirmation before
   filing, it's not spam) — the fix is entirely on the triage-bot side,
   not the reporting side.

Exit criteria: a synthetic test — file 3 near-duplicate crash reports,
confirm the bot escalates rather than dedup-closes into silence when
the canonical issue has no linked fix; file 2 similar feature requests
under different wording, confirm they get clustered/flagged.
STATUS: DONE -- verified live against TVick64889/forgepair on
2026-09-08. Filed 3 duplicate crash reports (unresolved canonical),
confirmed escalation not silent closure. Closed canonical with a
linked fix, confirmed remaining duplicates then correctly verified-
and-closed. Filed 2 similar + 1 dissimilar feature request, confirmed
correct clustering. All test issues cleaned up afterward. See
CHANGES.md Phase 3 and PR #12 for full details, including a real
timezone bug found and fixed during verification.

TRACKED SUB-ITEM (do not skip): extract update_known_issues_dashboard()'s
body-text-generation logic (scripts/issues.py) into its own pure
function, e.g. build_dashboard_body(high_impact_groups,
feature_clusters) -> str. Currently it's inline inside the function
that also does the GitHub API find/create/patch calls, which means it
can't be unit-tested in isolation -- only verified by running the
whole thing against the real repo (which was done, see exit criteria
above, but a fast local test would be better going forward).
STATUS: NOT DONE -- deferred, low priority, noted for next time this
script is touched.

---

## Phase 4 — Approval-gated apply mode (SPEC.md §7 item 2)

Goal: implement the #649 feature (confirm each change before it's
applied), using the exact extension point identified in the
architecture review.

1. Add a `confirm_ask` call at the choke point identified in
   ARCHITECTURE_REVIEW.md §4: inside `Coder.apply_updates()`
   (base_coder.py, around line 2304, right before `self.apply_edits(edits)`
   is called), following the same idiom already used 7+ other places in
   the file (e.g. the shell-command confirmation at line 2456, which
   uses `explicit_yes_required=True` — likely the right variant here too
   since this is a higher-stakes action than a URL-add prompt).
2. Design the granularity as a CLI flag / `.aider.conf.yml` setting
   (e.g. `--confirm-edits` or a new `edit_format`-independent mode
   flag), not a hardcoded always-on behavior — needs to be opt-in to not
   break the flow for people who want current behavior.
3. Decide and implement the actual granularity: per-file (approve/reject
   all edits to file X in this turn) is the natural first cut since
   `prepare_to_edit`/`allowed_to_edit` already operate per-path; a
   per-hunk/per-edit granularity is a larger change since `apply_edits`
   is currently coder-specific and edit-shape varies by format
   (SEARCH/REPLACE blocks vs. unified diff hunks vs. whole-file
   replacement vs. PatchAction chunks) — recommend shipping per-file
   first, evaluate demand for finer granularity after.
4. Make sure it composes correctly with the existing reflection/retry
   loop (max 3 reflections, base_coder.py line 101) and with
   `--yes`/non-interactive mode (a rejected edit in non-interactive mode
   should presumably skip that file's edit and continue, not hang
   waiting for input that will never come — needs an explicit decision
   and test).
5. Test coverage: extend `test_coder.py` with cases covering approve,
   reject, and reject-in-non-interactive-mode.

Exit criteria: running with the new flag, a proposed edit is shown and
requires explicit approval before `apply_edits` writes to disk; without
the flag, behavior is unchanged (regression tested against existing
suite).
STATUS: DONE -- `--confirm-edits` flag implemented, 9 new tests
covering approve/reject/per-file-granularity/non-interactive-mode/
disabled-by-default pass-through, plus manual end-to-end verification
against a real git repo (both approve and reject paths). Full existing
test suite (513 -> 522 tests) still passes unchanged. See CHANGES.md
Phase 4 and PR #15.

---

## Phase 5 — Honest failure handling on provider errors (SPEC.md §7 item 3)

Goal: fix the class of bug behind #3264 (silent 0-token response on
rate-limit, no error surfaced).

1. Audit `Coder.send()` (base_coder.py ~line 1783) and the exception
   handling around the litellm completion call for paths where a
   provider error/rate-limit could result in an empty
   `partial_response_content` with no exception raised and no user-facing
   message — the litellm exception-normalization system (`exceptions.py`,
   confirmed well-designed in ARCHITECTURE_REVIEW §11.1) should already
   catch true exceptions; the bug is more likely a response that
   "succeeds" at the HTTP level but returns empty/malformed content
   (e.g. a streamed response that terminates early without an explicit
   error chunk).
2. Add an explicit check: if a message send completes with zero content
   and no tool call, treat it as a failure condition — surface a clear
   `io.tool_error()` message (not a silent blank turn), and apply the
   same retry/backoff pattern already used for `ExInfo(retry=True)`
   exceptions in exceptions.py, rather than leaving the user staring at
   "Tokens: 2.9k sent, 0 received" with no explanation.
3. This is exactly the kind of gap the patch_coder.py "tolerate but warn
   instead of silently failing" pattern (§11.4 of the architecture
   review) should be generalized from — use that as the house style: no
   silent no-ops anywhere in the response pipeline.
4. Test coverage: mock a provider response that streams zero content
   with a 200-equivalent status, assert the user sees an explicit error
   rather than a blank turn.

Exit criteria: reproducing the original #3264 scenario (rate-limited
free-tier model) against a mocked provider response now produces a
visible error and retry, not silence.
STATUS: DONE -- EmptyResponseError added, raised from Coder.send() and
caught in send_message()'s existing retry loop with the same
exponential-backoff pattern already used for retryable litellm
exceptions. Confirmed both response modes were affected (streaming had
a partial fix -- a warning with no retry; non-streaming had nothing at
all). 5 new tests (mocked non-streaming/streaming, empty/real content,
visible-error assertion). Manually reproduced the exact #3264 symptom
end-to-end via a full Coder.run() call with an always-empty mocked
response: confirmed 8 retries with visible distinct messages and
increasing backoff, then explicit failure -- not silence. See
CHANGES.md Phase 5 and PR #16.

---

## Phase 6 — MCP client support (SPEC.md §7 item 1, the single biggest feature gap)

Goal: implement native MCP support, reusing the existing tool-call
plumbing identified in ARCHITECTURE_REVIEW.md §5 rather than building
tool-calling from scratch.

STATUS: Steps 1-6 DONE (branch phase6-mcp-client, commits 83c6fb7b2,
51746a5d9, 79ddb87ea, 021efa9cc, 40e096dd4). Step 7's mock-server round
trip test done early (needed as verification ground truth for steps
2-3). Exit criteria FULLY MET as of 2026-09-09: live demo run against
a real MCP server (@modelcontextprotocol/server-filesystem, 14 real
tools) with a real LLM (Anthropic claude-haiku-4-5-20251001, real
billed API calls, ~$0.0095 total demo cost) and a real approval gate
in front of tool execution. Two sequential real tool calls in one
task (list_directory, then read_text_file on a file it found),
both individually gated and approved, both results correctly fed back
and used in the final answer. Full transcript preserved at
$LOCALAPPDATA/Temp/forgepair-mcp-demo/demo_output2.log. Along the way,
found and fixed 3 real gaps in plumbing ARCHITECTURE_REVIEW.md assumed
was already generic: Model.send_completion() hardcoded tool_choice to
force exactly one function (broke as soon as 2+ tools -- e.g. multiple
MCP tools -- were passed); show_send_output_stream() never read
delta.tool_calls (only the deprecated single delta.function_call), so
a tool_calls-only streamed response was silently dropped under
--stream (aider's default) and would have been misdiagnosed as an
EmptyResponseError; aider's Coder is 100% synchronous but the mcp SDK
is fully async, requiring a background-event-loop-thread bridge
(aider/mcp/manager.py) rather than the "purely additive" integration
originally assumed. Also found and fixed post-implementation: our
.mcp.json didn't support Claude Code/Desktop's ${ENV_VAR}
interpolation syntax, meaning authenticated MCP servers would have
required hardcoding secrets into a commonly-committed file -- fixed
(commit 40e096dd4). Two remaining protocol-completeness gaps
identified but deliberately deferred to Phase 7 (not blocking v1):
MCP "resources"/"prompts" primitives (only "tools" implemented), and
auth/headers support for remote HTTP MCP servers (MCPServerConfig.url
has no headers/auth field -- most real hosted MCP servers requiring a
bearer token can't be connected to yet, only stdio and unauthenticated
HTTP servers).

1. Add an MCP client dependency (the official `mcp` Python SDK) and a
   config surface for declaring MCP servers (`.aider.conf.yml` entry,
   e.g. `mcp-servers: [...]`, mirroring how Claude Code/other MCP hosts
   configure servers — check their config schema for a familiar shape
   users will already recognize).

   DONE: mcp>=1.9.0 added to requirements.in, recompiled for
   --python-platform linux (confirmed pywin32 correctly excluded,
   avoiding the exact CI breakage the old requirements.in comment
   warned about). Config surface ended up as a separate .mcp.json file
   (not embedded in .aider.conf.yml) -- configargparse's
   YAMLConfigFileParser stringifies nested YAML dicts, so a list of
   server dicts under .aider.conf.yml would have come back as literal
   Python-repr strings, not structured data (confirmed empirically).
   .mcp.json uses the exact mcpServers schema as Claude Code/Claude
   Desktop (verified against real local config files on this machine),
   which is arguably an even closer match to "familiar shape" than the
   originally-proposed .aider.conf.yml embedding. See aider/mcp/config.py.

2. On startup, connect to configured MCP servers, enumerate their
   exposed tools, and translate each tool's JSON schema into the
   `functions` parameter format `Coder.send()` already accepts
   (confirmed existing mechanism, base_coder.py line 1783).

   DONE: aider/mcp/manager.py (MCPManager). MCPTool.to_function_schema()
   does the translation, namespaced as mcp__<server>__<tool>.

3. Route resolved `tool_calls` (already parsed via the existing
   streamed-partial-JSON-repair logic in `parse_partial_args()`,
   base_coder.py line 2338) to the appropriate MCP server instead of
   (or in addition to) the current internal edit-application path — this
   requires a dispatch layer that distinguishes "this tool_call is an
   aider-internal edit" vs. "this tool_call routes to MCP server X."

   DONE: AgentCoder (edit_format="agent") never does internal edit
   parsing at all -- everything routes to MCP. See design note under
   step 6.

4. Feed MCP tool results back into the message loop as a new message
   (role: tool, matching whatever litellm's/the underlying API's
   tool-result message shape is) and continue the conversation.

   DONE: AgentCoder.reply_completed() appends role="tool" messages to
   cur_messages and drives another turn via reflected_message, reusing
   aider's existing reflection loop (run_one) rather than adding a
   second competing multi-turn mechanism.

5. Decide whether MCP tool use requires the same approval gate built in
   Phase 4 — likely yes, arguably even more important for MCP since
   tools can have arbitrary side effects (not just file edits) —
   recommend MCP tool calls default to requiring confirmation
   regardless of the Phase 4 flag setting, since the blast radius is
   less predictable than an in-repo file edit.

   DONE: every MCP tool call goes through
   io.confirm_ask(explicit_yes_required=True) unconditionally, not
   tied to --confirm-edits. Same non-interactive-declines-by-default
   semantics as Phase 4 (--yes-always does NOT auto-approve MCP calls).

6. New coder mode or extension of existing modes: decide whether MCP
   tool access is a property of specific edit-formats/coders (e.g. only
   available in a new "agent" mode) or globally available across all
   coders — recommend starting scoped to one new mode to control the
   surface area, mirroring how `ArchitectCoder` is a distinct mode
   rather than a flag on every coder.

   DONE: AgentCoder, edit_format="agent". See aider/coders/agent_coder.py.

7. Test coverage: a mock MCP server exposing a trivial tool, full
   round-trip test (aider discovers tool → model calls it → result
   returned → conversation continues).

   DONE (mock server + mocked-LLM round trip, PLUS live real-server/
   real-LLM demo): tests/fixtures/mcp_servers/echo_server.py (a real
   FastMCP server, not an SDK mock) + tests/basic/test_mcp_manager.py
   + tests/basic/test_agent_coder.py (full connect->call->approve->
   feed-back->second-turn cycle). Live demo (2026-09-09): real
   @modelcontextprotocol/server-filesystem + real Anthropic API,
   confirmed in demo_output2.log.

Exit criteria: a working demo against at least one real, commonly-used
MCP server (e.g. a filesystem or web-search MCP server) with an
approval gate in front of tool execution.

STATUS: MET (2026-09-09) -- @modelcontextprotocol/server-filesystem,
real Anthropic API (claude-haiku-4-5-20251001), approval gate fired
and was answered for two sequential real tool calls in one task
(list_directory then read_text_file), both results correctly used in
the model's final answer. See demo_output2.log for the full transcript.

---

## Phase 7 — Remaining validated feature backlog (SPEC.md §7 items 4-7)

Lower priority than Phases 4-6 (approval gating and MCP are the two
biggest evidence-backed asks). Re-scoped 2026-09-09, after Phase 6
shipped, against current upstream reality (issue threads re-read,
actual dependency versions checked) rather than the original
speculative wording -- three of the four items below turned out
smaller than originally scoped, one confirmed as-scoped.

RECOMMENDED SEQUENCING (smallest verified win first):
1. Item 4a (GitPython index-v3) -- literally zero code change, just a
   verification test + closing the upstream-inherited issue with
   evidence. Do this first, it's nearly free.
2. Item 2 (tool/function-calling, #2672) -- close as subsumed by
   Phase 6, no code needed. Do alongside item 4a.
3. Item 1 (GitHub Copilot provider) -- re-scoped from "build an
   adapter" to "wire up + test + document litellm's existing native
   provider." Real remaining work, but much less than originally
   estimated.
4. Item 4b (ollama_chat timeout) -- needs more investigation before
   committing to a fix approach; may require an upstream litellm fix
   rather than an aider-side one.
5. Item 3 (IDE presence) -- lowest urgency, mostly a documentation
   task; SPEC.md's own non-goals already deprioritize this.

1. GitHub Copilot as a model provider (#2227, 118👍/215 comments) —
   likely implementable via litellm if litellm already supports a
   Copilot adapter, otherwise needs a custom provider adapter following
   the pattern of aider's existing provider-specific handling
   (`github_copilot_token_to_open_ai_key`, already present in models.py
   per the structural map — worth checking whether partial Copilot
   support already exists and just needs finishing, before assuming
   it's greenfield).

   RE-SCOPED (2026-09-09): confirmed litellm (we're on 1.82.3) now
   ships a fully native `github_copilot/` provider --
   `.venv/Lib/site-packages/litellm/llms/github_copilot/` -- with its
   own OAuth device-flow authenticator (login, token exchange,
   refresh, local caching under `~/.config/litellm/github_copilot/`),
   confirmed working live (real device codes generated against
   GitHub's real API when `model='github_copilot/gpt-4o'` was probed
   directly). This is categorically more complete than aider's current
   hand-rolled `github_copilot_token_to_open_ai_key()`
   (models.py:1036), which requires the user to already possess a
   `GITHUB_COPILOT_TOKEN` and does no device-flow login itself.
   aider currently has ZERO references to `github_copilot/` anywhere
   in its own code -- still only wired to the old manual
   `OPENAI_API_BASE`+`OPENAI_API_KEY`+`openai/`-prefix workaround (see
   aider/website/docs/llms/github.md, also confirmed stale against
   current upstream issue #2227 discussion).
   Read the last ~10 real comments on #2227 (most recent: Dec 2025):
   community consensus is that basic connectivity already works via
   litellm's native provider once configured by hand (one user's
   working ~/.aider.conf.yml + ~/.aider.model.settings.yml posted
   in-thread), but (a) aider's own docs still describe the old
   workaround, not the native provider, and (b) the required
   `Editor-Version`/`Copilot-Integration-Id` extra_headers currently
   have to be hand-added via model-settings.yml rather than being an
   aider default the way they already are for the old
   `GITHUB_COPILOT_TOKEN` path (models.py:1140-1145).
   REMAINING WORK (smaller than original estimate): (a) extend the
   `GITHUB_COPILOT_TOKEN in os.environ` extra_headers default at
   models.py:1140 to also apply when `model.startswith("github_copilot/")`,
   so headers aren't something every user must hand-configure; (b)
   rewrite aider/website/docs/llms/github.md to document the native
   `github_copilot/` provider as the primary path (device-flow login,
   no manual token copying from `apps.json`), keeping the old
   OPENAI_API_BASE approach as a documented fallback for anyone who
   already has it working; (c) add model-settings.yml entries for
   common github_copilot/* models if litellm's own metadata doesn't
   already cover them (untested -- litellm's get_model_info() also
   triggers the live OAuth flow, so this needs a real device-flow
   login to verify, not just static inspection); (d) NO test coverage
   exists for this path at all today (grep confirmed zero matches in
   tests/) -- any new work here should not be merged without at least
   one test, even if it has to mock the Authenticator rather than
   hitting the real GitHub API.
   OPEN QUESTION for whoever picks this up: does a real device-flow
   login need to be run manually to verify (c), since it can't be
   safely automated in CI without a dedicated test GitHub account?

   DONE (2026-09-09), items (a), (b), (d): (a) `Model.is_github_copilot_native()`
   added, extra_headers default extended to cover `github_copilot/*`
   models regardless of GITHUB_COPILOT_TOKEN, without overwriting a
   user's own explicit extra_headers config -- see
   models.py:1157-1169. (b) aider/website/docs/llms/github.md rewritten:
   native provider is now the documented primary path, old manual
   OPENAI_API_BASE approach kept as a clearly-labeled fallback. (d) 4
   new tests (test_models.py: is_github_copilot_native, headers-by-
   default, explicit-headers-respected, non-copilot-gets-no-headers).
   REAL FINDING while writing tests: instantiating `Model("github_copilot/...")`
   at ALL (not just calling send_completion) triggers a live GitHub
   OAuth device-flow login -- confirmed via TWO separate litellm calls
   inside Model.__init__: `litellm.get_model_info()` (via
   ModelInfoManager) AND `litellm.validate_environment()` (since
   "github_copilot" isn't in fast_validate_environment's keymap, so it
   always falls through to the slow litellm-backed path). A first draft
   of the tests only mocked get_model_info and still hung a real test
   run waiting for live device-code approval -- had to kill the process
   via taskkill. Both calls are now mocked in the test helper
   (_make_github_copilot_model). Item (c) (model-settings.yml entries)
   still NOT done -- deliberately deferred, since verifying whether
   litellm's own metadata already covers common github_copilot/* models
   requires a real device-flow login (can't be checked statically, per
   the finding above), and that's a one-person-with-a-real-GitHub-
   account task, not something to fake or skip verification on.

2. Tool/function-calling support as a general capability (#2672) — 
   likely substantially delivered as a side effect of Phase 6's MCP
   work, since MCP IS a tool-calling protocol; confirm whether a
   separate non-MCP tool-calling surface is still requested once MCP
   ships, or whether this issue is effectively closed by Phase 6.

   CONFIRMED SUBSUMED (2026-09-09): re-read #2672's full body and all
   4 comments. The issue's stated use cases (build/test/deploy
   workflows, GitOps/PR/commit operations, "operational tasks") and
   its explicit final line ("it would be valuable to support standard
   tooling protocols like MCP") are fully addressed by Phase 6's
   AgentCoder. Zero comments since Sept 2025, none asking for a
   separate non-MCP tool-calling surface. One comment (Jan 2025) asked
   for the inverse capability -- aider exposing ITSELF as an MCP
   server, not just consuming MCP servers as a client -- which is a
   different, not-yet-requested-elsewhere feature, not part of this
   item's original scope; noting it here in case it resurfaces as a
   separate future request, but not adding it speculatively.
   ACTION: close #2672 referencing the merged Phase 6 PR (#17 on the
   fork) as resolving it; no code work needed.

3. IDE presence roadmap (VS Code #68, PyCharm #483, Emacs #1913) — per
   SPEC.md §8 non-goals, don't build full extensions; instead document
   a shell-out integration contract (stable CLI flags/exit codes/output
   format that an editor extension could wrap), and note that
   `watch.py`'s existing `AI!`/`AI?` inline-comment triggering
   (confirmed real and working, ARCHITECTURE_REVIEW §9) already gives
   editor-adjacent workflow without a dedicated plugin — publicize this
   existing feature better before assuming a new one is needed.

   CONFIRMED AS-SCOPED (2026-09-09): watch.py's AI!/AI? triggers and
   aider/website/docs/usage/watch.md both verified still present and
   accurate. No re-scoping needed -- this item's original plan holds.
   Lowest priority of the four per SPEC.md's own non-goals; no urgency
   to schedule ahead of the others.

   DONE (2026-09-09): added a "Editor/IDE integration via shell-out"
   section to aider/website/docs/scripting.md documenting the actual
   shell-out contract -- --message/--message-file + --yes-always for
   non-interactive single-shot invocation, and a link to watch.py's
   existing AI!/AI? capability as the no-plugin-needed editor-adjacent
   path. Also documents aider's REAL exit code behavior, checked
   directly against main.py rather than assumed: today it's binary
   only (0 on completion, 1 on any of the many error return paths) --
   there's no differentiated exit code for e.g. "edits rejected" vs.
   "provider error" vs. "malformed response," so an integration
   needing to distinguish those must parse stdout/stderr or use the
   Python scripting API instead of relying on the exit code alone.
   Documenting this honestly (not implying a richer contract exists
   than actually does) rather than inventing new exit codes -- that
   would be a real, larger change with backwards-compat implications
   for any existing script relying on the current binary behavior, and
   wasn't asked for.

4. Reproducible bug fixes: GitPython index-version-3 incompatibility
   (#211) — per ARCHITECTURE_REVIEW §7, this is dependency-level; decide
   between (a) pinning/patching GitPython, (b) shelling out to `git`
   directly for the specific affected operations, before starting.
   ollama_chat timeout handling — audit `validate_environment`/provider-
   specific code paths in models.py for where timeout config is or
   isn't threaded through to the ollama_chat provider.

   RE-SCOPED, split into two sub-items (2026-09-09):

   4a. GitPython index-v3 (#211): ALREADY FIXED, verify-only. Traced
   upstream: GitPython's own issue #1960 ("Git index version 3
   support") was closed as resolved by GitPython PR #2081 (merged
   2025-11-09). Our pinned `gitpython==3.1.46` (requirements.txt) was
   released 2026-01-01 -- AFTER that merge. Confirmed directly against
   our installed dependency's actual source
   (`.venv/Lib/site-packages/git/index/fun.py` line 212):
   `assert version in (1, 2, 3), "Unsupported git index version %i,
   only 1, 2, and 3 are supported" % version`. Index v3 is already
   accepted. REMAINING WORK: write a regression test that creates a
   real git repo with an index-v3-triggering operation (e.g. `git add -N`
   or `feature.manyFiles=true`, per the upstream issue thread) and
   confirms aider's GitRepo wrapper handles it without error, then
   close #211 with that evidence. No dependency bump or code change
   needed -- just proof.

   4b. ollama_chat timeout: RE-VERIFIED, ALREADY WORKS -- original
   BUILD_PLAN wording was based on static code reading (grepping
   litellm's provider-specific ollama files for "timeout" and finding
   zero matches) which turned out to be the wrong place to look --
   ollama_chat completions route through litellm's shared generic
   `llm_http_handler.py`, which does thread timeout through correctly
   (confirmed: dozens of `timeout=timeout` occurrences in that file).
   Reproduced for real (2026-09-09) against a real local ollama
   instance (v0.33.3, real qwen3.5:4b model) through aider's actual
   `Model.send_completion()` code path, both streaming and
   non-streaming: setting an artificially short timeout (1.5s) on a
   real generation request correctly raised
   `litellm.Timeout: Connection timed out after 1.5 seconds` at ~3-5s
   (retry/backoff adds some overhead), not silently ignored.
   Traced to the actual upstream bug this item was about: litellm
   issue #8333 ("[Bug]: ollama_chat/ provider does not honor
   timeout"), filed 2025-01, closed 2025-06-29 as stale/not-a-bug (a
   litellm maintainer clarified it was a debug-logging clarity issue,
   not broken timeout handling) -- our current litellm==1.82.3 (a much
   later version) demonstrably honors it in real testing regardless of
   how that specific issue was resolved.
   ACTION: no code change needed. Retire this item from the backlog;
   note it here as re-verified rather than silently dropping it, in
   case ollama_chat timeout handling regresses in some future litellm
   version and needs re-investigating.

---

## Sequencing summary

Phase 0 (fork+baseline) and Phase 1 (cleanup) are prerequisites for
everything else — don't parallelize past them.

Phase 2 (governance) should start in parallel with Phase 1, since it
has no code dependency on the cleanup work, and having governance
running before Phase 3-7 generates a real PR volume is the whole point.

Phase 3 (triage) can run in parallel with Phase 4/5/6 — different
subsystem, no shared code.

Phase 4 (approval gating) should land before or alongside Phase 6 (MCP),
since Phase 6 explicitly wants to reuse Phase 4's gate for MCP tool
calls (see Phase 6 step 5).

Phase 5 (honest error handling) is small and self-contained — could be
pulled forward earlier if you want a quick, low-risk first real
contribution to point to.

Phase 7 is explicitly lower-priority and partially contingent on Phase
6's outcome (item 2 may be subsumed).

## What "done" looks like for a v1 release

- Fork exists under ForgePair's name, passes its full (expanded) test
  suite, dead code removed, fragile OpenRouter scraping replaced.
- Governance loop proven with at least one non-founder merge + auto-
  release.
- Triage bot redesigned and demonstrated not to silently bury recurring
  issues.
- Approval-gated apply mode shipped and opt-in.
- Honest error handling shipped for at least the rate-limit/silent-
  failure class of bug.
- MCP client support shipped with at least one working real-world MCP
  server integration demo.
- Everything in Phase 1's cleanup list resolved, not deferred.

Explicitly NOT required for v1 (per SPEC.md §8 non-goals): IDE
extensions, Copilot provider, full non-MCP tool-calling surface, GitPython
dependency-level bug fix — these can ship post-v1 as Phase 7 items land.
