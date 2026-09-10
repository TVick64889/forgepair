# ForgePair — Project Status

ForgePair is a fork of [aider-AI/aider](https://github.com/Aider-AI/aider),
maintained under a different governance model to avoid the single-
maintainer bottleneck that stalled the upstream project (see
[SPEC.md](SPEC.md) for the evidence and reasoning, [BUILD_PLAN.md](BUILD_PLAN.md)
for the phased execution plan, and [ARCHITECTURE_REVIEW.md](ARCHITECTURE_REVIEW.md)
for the codebase deep-dive that informed both).

This file exists so anyone using or contributing to ForgePair -- not
just the people who wrote the plan -- can see current status and known
gaps in one place, without having to read the full planning documents.
Updated as work happens, same policy as [CHANGES.md](CHANGES.md).

## What's done

All of SPEC.md's v1 "what to ship" priorities are complete, tested, and
merged:

- Governance infrastructure: branch protection + required status checks
  (tests across 5 Python versions x 2 OSes, lint, Docker build) verified
  as a real, working hard gate -- confirmed directly by attempting a
  direct push (rejected) and running a real PR through the full flow to
  merge. A live GitHub-native merge queue is configured and verified
  end-to-end (org-owned repo, `main-protection-with-merge-queue`
  ruleset -- PR #40 actually merged through it automatically), and
  continuous release is live: every merge to `main` auto-publishes to
  PyPI via Trusted Publishing (OIDC), no stored token; `forgepair`
  1.0.0+ is live on PyPI. Tiered contributor categories are documented
  in CONTRIBUTING.md. See "Known gaps" below for what's NOT yet true
  about this (no second contributor has ever used the tiered process).
- Issue/request triage redesign -- verified live against this repo.
- Model-metadata fragility fixes (OpenRouter scraping replaced with
  the real API, hardcoded model lists auto-refreshed).
- Approval-gated apply mode (`--confirm-edits`).
- Honest failure handling on provider errors (no more silent 0-token
  responses).
- Native MCP (Model Context Protocol) client support (`--edit-format
  agent`) -- verified with a live demo against a real MCP server and a
  real LLM, not just automated tests. Authentication support for
  remote HTTP MCP servers (bearer token / API key via `.mcp.json`
  `headers`) added and verified against a real server enforcing real
  401s, not mocks.
- Pinned `black` version upgraded (`23.3.0` -> `26.5.1`) and the
  repo-wide reformat applied as its own isolated PR; the old
  Python-3.11-pre-commit-venv workaround note has been pruned from
  CONTRIBUTING.md (no longer needed since the version bump).
- `requirements/common-constraints.txt`'s scipy/numpy version-branch
  conflict (see former issue #18) fixed -- `scripts/pip-compile.sh`
  now compiles with `--universal --python-version 3.10`, resolving the
  full Python 3.10-3.14 support matrix correctly instead of collapsing
  to one interpreter's pins. The old hand-patch splice hack is gone.
- GitHub Copilot model metadata gap resolved -- verified live against
  a real Copilot Free account's `/models` endpoint (not just static
  litellm inspection): added local `model-metadata.json` entries for
  24 models the Copilot API currently serves that litellm doesn't yet
  have pricing/context-window data for.
- Fork identity/branding fixed: `pyproject.toml`'s package name
  (`aider-chat` -> `forgepair`, with a new `forgepair` CLI entry point
  alongside the existing `aider` one so nothing breaks), and the
  crash-reporter/Homepage URLs (were still pointing at upstream
  `Aider-AI/aider`, meaning a real crash report would have been filed
  against the wrong project). Found via a full item-by-item re-audit
  of BUILD_PLAN.md's Phase 0 checklist against the actual repo state,
  not assumed done from STATUS.md's earlier summary.
- Resolved Phase 1's long-deferred `search_replace.py` cleanup item:
  the two unused fuzzy-match strategies (`dmp_apply`,
  `git_cherry_pick_sr_onto_so`) confirmed genuinely dead (no test
  coverage, no live caller, already excluded from the debug/benchmark
  harness's own default list) and removed, along with the now-orphaned
  `map_patches()` helper.
- GitPython index-version-3 incompatibility (#211): confirmed already
  fixed upstream (GitPython PR #2081), and a real regression test
  exists proving it -- `tests/basic/test_sanity_check_repo.py::
  test_real_git_index_version_3_repo_works_without_error` creates an
  actual index-v3 file via a real `git add -N` and exercises aider's
  real `GitRepo` class against it (no mocked GitError). No dependency
  bump or code change was needed, just this proof; noted here since it
  wasn't previously listed in this section despite being done.

See [CHANGES.md](CHANGES.md) for the detailed, dated changelog of all
of the above.

## Known gaps

Nothing below is hidden or silently deferred -- each item was found,
scoped, and intentionally left for later (usually because fixing it
properly needs its own focused PR, or needs a resource -- a real
GitHub account, a production release, etc. -- that isn't available
during routine development). Tracked here so they don't have to be
rediscovered.

### Governance / CI

- ~~No merge queue is actually configured.~~ -- FIXED and VERIFIED
  2026-09-10. The repo transferred to the `forgepair` GitHub
  organization (from the personal `TVick64889` account) specifically to
  unblock this -- GitHub's native merge queue only works for
  organization-owned repos (see the original investigation below).
  `main` has a repository ruleset (`main-protection-with-merge-queue`)
  with a real `merge_queue` rule alongside `required_status_checks`,
  `deletion`, and `non_fast_forward`, replacing the old classic branch
  protection. Confirmed end-to-end, not just configured: PR #40
  (scipy/numpy constraints fix) went green, entered the queue, and
  merged automatically on 2026-09-10 without anyone clicking merge.
  Original investigation (2026-09-09, kept for context): attempting to
  add a `merge_queue` rule to a ruleset on the personal-account repo
  returned `422 Validation Failed` regardless of payload shape;
  `gh api repos/TVick64889/forgepair --jq '.owner.type'` confirmed
  `User`-owned repos can't use this feature, which is what motivated
  the org transfer.
- **No second contributor has ever used the tiered-merge process.**
  Confirmed via the repo's collaborator list (one member). The tiered
  categories are documented in CONTRIBUTING.md but have never actually
  been exercised by anyone but the founder -- so the core claim of this
  governance model (it doesn't bottleneck on one person) has evidence
  for the CI-gate half, but not the "someone else actually merges
  something" half.
- ~~Continuous release is still dry-run.~~ -- FIXED 2026-09-10.
  `continuous-release.yml`'s `DRY_RUN` flipped to `"false"`, and
  publishing is live: the `forgepair` package on PyPI shows a real
  `1.0.0` release (confirmed via `pip index versions forgepair`).
  The actual publish mechanism ended up different from what this gap
  originally assumed: rather than a stored `PYPI_API_TOKEN` secret,
  publishing goes out via `release.yml` using PyPI Trusted Publishing
  (OIDC) -- no long-lived token stored in the repo at all.
  `continuous-release.yml`'s header comments have been updated to match
  (see PR #41, 2026-09-10) -- no longer a doc-drift gap.

Not a gap, but related and worth noting here: Docker Hub publishing is
also not configured by default (no ForgePair-maintained Docker Hub
account exists). This isn't an unfinished engineering task -- it's a
deliberate choice with a fully documented, ready-to-use path for
anyone who wants it. `docker-build-test.yml` already runs build-only
on every PR, so CI validates the Dockerfile without needing any Docker
Hub credentials, and the publish workflow itself is fully built and
just needs a fork maintainer's own credentials to turn on. See "Using
ForgePair via Docker" below for both the build-it-yourself path (works
right now, zero setup) and the exact steps to enable publishing to
your own Docker Hub account.

### MCP (Model Context Protocol) client

- ~~No startup check for orphaned MCP server subprocesses from a
  previous session that died uncleanly (crash, SSH drop, SIGKILL)~~ --
  FIXED. The SwitchCoder cleanup fix above only closes the gap while the
  aider process itself stays alive; this closes the separate gap where
  the whole process dies before any shutdown path runs. Implemented as
  PID tracking, not command-line guessing: `MCPManager` now records the
  PID of every stdio server subprocess it spawns to a per-project JSON
  file (`.aider.mcp-pids.json`, next to the `.mcp.json` it came from;
  covered by `.gitignore`'s `.aider*` pattern), tagged with the
  command/args and the spawning aider process's own PID, and clears its
  own entries on a clean `shutdown()`. `connect_all()` now calls
  `check_for_leftover_processes()` first, which reports (via
  `leftover_processes`) any entry whose PID is still alive AND whose
  live process's command/args still match what was recorded (the
  PID-reuse guard -- a bare "PID exists" check isn't enough, since the
  OS recycles PIDs for unrelated processes over time). `AgentCoder`
  warns about each one found (advising the user to look into it as an
  artifact of a session that didn't shut down cleanly) but does not
  kill it -- warn-by-default, per the agreed runtime policy. The one
  exception: if a server's own fresh connect attempt actually fails
  while a leftover is recorded under that exact server name (evidence
  the leftover -- e.g. holding a single-instance lock or a port -- is
  what's blocking the new one from loading), `MCPManager` re-verifies
  the leftover one more time immediately before acting, kills it, and
  retries that server's connect once; `AgentCoder` reports this case
  louder/differently (terminated automatically, not just advised).
  Verified with real subprocess tests (no mocking of the detection or
  kill logic): a real MCP server process is spawned, the manager is
  discarded without calling `shutdown()` (simulating an unclean
  process death) while the spawned process is left running, and a
  fresh `MCPManager` against the same pid_file correctly detects it;
  separately, a real single-instance-only stdio server fixture proves
  the full kill-if-blocking path end-to-end (leftover holds the lock,
  fresh connect fails, leftover is killed, retry succeeds). Also
  covered: a dead PID (fully exited, not orphaned) is correctly not
  reported, and a PID reused by an unrelated process (guarded by the
  command/args match) is correctly not reported. See
  `tests/basic/test_mcp_manager.py::TestMCPManagerOrphanDetection`
  (6 tests) and `tests/fixtures/mcp_servers/single_instance_server.py`.

- ~~Only the "tools" primitive was implemented~~ -- FIXED. MCP's other
  two primitives, "resources" (readable data sources) and "prompts"
  (reusable prompt templates), are now supported: `MCPManager` discovers
  and fetches both (tolerating servers that only implement tools -- not
  a connection error), and two new slash commands, `/mcp-resources` and
  `/mcp-prompts`, list and pull content into chat (list with no
  argument; fetch/run by URI or name + `key=value` args). Verified with
  a real MCP server subprocess exposing all three primitives, not mocks
  -- see tests/basic/test_mcp_manager.py and tests/basic/test_mcp_commands.py.
  (Remote HTTP auth was already done -- see "What's done".)

- ~~MCPManager subprocess cleanup relied on `__del__`, not an explicit
  shutdown call, when the user switches coders mid-session~~ -- FIXED.
  Found while investigating an unrelated test flake (see below). aider's
  `SwitchCoder` handling in `main.py`'s persistent interactive loop
  (~line 1178, used by `/model`, `/chat-mode`, `/architect`, etc.) did
  `coder = Coder.create(**kwargs)` to replace the running coder without
  ever explicitly calling `old_coder.mcp_manager.shutdown()` first --
  cleanup of the old `AgentCoder`'s background event-loop thread and
  connected MCP server subprocess(es) depended entirely on Python's
  garbage collector eventually invoking `AgentCoder.__del__()`. In
  practice CPython's refcounting usually collected it right away
  (confirmed: a manual repro of create-agent-coder -> switch-away ->
  `gc.collect()` showed no leaked subprocess), but relying on `__del__`
  was inherently non-deterministic -- a user switching in and out of
  agent mode several times in one session, combined with any reference
  cycle delaying GC, could have accumulated orphaned MCP server
  subprocesses/threads until the whole aider process exited. Fixed by
  having the `SwitchCoder` except-branch call
  `getattr(coder, "mcp_manager", None)` and `.shutdown()` it explicitly
  before replacing `coder`, mirroring what `AgentCoder.__del__` already
  did, so cleanup no longer waits on GC timing. `shutdown()` is
  idempotent and a no-op for non-agent coders. Verified with real
  targeted tests driving the actual `SwitchCoder` except-branch in
  `main()` (not mocking the branch itself): confirms `mcp_manager.
  shutdown()` fires exactly once, before the replacement coder is
  created, and confirms coders without an `mcp_manager` attribute at
  all don't crash the handler -- see
  `tests/basic/test_main.py::TestMain::test_switch_coder_shuts_down_outgoing_mcp_manager`
  and `::test_switch_coder_without_mcp_manager_does_not_error`.

- Unrelated to the above: a Windows-only test flake was observed when
  running many MCP-subprocess-heavy test files back-to-back in one
  `unittest` process (tests/basic/test_mcp_manager.py +
  test_mcp_commands.py + test_agent_coder.py + test_mcp_config.py
  together) -- `test_agent_coder.py`'s `tearDown()` occasionally hits a
  `PermissionError` deleting its tempdir. Investigated and ruled out as
  a real product bug: the test's actual assertions always pass; the
  isolated repro of the exact same scenario (multiple tool calls,
  explicit `mcp_manager.shutdown()`, then delete the tempdir) succeeds
  cleanly every time. Looks like Windows-specific resource/handle
  pressure from spawning ~15+ subprocesses within 40 seconds in one
  test run, not a cleanup bug in aider's own code.
  ~~FOLLOW-UP: not started~~ -- FIXED. `test_agent_coder.py` was using a
  raw `tempfile.TemporaryDirectory()` directly, when aider already has
  a purpose-built `aider.utils.IgnorantTemporaryDirectory` for exactly
  this (Windows PermissionError/RecursionError-tolerant cleanup, using
  `ignore_cleanup_errors=True` on Python 3.10+, already used
  everywhere else in the test suite via `ChdirTemporaryDirectory`/
  `GitTemporaryDirectory`) -- this test just wasn't using it. Switched
  `setUp()` to `IgnorantTemporaryDirectory()`. Verified: 3 back-to-back
  runs of the exact same heavy file combination that originally
  surfaced the flake, all clean (58/58 tests passing each time).

### Contributor workflow / tooling

- ~~No local pre-flight step catches pre-commit failures before a
  push/PR~~ -- PARTIALLY FIXED. Surfaced directly this session: PR #32
  needed three separate push-and-wait CI round-trips to go green, all
  for formatting/lint drift that local `pre-commit` (or `black`/
  `isort`/`flake8` run with the repo's actual configured flags) would
  have caught in seconds -- (1) `black` was run locally without
  `--line-length 100 --preview` (the flags actually pinned in
  `.pre-commit-config.yaml`), producing different output than CI's
  hook wanted; (2) a `flake8` E731 (lambda assignment) and an isort
  ordering issue in files from an earlier commit in the same PR had
  never been locally linted before that push. CONTRIBUTING.md already
  documented `pre-commit install` and `pre-commit run --all-files` --
  the gap was that this session's actual working environment never had
  the hook installed, not a documentation gap. Ran `pre-commit install`
  in this environment and verified it actually fires and blocks a bad
  commit: a deliberately malformed scratch file (unused imports,
  wrong formatting) was correctly caught and blocked by isort/black/
  flake8 in sequence before the commit completed. NOT FULLY CLOSED:
  this only fixes the local dev environment used this session --
  there's still no CI-independent enforcement (e.g. a documented
  onboarding step, or a repo-level reminder) that guarantees every
  future contributor/agent working on this repo actually runs
  `pre-commit install` before their first commit, so the same CI
  round-trip cost could still recur for someone else.

### Documentation drift

- ~~CONTRIBUTING.md's black/pre-commit workaround section was stale~~ --
  FIXED. Removed the section instructing contributors to run pre-commit
  from a separate Python 3.10/3.11 `.venv-precommit` to work around
  `black==23.3.0`'s incompatibility with Python 3.12+ (`ast.Str`
  removal). Verified `black==26.5.1` (the version actually pinned in
  `.pre-commit-config.yaml`) imports cleanly on this machine's Python
  3.14.6 -- the underlying incompatibility no longer applies, so the
  workaround is gone, not just marked obsolete.

### GitHub Copilot provider (Phase 7 item 1)

- ~~model-settings.yml entries for common `github_copilot/*` models
  (item (c) of the Phase 7 Copilot work) were still not done~~ --
  PARTIALLY FIXED. Re-verified live 2026-09-09 that the cached Copilot
  device-flow token was NOT stale (still valid, ~18h remaining) and
  confirmed it works end-to-end (`litellm.completion(model=
  "github_copilot/gpt-4o", ...)` returned a real response). Probed the
  live `/models` endpoint directly (not litellm's static list): 54 real
  models currently served, of which litellm's own cost-map already
  covers 19 -- the other 35 had zero `model-settings.yml` entries,
  meaning `aider.models.Model` fell back to the generic default
  (`edit_format: whole`, `use_repo_map: false`) for all of them, a real
  functional degradation (worst/most token-expensive edit mode, no
  codebase context) not just a cosmetic gap. Added 13 entries for the
  models with an obvious underlying-family match already present in
  this file (claude-sonnet-5/opus-4.7/4.8/4.8-fast/5 matched against
  the existing claude-sonnet-4-6/opus-4-7 templates; gemini-3.5/3.6/
  3.7/3.8-flash matched against gemini-3-flash-preview;
  gpt-5.4/5.4-mini/5.5 matched against the existing gpt-5.4/5.5
  entries; gpt-4-0125-preview matched against its own non-Copilot
  entry), each mirroring that family's existing settings rather than
  inventing new ones. Verified: `aider.models.Model(...)` for each new
  entry resolves the intended `edit_format`/`use_repo_map`/
  `weak_model_name` (confirmed directly, not just YAML-parse-checked),
  and untouched models (e.g. `github_copilot/kimi-k3`) still correctly
  fall back to the old default -- no regression. `tests/basic/
  test_models.py` + `test_model_info_manager.py` (32 tests) pass.
  NOT fully closed: the remaining 22 models (`claude-fable-*`,
  `mai-code-*` variants beyond the one with an existing
  model-metadata.json entry, `copilot-search-*`, `exec-agent-*`,
  `trajectory-compaction`, internal `*-free-auto` pipeline variants)
  have no clear family match in this file to template from --
  guessing settings for them would be worse than leaving them on the
  generic default. Also: could not live-verify a full completion
  round-trip for every new entry, since this account's
  `free_limited_copilot` SKU plan doesn't have access to every listed
  model (confirmed: `github_copilot/gpt-5.4` and
  `github_copilot/claude-sonnet-5` both returned a real, live "model
  not supported" 400 from Copilot's own API for this account/plan,
  not a config or code error -- `github_copilot/gpt-4o`, which has no
  new entry from this pass, works live on this same account). The
  settings themselves were verified via aider's own config-resolution
  path, just not an end-to-end completion call for models this
  account's plan can't reach.

### Model release/staleness handling (general, not just Copilot)

- **No systematic, cross-provider process for catching new or stale
  model entries as providers ship them.** The Copilot investigation
  above (35 of 54 live models missing a `model-settings.yml` entry)
  surfaced this as a pattern, not a one-off: `model-list-freshness.yml`
  already auto-refreshes `model-metadata.json` on a schedule (see
  "What's done"), but that only covers pricing/context-window
  metadata pulled from litellm's own feed -- it does nothing for
  `model-settings.yml` (edit_format/use_repo_map/weak_model_name/etc,
  which litellm has no opinion on and aider must hand-curate per
  model), and nothing for any *other* provider's model list drifting
  out from under aider the same way Copilot's did. NOT INVESTIGATED
  YET: what a good mechanical fix looks like here -- e.g. a scheduled
  job that diffs each configured provider's live model list against
  `model-settings.yml`/`model-metadata.json` and opens an issue (or a
  PR with template-matched settings, same approach used for the 13
  Copilot entries above) for anything new or missing, plus a way to
  flag entries for models a provider has quietly stopped serving
  (stale in the other direction). Tracked here as a follow-up
  investigation, not scoped or started.

### Phase 1 cleanup

- ~~`gui.py` liveness was never runtime-verified~~ -- this STATUS.md
  entry was itself stale/wrong. ARCHITECTURE_REVIEW.md §11.6 already
  documents a real verification done 2026-09-08, during Phase 1:
  `pip install -r requirements/requirements-browser.txt` installed
  cleanly, `aider --gui` (headless) launched a real Streamlit server,
  `curl http://localhost:8501/` returned 200 with real HTML, and
  `curl http://localhost:8501/_stcore/health` returned "ok" --
  confirming `gui.py`'s own script executed (not just the Streamlit
  shell). Caught during a 2026-09-09 spec-vs-status re-scan: this file
  and ARCHITECTURE_REVIEW.md had drifted out of sync with each other on
  the same fact. Corrected here; no new work needed. Still true (from
  ARCHITECTURE_REVIEW.md): no `test_gui.py`, not covered by CI, so
  re-verify manually after any change touching `Coder.create()`,
  `InputOutput`, or gui.py itself.

### Low-priority tracked items (not started)

- **`scripts/issues.py`'s `update_known_issues_dashboard()` body-text
  generation is not yet extracted into a standalone pure function**
  (e.g. `build_dashboard_body(...) -> str`). Currently inline inside
  the function that also makes the GitHub API calls, so it can only be
  verified by running the whole thing against the real repo (already
  done once, see BUILD_PLAN.md Phase 3) rather than a fast local unit
  test. Tracked in BUILD_PLAN.md as explicitly deferred, low priority.

### Not started (explicitly lower priority, not required for v1)

Per SPEC.md's own non-goals:

- Full IDE extensions (VS Code, PyCharm, Emacs) -- a documented
  shell-out integration contract exists instead (see
  [scripting docs](aider/website/docs/scripting.md)), plus the
  existing `AI!`/`AI?` inline-comment watch mode.
- A general non-MCP tool-calling surface -- confirmed subsumed by the
  MCP work; the original request
  ([upstream #2672](https://github.com/Aider-AI/aider/issues/2672))
  has been noted as resolved by this fork.

## Where to look for more detail

- [BUILD_PLAN.md](BUILD_PLAN.md) -- the full phase-by-phase plan, with
  dated STATUS notes on every item (including the ones summarized
  above) as they were investigated, scoped, and closed out.
- [CHANGES.md](CHANGES.md) -- user-facing changelog, one entry per
  completed phase.
- [ARCHITECTURE_REVIEW.md](ARCHITECTURE_REVIEW.md) -- the original
  codebase deep-dive that the fork-vs-rebuild decision and much of the
  phase sequencing was based on.

## Using ForgePair via Docker

ForgePair doesn't publish a pullable image to Docker Hub itself (see
"Docker Hub publishing" under Known gaps above), but the Dockerfile is
validated on every PR, so building it yourself works today with zero
setup on the maintainers' end.

### Build it yourself (works right now)

```
git clone https://github.com/forgepair/forgepair
cd forgepair
docker build -t forgepair -f docker/Dockerfile --target aider .
docker run -it --rm -v "$(pwd):/app" forgepair
```

Two build targets exist (`--target aider` or `--target aider-full`,
matching `docker-build-test.yml`'s CI matrix) -- `aider-full` includes
extra optional dependencies (e.g. the `help`/browser extras) that
`aider` doesn't, at the cost of a larger image.

### Publishing to your own Docker Hub (for a fork maintainer)

If you maintain a fork and want a pullable image for your users, the
publish workflow already exists and just needs your own credentials:

1. Create a Docker Hub account (free tier is fine) and a repository to
   push to.
2. In your fork's GitHub repo settings, add two secrets:
   `DOCKERHUB_USERNAME` and `DOCKERHUB_PASSWORD` (a
   [Docker Hub access token](https://docs.docker.com/security/for-developers/access-tokens/),
   not your account password, is recommended).
3. `.github/workflows/docker-release.yml` triggers on any `vX.Y.Z` tag
   push and builds+pushes both targets, multi-arch (amd64+arm64), to
   `${DOCKERHUB_USERNAME}/aider` and `${DOCKERHUB_USERNAME}/aider-full`.
   Note: this repo's own `continuous-release.yml` is live (not dry-run)
   and already auto-tags `vX.Y.Z` on every merge to `main` -- so on a
   real fork with these secrets set, `docker-release.yml` will fire
   automatically on the next merge with no extra tagging step needed.
4. Alternatively, trigger `docker-release.yml` manually any time via
   `workflow_dispatch` (the "Run workflow" button in the Actions tab)
   without needing a tag push at all.

This is entirely opt-in and per-fork -- nothing above affects anyone
who just wants to build and run locally.
