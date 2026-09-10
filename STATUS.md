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
  merge. Continuous-release automation exists and correctly computes
  next-version on every merge, but is intentionally still in dry-run
  mode (no PyPI token configured yet). Tiered contributor categories are
  documented in CONTRIBUTING.md. See "Known gaps" below for what's NOT
  yet true about this (no merge queue configured, no second contributor
  has ever used the tiered process, release automation not live) --
  this was previously overstated here as fully proven; corrected after
  a direct re-audit against BUILD_PLAN.md's own item-level exit criteria.
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
  Python-3.11-pre-commit-venv workaround is no longer needed for
  compatibility (CONTRIBUTING.md's note on it can be pruned in a
  follow-up doc pass).
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

- **No merge queue is actually configured.** Confirmed directly via
  GitHub's API (`mergeQueue: null`). Branch protection/required checks
  are real and enforced, but every merge to date has been the repo
  owner clicking merge directly, not a queue processing an approved,
  green PR automatically.
- **No second contributor has ever used the tiered-merge process.**
  Confirmed via the repo's collaborator list (one member). The tiered
  categories are documented in CONTRIBUTING.md but have never actually
  been exercised by anyone but the founder -- so the core claim of this
  governance model (it doesn't bottleneck on one person) has evidence
  for the CI-gate half, but not the "someone else actually merges
  something" half.
- **Continuous release is still dry-run.** `continuous-release.yml`
  correctly computes what the next version would be on every merge,
  but `DRY_RUN: "true"` and no `PYPI_API_TOKEN` secret means nothing
  has ever actually auto-published. This is intentional (no real
  package to publish yet, per the workflow's own comments) but is a
  real gap against BUILD_PLAN.md Phase 2's stated exit criteria ("a
  release auto-publishes from that merge"), which has not been met.
- **Docker Hub publishing is intentionally not configured by default**
  (no ForgePair-maintained Docker Hub account exists, no
  current user demand for a pullable image maintained by this
  project). `docker-build-test.yml` runs build-only on every PR so CI
  validates the Dockerfile without needing any Docker Hub credentials.
  Anyone can still use ForgePair via Docker today without waiting on
  this -- see "Using ForgePair via Docker" below for both the
  build-it-yourself path (works right now, zero setup) and how a fork
  maintainer can turn on publishing to their own Docker Hub if they
  want a pullable image.

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
  test run, not a cleanup bug in aider's own code. Not fixed (it's a
  test-suite-only symptom); flagging so it isn't mistaken for a MCP
  cleanup regression if seen again in CI.

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

- **model-settings.yml entries for common `github_copilot/*` models
  (item (c) of the Phase 7 Copilot work) are still not done.** Verified
  directly: zero `github_copilot` matches in
  `aider/resources/model-settings.yml` (separate from
  `model-metadata.json`, which does have 49 Copilot entries already --
  that's items (a)/(d), already shipped). Confirming whether litellm's
  own metadata already covers these models requires a real GitHub
  Copilot device-flow login, which can't be safely automated/verified
  statically or in CI -- needs a human with a real account to run it.

### Phase 1 cleanup

- **`gui.py` liveness was never runtime-verified.** BUILD_PLAN.md Phase
  1 item 7 called for actually launching `aider/gui.py` against a
  scratch repo and explicitly deciding carry-forward/fix/drop for v1.
  No record in STATUS.md, CHANGES.md, or BUILD_PLAN.md of this having
  been done -- the file exists but its status is still technically
  unresolved, which BUILD_PLAN.md's own Phase 1 exit criteria requires
  before that phase can be considered fully closed.

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
git clone https://github.com/TVick64889/forgepair
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
   Note: this repo's own `continuous-release.yml` is currently in
   dry-run mode and doesn't push version tags yet (see BUILD_PLAN.md
   Phase 2 item 4) -- if you want tag-triggered publishing to actually
   fire, you'll need your own tagging process (e.g. push a `v1.0.0` tag
   by hand, or flip your fork's release workflow live) until that
   changes upstream.
4. Alternatively, trigger `docker-release.yml` manually any time via
   `workflow_dispatch` (the "Run workflow" button in the Actions tab)
   without needing a tag push at all.

This is entirely opt-in and per-fork -- nothing above affects anyone
who just wants to build and run locally.
