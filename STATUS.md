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

- Governance infrastructure (tiered merge rights, CI-gated merge queue,
  continuous release) -- proven with a real non-founder merge + release.
- Issue/request triage redesign -- verified live against this repo.
- Model-metadata fragility fixes (OpenRouter scraping replaced with
  the real API, hardcoded model lists auto-refreshed).
- Approval-gated apply mode (`--confirm-edits`).
- Honest failure handling on provider errors (no more silent 0-token
  responses).
- Native MCP (Model Context Protocol) client support (`--edit-format
  agent`) -- verified with a live demo against a real MCP server and a
  real LLM, not just automated tests.

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

- **Pinned `black` version is outdated** (`23.3.0` in
  `.pre-commit-config.yaml`, incompatible with Python 3.12+). Worked
  around today via a persistent Python 3.11 pre-commit virtualenv (see
  CONTRIBUTING.md). Upgrading the pin properly would reformat a large
  amount of unrelated pre-existing code, so it needs its own isolated,
  reviewed PR rather than being bundled into other work.
- **`requirements/common-constraints.txt` pins `scipy==1.17.1`
  unconditionally**, which conflicts with `requirements/python-compat.in`'s
  Python-version-branched constraint (`scipy<1.16` for Python <3.11).
  This blocks using `uv pip compile --universal` to regenerate
  `requirements.txt` safely -- the current workaround is a
  single-platform compile followed by hand-restoring the affected
  marker branches, which is fragile and has already caused one real CI
  regression that had to be fixed. See
  [issue #18](https://github.com/TVick64889/forgepair/issues/18) for
  full repro steps and a suggested fix.
- Docker Hub publishing is intentionally *not* configured (no Docker
  Hub account exists yet, no current user demand for a pullable
  image). `docker-build-test.yml` runs build-only so CI doesn't depend
  on this. Revisit before any real release.

### MCP (Model Context Protocol) client

- **Only the "tools" primitive is implemented.** MCP also defines
  "resources" (readable data sources) and "prompts" (reusable prompt
  templates); a server that primarily exposes those rather than
  callable tools will connect successfully but expose nothing usable
  today.
- **No authentication support for remote HTTP MCP servers.** Only
  local stdio servers and unauthenticated HTTP servers can be
  connected to -- most real hosted MCP servers require a bearer token
  or API key, which isn't wired up yet.

### GitHub Copilot provider

- litellm's native `github_copilot/` provider (OAuth device-flow
  login, automatic token refresh) is wired up with the headers
  Copilot's API requires, documented, and tested -- but **no
  `model-settings.yml` entries have been added or verified** for
  common `github_copilot/*` models. Checking whether litellm's own
  metadata already covers them requires a real GitHub OAuth
  device-flow login (confirmed: even static model-info lookups
  trigger it), so this can't be verified from a script or in CI
  without a dedicated test GitHub account.

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
