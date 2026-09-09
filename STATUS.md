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

- **Only the "tools" primitive is implemented.** MCP also defines
  "resources" (readable data sources) and "prompts" (reusable prompt
  templates); a server that primarily exposes those rather than
  callable tools will connect successfully but expose nothing usable
  today. Scoped follow-up: new slash commands (e.g. `/mcp-resources`,
  `/mcp-prompts`) to list and pull content into chat, since resources
  and prompts aren't callable functions like tools and need their own
  user-facing surface rather than just internal plumbing. (Remote HTTP
  auth, the other half of this gap, is done -- see "What's done".)

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
