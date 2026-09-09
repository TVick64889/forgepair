# Aider Codebase Deconstruction

Status: complete architectural review
Date: 2026-09-08
Source: github.com/Aider-AI/aider, cloned locally to
C:\Users\tlvic\hermes-work\aider-src (shallow clone, main branch,
commit 5dc9490, 2026-05-22)

Method: full structural AST map of all 78 source files (see
C:\Users\tlvic\hermes-work\aider_structural_map.txt), plus deep manual
reads of the ~10 architecturally load-bearing files. Test suite: 36
files, 12,264 lines (test:code ratio ~0.60 — a real, substantial test
suite, not token coverage).

## 1. High-level shape

~20,285 lines of Python across 78 files (excludes docs website, tree-sitter
query grammars). Roughly:

- Core chat/edit loop: base_coder.py (2,485 lines) — the single largest
  file and the true center of gravity of the whole program.
- ~15 "Coder" subclasses, one per edit-format strategy (how the LLM's
  response gets turned into file changes).
- CLI/terminal I/O layer: io.py (1,191 lines), commands.py (1,712 lines,
  the `/slash-command` implementations).
- Bootstrapping/config: main.py (1,274 lines), args.py (945 lines).
- Model abstraction: models.py (1,338 lines) — talks to litellm, resolves
  which model/provider/settings to use.
- Git integration: repo.py (622 lines).
- Codebase-context system: repomap.py (867 lines) — tree-sitter-based
  repo map generation, the "map your codebase" feature.
- A parallel, optional Streamlit-based GUI: gui.py (545 lines) — appears
  secondary/experimental relative to the terminal CLI.
- Support modules: linter.py, scrape.py (web page → markdown), voice.py
  (speech-to-text input), watch.py (file-change watching for inline
  AI-comment triggers), analytics.py (opt-in telemetry via PostHog/Mixpanel),
  report.py (crash reporter, previously reviewed).

Dependency footprint (requirements.txt) is heavy: litellm (the core LLM
abstraction, pulls in openai SDK, tiktoken, jsonschema, pydantic, fastapi/
starlette as transitive deps), gitpython, tree-sitter + tree-sitter-
language-pack (parsers for dozens of languages), playwright/pypandoc/
beautifulsoup4 (web scraping), sounddevice/soundfile/pydub (voice),
prompt_toolkit + rich (terminal UI), posthog + mixpanel (analytics).
This is not a small dependency surface — a rebuild or fork inherits (or
must re-solve) all of this.

## 2. The core architecture: the Coder class hierarchy

This is the single most important thing to understand before deciding
fork vs. rebuild.

`aider/coders/base_coder.py` defines `class Coder`, an 85-method god-object
that owns the entire lifecycle of one chat "mode":
- Holds state: which files are in the chat (`abs_fnames`), which are
  read-only, conversation history (`done_messages`/`cur_messages`), the
  active model, the git repo handle, the repo-map instance, cost/token
  counters, reflection counters.
- Drives the loop: `run()` → `get_input()` → `run_one()` →
  `send_message()` → (LLM streams back a response) → `apply_updates()`
  → `auto_commit()`.
- `Coder.create(...)` (classmethod, lines 124-201) is a factory: it
  looks up `coders.__all__` for a subclass whose `edit_format` class
  attribute matches the requested format string, and instantiates that
  subclass. This is how aider switches between "diff" mode, "whole file"
  mode, "udiff" mode, "architect" mode, etc. — they're literally
  different Coder subclasses, selected by string match on `edit_format`.
- When switching format mid-session (e.g. user runs `/chat-mode`), it
  carries forward files, history (auto-summarizing if needed to avoid
  confusing the new format's LLM with old-format assistant messages),
  cost totals, and the file watcher — via `clone()`, which just calls
  `Coder.create(from_coder=self, ...)`.

Each subclass only needs to implement three methods to plug into the
whole machine: `get_edits()` (parse the LLM's raw response into a list
of proposed edits), `apply_edits(edits)` (write them to disk), and
optionally `apply_edits_dry_run(edits)` (validate without writing —
used before the real apply pass). Everything else — the chat loop, git
commits, cost tracking, confirmation prompts, shell-command handling,
URL detection, lint/test integration — is inherited from `Coder` and
shared identically across all edit formats.

**This is the key finding for the fork-vs-rebuild decision**: the
edit-format subclass mechanism is a clean strategy pattern. Adding a new
mode (e.g. an MCP-tool-driven mode, or a stricter approval-gated mode)
is architecturally the same shape as every existing mode — subclass
`Coder`, implement `get_edits`/`apply_edits`, register it in
`coders/__init__.py`'s `__all__`. This is NOT a rigid or hostile
architecture to extend.

### The edit-format subclasses (what already exists)

- `EditBlockCoder` (`edit_format = "diff"`) — SEARCH/REPLACE block format.
  The default/flagship format. Uses fuzzy multi-strategy text matching
  (`editblock_coder.py`, `search_replace.py`, 757 lines) to locate the
  SEARCH block in the file even if the LLM's transcription isn't
  byte-perfect: tries perfect match, then whitespace-tolerant match,
  then handles `...` elision markers, then (dead code path, see below)
  edit-distance fuzzy match.
- `UnifiedDiffCoder` (`udiff_coder.py`, 429 lines) + `UnifiedDiffSimpleCoder`
  — classic unified-diff (`---`/`+++`/`@@`) format.
- `WholeFileCoder` — LLM re-emits the entire file content; simplest,
  most token-expensive, used as a fallback for weaker models.
- `PatchCoder` (`patch_coder.py`, 706 lines) — a structured, dataclass-based
  patch format (`ActionType.ADD/DELETE/UPDATE`, `Chunk`, `PatchAction`,
  `Patch`) with a three-tier fuzzy context-matching algorithm
  (`find_context_core`: exact match → rstrip-tolerant → strip-tolerant,
  with an escalating "fuzz level" 0/1/100 recorded per match). Comment
  in the source says this was "adapted from apply_patch.py" — looks
  derived from OpenAI's or a similar external patch format.
- `ArchitectCoder` (48 lines, subclasses `AskCoder`) — implements aider's
  two-model "architect" workflow: one model proposes a plan/discussion
  (no file edits), a second "editor" model turns that into actual edits.
  This is the closest existing analog to a "plan then execute" agentic
  loop.
- `AskCoder` — read-only Q&A mode, no edits at all.
- `ContextCoder` — a mode focused on gathering/identifying relevant file
  context.
- `HelpCoder` — powers the `/help` command, searches aider's own docs.
- `*_func_coder.py` variants (EditBlockFunctionCoder, WholeFileFunctionCoder,
  SingleWholeFileFunctionCoder) — older function-calling-based variants,
  likely predating widespread native tool-call support in providers;
  possible legacy/deprecated path worth checking for removal.
- `Editor*Coder` variants (EditorEditBlockCoder, EditorWholeFileCoder,
  EditorDiffFencedCoder) — thin subclasses used specifically as the
  "editor model" role inside architect mode.
- `*_fenced_coder.py` variants — format variants using fenced code
  blocks instead of the base delimiter style, presumably for models
  that respond better to that convention.

Net: aider already solved "many different LLM output conventions, one
consistent internal edit-application pipeline" — this is real, tested
(12k+ lines of tests), multi-year-refined work. This reinforces the
fork recommendation: reproducing just the EditBlockCoder fuzzy-matching
logic and PatchCoder's context-matching alone would be a substantial
rebuild effort for zero product differentiation.

## 3. The chat loop, step by step

1. `main.py:main()` parses args/config (args.py, cascading CLI flags →
   env vars → `.aider.conf.yml` → `.env`), sets up `InputOutput`,
   `GitRepo`, `Analytics`, resolves the model via `models.Model(...)`,
   builds the initial `Coder` via `Coder.create(...)`, then calls
   `coder.run()`.
2. `Coder.run()` (base_coder.py:876) loops: `get_input()` (prompt_toolkit-
   based prompt with autocomplete, file mentions, slash commands) →
   `run_one(user_message, preproc)`.
3. `run_one` → `preproc_user_input`: if the input is a slash command
   (`/add`, `/commit`, etc.), dispatch to `Commands.run()` and return —
   commands.py owns ~74 methods, one per `/command`. Otherwise, scan for
   file mentions and URLs (each offered via `confirm_ask` to add to
   chat), then hand off to `send_message()`.
4. `send_message` → `send()` (line 1783): builds the full message list
   (system prompt + repo map + file contents + chat history + new
   message), calls litellm's completion API (streaming), accumulates
   `partial_response_content` and — if the model used tool/function
   calling — `partial_response_function_call`, from streamed chunks.
5. After the response completes: `apply_updates()` (line 2296) is the
   central choke point — calls the active Coder subclass's `get_edits()`
   to parse, `apply_edits_dry_run()` to validate, `prepare_to_edit()` to
   gate each file through `allowed_to_edit()` (confirm-ask prompts for
   "create new file?" / "allow edit to file not in chat?"), then the
   real `apply_edits()` to write to disk.
6. `auto_commit()` runs after successful edits if git auto-commit is
   enabled (default): stages changed files, generates a commit message
   (via a "weak model" — a cheaper/faster model used for auxiliary tasks
   like commit messages and chat summarization), commits.
7. If `get_edits()` raises `ValueError` (malformed edit format) or the
   LLM's edits fail to apply (`SEARCH/REPLACE blocks failed to match`),
   the error text is fed back to the LLM as a "reflection" — the loop
   retries automatically, capped at `max_reflections = 3` (line 101).
   This self-correction loop is a real, working retry mechanism already
   in place — not something a rebuild would need to invent from scratch.
8. Lint/test integration: after edits, if `--auto-lint`/`--auto-test`
   are enabled, `Linter` runs and on failure prompts "Attempt to fix
   lint/test errors?" — another reflection-triggering confirm_ask.

## 4. Confirmation/approval touchpoints (relevant to the approval-gating feature ask)

Every user-facing "are you sure" moment in the codebase funnels through
one method: `io.confirm_ask(question, subject=None, group=None,
allow_never=True, explicit_yes_required=...)`. Confirmed usages found:
- Add URL to chat (line 976)
- Create new file (line 2207)
- Allow edit to file not yet added to chat (line 2226)
- Attempt to fix lint errors (line 1604) / test errors (line 1620)
- Run shell command(s) suggested by the LLM (line 2456, uses
  `explicit_yes_required=True` — a stricter variant that doesn't accept
  a bare Enter as yes)
- Add command output to chat (line 2479)
- Add file mentioned in LLM response to chat (line 1772)

**What's missing, confirmed by reading `apply_updates()` directly**: there
is no `confirm_ask` call wrapping the actual edit-write step itself
(`self.apply_edits(edits)`, line 2304). Individual file-level "can I even
touch this file" gates exist (via `allowed_to_edit`), but once a file is
allowed, all edits to it within that turn are applied without a
per-change or per-diff confirmation. This confirms the earlier
assessment: implementing issue #649 ("confirm each change before
applying") is a matter of adding one more `confirm_ask` call at this
exact choke point, following the exact idiom already used seven other
places in the same file — not new architecture.

## 5. Tool-calling / function-calling plumbing (relevant to MCP feature ask)

`Coder.send()` accepts a `functions` parameter (line 1783: `def
send(self, messages, model=None, functions=None)`). Response handling
(lines 1849-1918) reads `completion.choices[0].message.tool_calls`,
extracts `.function` from the first tool call, and accumulates
streamed function-call argument fragments into
`self.partial_response_function_call` across chunks (handles the
case where a provider streams the JSON arguments token-by-token).
`parse_partial_args()` (line 2338) then attempts to JSON-decode the
accumulated arguments, with several fallback repair attempts for
truncated JSON (e.g. appending `]}`, `}]}`, `"}]}` if the raw decode
fails) — defensive handling of a real, previously-encountered failure
mode (models emitting incomplete tool-call JSON when cut off).

This plumbing currently appears to serve the `*_func_coder.py` variants
(EditBlockFunctionCoder etc.) — i.e. it's used for aider's *own*
structured-edit format, not for exposing arbitrary external tools to
the model. But the low-level mechanics (accepting `functions`, parsing
streamed tool-call deltas, repairing partial JSON) are exactly what an
MCP client integration would need to reuse: MCP's job is essentially
"declare a dynamic set of tools to the model and route tool_calls to
the right handler," and the message-send/response-parse plumbing for
that already exists here. The new work for MCP support would be: (a) an
MCP client to discover/connect to servers and enumerate their tools,
(b) translating MCP tool schemas into the `functions` param format,
(c) routing a resolved tool_call to the MCP server instead of to
`apply_edits`, (d) feeding the tool result back into the message loop.
None of that fights the existing design; it's an additive path
alongside the current edit-format-focused usage of the same plumbing.

## 6. Model abstraction layer (models.py, 1,338 lines)

Previously reviewed in depth (see chat history above); summary for
completeness:
- `Model` class (27 methods) wraps a model name string, resolves
  settings by matching against `MODEL_SETTINGS` (loaded from
  `aider/resources/model-settings.yml`, 3,128 lines of YAML — one entry
  per known model/model-family, controlling `edit_format`,
  `weak_model_name`, `use_repo_map`, caching behavior, reasoning-tag
  handling, etc.).
- `ModelInfoManager` fetches pricing/context-window/capability metadata
  at runtime from litellm's hosted JSON (24h local cache in
  `~/.aider/caches/`), with an `OpenRouterModelManager` for
  OpenRouter-specific models, falling back to HTML-scraping the
  OpenRouter model page if the API/cache misses (the fragile point
  identified earlier).
- `fast_validate_environment()` / `validate_environment()`: resolves
  which API key env var a given model needs — fast path via small
  hardcoded `OPENAI_MODELS`/`ANTHROPIC_MODELS` lists (cosmetic only, per
  earlier finding), full path via `litellm.validate_environment()` and
  provider-prefix pattern matching (`bedrock/`, `vertex_ai/`, etc.).
- `sanity_check_models()`/`sanity_check_model()`: called after model
  selection to warn about missing env vars, unknown context window
  (falls back to defaults), and unknown models (offers fuzzy-matched
  suggestions via `fuzzy_match_models()`).

## 7. Git integration (repo.py, 622 lines)

`GitRepo` wraps GitPython. Notable:
- Constructor resolves the actual git root by walking up from every
  file/dir passed in, raises `FileNotFoundError` if files span multiple
  repos.
- Uses `git.GitDB` as the object database backend explicitly, citing a
  linked GitPython issue (#427) in a comment — a known historical
  workaround, not obviously related to the index-version-3
  incompatibility bug (#211) found in the issue-content review; that bug
  likely lives deeper in GitPython's index-parsing itself, which aider
  doesn't control directly — a fork inherits this as an open dependency-
  level bug, not something fixable purely in aider's own code without
  either patching/pinning GitPython or moving off it (e.g. to shelling
  out to `git` directly for the affected operations).
- `commit()` has a detailed attribution system: separately controls git
  "Author" vs. "Committer" fields, and whether aider-generated commits
  get attributed differently from user-driven commits, plus an optional
  "Co-authored-by" trailer — this is a surprisingly well-thought-out
  piece of design (many tools get commit attribution as an afterthought).

## 8. Repo-map (repomap.py, 867 lines)

Tree-sitter-based codebase overview generation:
- Parses source files into an AST for each tag (`Tag` namedtuple:
  rel_fname, fname, line, name, kind), caching parsed tags in a SQLite-
  backed `diskcache.Cache` (`.aider.tags.cache.v{N}`, cache version
  bumped when the tag schema changes — currently v3, or v4 if the newer
  `tree-sitter-language-pack` is in use, i.e. there are two different
  underlying tree-sitter binding paths supported simultaneously,
  another example of accumulated compatibility-shim complexity).
- `get_ranked_tags_map`: builds a relevance-ranked view of the repo
  given which files are in chat, which files/identifiers were
  mentioned — this is presumably a PageRank-style graph ranking (not
  fully read in this pass, worth a deeper look before build time) that
  decides what to include in the token-budget-constrained repo map.
- Token budget estimation (`token_count`) samples every Nth line rather
  than tokenizing the whole file when the file is large — a reasonable
  performance shortcut, but means the estimate is approximate, not
  exact.

## 9. Support systems (lighter review)

- `io.py` (1,191 lines): terminal I/O, built on `prompt_toolkit` +
  `rich`. Owns `AutoCompleter` (tab-completion for file names, `/commands`,
  code identifiers scraped via pygments lexers), color/style config,
  `confirm_ask` (the central approval-prompt primitive), markdown
  streaming output.
- `commands.py` (1,712 lines): ~74 `/slash-command` methods on the
  `Commands` class — file management (`/add`, `/drop`, `/read-only`),
  git (`/commit`, `/diff`, `/undo`), model switching (`/model`,
  `/editor-model`, `/weak-model`), chat-mode switching (raises
  `SwitchCoder`, an exception used as control flow to signal the outer
  loop to rebuild the Coder with a new edit_format — a slightly unusual
  but workable pattern), web scraping (`/web`), voice (`/voice`), and
  more.
- `linter.py` (304 lines): supports built-in Python compile-check plus
  shelling out to external linters (flake8 default for Python,
  configurable per-language), plus a "basic_lint" tree-sitter-based
  fallback for languages without a configured linter.
- `scrape.py` (284 lines): fetches a URL, converts to markdown — tries
  Playwright first (real browser rendering, handles JS-heavy pages),
  falls back to plain httpx + pandoc/beautifulsoup if Playwright isn't
  installed.
- `watch.py` (318 lines): filesystem watcher that looks for inline
  `AI!`/`AI?` comments in edited files (a documented aider convention
  for triggering aider from inside your editor without switching to the
  terminal) — a real, working "IDE-adjacent" feature already present,
  worth knowing about before assuming IDE integration means "start from
  zero."
- `voice.py` (187 lines): records audio, transcribes via (presumably
  Whisper-compatible) API for voice input.
- `analytics.py` (258 lines): opt-in usage telemetry via PostHog, with
  UUID-based sampling (`is_uuid_in_percentage`) suggesting metrics are
  only collected from a percentage of users, and explicit model-name
  redaction (`_redact_model_name`) before sending — a real, if basic,
  privacy-conscious design choice worth preserving.
- `gui.py` (545 lines): a Streamlit-based browser GUI, appears to be an
  alternate/experimental frontend reusing the same `Coder` backend
  (`CaptureIO` subclasses `InputOutput` to redirect output into the
  Streamlit UI instead of the terminal). Worth explicit confirmation of
  how maintained/functional this currently is before counting on it —
  not reviewed for currency in this pass.
- `onboarding.py` (428 lines): first-run flow, including an OpenRouter
  OAuth PKCE flow (`generate_pkce_codes`, `exchange_code_for_key`,
  `start_openrouter_oauth_flow`) to let a brand-new user sign up for
  OpenRouter and get an API key without leaving the terminal — a nicely
  frictionless onboarding mechanism worth keeping.

## 10. What this review changes about the fork-vs-rebuild decision

Reinforces "fork," with more specific reasoning than before:

1. The `Coder` strategy-pattern architecture is genuinely extensible —
   both target features (MCP support, approval-gated apply) attach at
   clean, existing extension points (`functions`/tool_call plumbing;
   the `apply_updates()`/`confirm_ask` choke point) rather than fighting
   the design.
2. The edit-format subclasses represent real, hard-won correctness work
   (multi-strategy fuzzy matching, partial-JSON repair, reflection/retry
   loop, per-format prompt engineering) — 12,264 lines of tests exist
   specifically because these edge cases were expensive to discover.
   Rebuilding would mean re-discovering most of them.
3. Some real technical debt is visible and should be scoped explicitly
   before/during the fork, not discovered mid-build:
   - Two parallel tree-sitter binding paths (cache v3 vs v4) — pick one,
     drop the other, as part of the initial cleanup pass.
   - `*_func_coder.py` variants may be legacy/pre-native-tool-calling —
     worth confirming whether they're still reachable/used before
     carrying them forward.
   - GitPython's index-version-3 bug (#211) is a dependency-level issue,
     not fixable purely inside aider's code as currently structured —
     decide up front whether to patch/vendor/pin GitPython or shell out
     to `git` directly for the affected paths.
   - The commented-out fuzzy edit-distance fallback in
     `search_replace.py`'s `replace_most_similar_chunk` (dead code after
     an early `return`) — sign of an abandoned experiment; should be
     either finished, tested, and re-enabled, or deleted, not left
     ambiguously half-present.
   - The Streamlit GUI's maintenance state is unconfirmed — decide
     whether it's in scope for v1 or explicitly deferred.

## 11. Follow-up pass — closed items

All items from the prior open-items list have now been read in full.
Findings:

### 11.1 sendchat.py, exceptions.py, history.py (full reads)

- `sendchat.py` (61 lines): two small message-hygiene functions.
  `sanity_check_messages` enforces strict user/assistant alternation
  (system messages excluded) and raises `ValueError` with a formatted
  transcript if violated — this is what feeds `apply_updates()`'s
  `ValueError` → reflection-retry path when message structure breaks.
  `ensure_alternating_roles` is the repair counterpart: inserts empty
  opposite-role messages to fix consecutive same-role messages rather
  than erroring. Small, well-scoped, easy to carry forward as-is.
- `exceptions.py` (113 lines): `LiteLLMExceptions` builds a lookup table
  mapping every litellm exception class name to an `ExInfo(name, retry,
  description)` triple — whether that error class is auto-retryable and
  what human-readable message to show. Notably, `_load()` self-validates
  at import time: it walks `dir(litellm)` for anything ending in
  "Error" that's a real exception subclass and **raises `ValueError` if
  litellm has an exception aider doesn't know about**. This is a real,
  working "catch drift from an upstream dependency" mechanism — worth
  preserving and reusing verbatim; it directly prevents a class of
  silent failure (new litellm exception type falls through as
  unhandled/unretryable without anyone noticing) the same way the model-
  metadata dynamic-fetch system prevents metadata drift. `get_ex_info`
  also special-cases a few specific error message substrings (e.g.
  "insufficient credits" + HTTP 402 embedded in an `APIError` string,
  or `boto3` missing for Bedrock) to give more precise guidance than the
  generic class-level mapping would — evidence of real production
  incidents driving specific fixes over time.
- `history.py` (143 lines): `ChatSummary` implements recursive,
  token-budget-aware chat history compression. `too_big`/`tokenize`
  check against a `max_tokens` budget; `summarize_real` does a binary
  split (finds a split point ending on an assistant message, keeps the
  tail verbatim, summarizes the head via a cheap "weak model" call,
  recurses with increasing `depth` up to 3 if the result still doesn't
  fit). This is a genuinely non-trivial, already-debugged algorithm
  (note the explicit reservation of a 512-token safety buffer against
  the model's real max-input-tokens, and the depth-capped recursion to
  guarantee termination) — another point in favor of forking rather
  than reimplementing.

### 11.2 repomap.py ranking algorithm (full read)

Confirmed: it's PageRank over a dependency graph, using `networkx`.
Nodes are files; edges connect a file that *references* an identifier
to file(s) that *define* it, weighted by a heuristic score. The
weighting logic (lines 380-574) is intricate and worth knowing in
detail before touching it:
- Files currently in the chat, or explicitly mentioned by the user, get
  "personalization" mass in the pagerank call (biases rank toward
  code related to what the user is actively discussing).
- Per-identifier edge weight multiplier (`mul`) is boosted 10x if the
  identifier was mentioned in conversation, another 10x if it "looks
  like a real identifier" (snake_case/kebab-case/camelCase and ≥8 chars
  — a heuristic to deprioritize generic short names like `i`, `get`,
  `x`), and reduced 10x if the identifier starts with `_` (treated as
  private/less relevant) or has more than 5 definitions across the repo
  (deprioritizes overly generic/ambiguous names).
- References from files already in the chat get a 50x weight boost —
  strongly biases the map toward "what's relevant to code you're
  already editing."
- Handles a documented tree-sitter version quirk directly (line 473-479
  comment): older tree-sitter (0.23.2) doesn't count some function
  definitions as both a "def" and a "ref" for certain languages (Ruby
  example given), so a small self-edge is added for definitions with no
  detected references, as a workaround.
- Includes defensive handling for `ZeroDivisionError` from
  `networkx.pagerank` (documented as a fix for a specific filed bug,
  #1536) — falls back to unpersonalized pagerank, and if that also
  fails, returns an empty map rather than crashing.
- Results are cached three ways: a persistent disk cache
  (`diskcache`/SQLite, keyed by file mtime, for parsed tree-sitter tags
  per file) plus an in-memory `map_cache` keyed by
  (chat_files, other_files, max_tokens[, mentioned_fnames/idents]),
  with a `refresh` policy (`auto`/`always`/`files`/`manual`) that
  decides whether to trust the cache — `auto` only recomputes if the
  last computation took over 1 second, a pragmatic latency/freshness
  tradeoff.

This confirms the earlier assessment: real, tuned, multi-year heuristic
work. Reimplementing "map your codebase" from scratch to reach parity
would mean re-deriving these specific weight constants and edge cases
through the same kind of real-world trial and error aider already went
through — a strong argument for forking rather than rebuilding this
subsystem.

### 11.3 search_replace.py fuzzy-matching chain (full read)

The complete strategy list (lines 528-562) confirms and extends the
earlier finding. Three matching strategies are tried in order, each
across up to 4 text preprocessing variants (raw / strip-blank-lines /
relative-indent / both):
1. `search_and_replace` — exact substring match/replace (the cheap,
   fast path — succeeds most of the time).
2. `git_cherry_pick_osr_onto_o` — an unusual, clever fallback: actually
   shells out to a **real git repository created in a temp dir**
   (`GitTemporaryDirectory`), commits original→search→replace as three
   commits, then cherry-picks the search→replace diff onto the original
   using git's own merge/cherry-pick algorithm, relying on git's mature
   conflict-resolution logic instead of reimplementing one. If it
   conflicts, returns None (falls through to the next strategy) rather
   than raising.
3. `dmp_lines_apply` — uses Google's `diff-match-patch` library
   operating at line granularity (each line mapped to a single
   character via `diff_linesToChars` so DMP's char-level diff algorithm
   effectively operates on whole lines), with fuzzy match
   thresholds tuned specifically for this use (`Match_Threshold=0.1`,
   very permissive).
- `relative_indent` preprocessing (referenced, not fully unpacked in
  this pass but its role is clear from usage): normalizes indentation
  to relative levels before matching, so an LLM-produced SEARCH block
  with systematically-wrong absolute indentation (e.g. it "unindented"
  by the wrong amount) can still match.
- Two more strategies exist in the file (`dmp_apply`, char-level;
  `git_cherry_pick_sr_onto_so`, a variant ordering) but are **not**
  included in the live `editblock_strategies`/`udiff_strategies` lists
  — present as tested-but-unused alternatives, likely kept for the
  `main()`/benchmarking harness at the bottom of the file rather than
  production use.

Net: the "try several fundamentally different algorithms, each with
several text-normalization variants, cheapest/most-precise first" design
is a real, considered strategy for handling imperfect LLM output — not
something to casually reproduce from a blank page.

### 11.4 patch_coder.py end-to-end (full read)

Confirms and extends the earlier summary. The parser
(`_parse_patch_text`) hand-writes a state machine over the custom
"*** Begin Patch / *** Update File: X / @@ .../*** End Patch" format,
built directly on the earlier-read `find_context_core` fuzz-tiered
context matching (exact → rstrip-tolerant → strip-tolerant). Notable
robustness details:
- Tolerates a missing `*** Begin Patch` sentinel if the content still
  "looks like" a patch (heuristic check for `@@`/`*** Update File:`
  etc.), issuing a warning instead of hard-failing — another example of
  "don't reject output that's probably fine over a formatting technicality."
  This directly supports the design principle in ForgePair's spec
  (§4 "honest failure handling") — the pattern of tolerate-and-warn vs.
  silently-fail-with-no-explanation is already inconsistently applied
  across the codebase; worth standardizing.
- Supports multi-chunk updates to the same file across multiple
  `*** Update File:` blocks in one patch, merging them.
- Supports an explicit file-move (`*** Move to:`) as part of an update
  action, and duplicate-delete detection (warns and ignores rather than
  erroring).
- Raises structured `DiffError` (caught and re-raised as `ValueError`
  in `get_edits()` for consistency with the other coders' error-
  handling contract) for genuinely malformed input: conflicting
  actions on the same path, missing file content for a referenced path,
  invalid line prefixes.

### 11.5 `*_func_coder.py` variants — live/dead audit (confirmed)

Definitively **legacy/dead code**, confirmed by direct evidence:
`aider/coders/__init__.py` imports and registers 14 coder classes in
`__all__`, and explicitly comments out the import and registration of
`SingleWholeFileFunctionCoder` (lines 16 and 28: `# from
.single_wholefile_func_coder import SingleWholeFileFunctionCoder` /
`#    SingleWholeFileFunctionCoder,`). `EditBlockFunctionCoder` and
`WholeFileFunctionCoder` aren't even imported at all — not present
anywhere in `__init__.py`, commented or otherwise. None of the three
`_func_coder.py` files are reachable via `Coder.create()`'s
`coders.__all__` lookup, meaning **they cannot be selected by any
`--edit-format` value today** — they are unreachable dead code sitting
in the tree. Confirmed further by the test suite: no
`test_editblock_func.py` or `test_wholefile_func.py` exists (see §11.6),
meaning they aren't even exercised by CI. These three files
(editblock_func_coder.py, wholefile_func_coder.py,
single_wholefile_func_coder.py, plus their matching `*_prompts.py`
files) are safe to delete outright in a fork rather than carry forward
or investigate further — no functional risk, pure cleanup.

### 11.6 gui.py current state (CONFIRMED WORKING, verified 2026-09-08 during Phase 1)

Update: this was previously flagged as unconfirmed pending runtime
verification. Now verified end-to-end against the ForgePair fork:
- `pip install -r requirements/requirements-browser.txt` (the optional
  `browser` extra) installs `streamlit==1.55.0` cleanly, no errors.
- `aider --gui` (headless mode via `STREAMLIT_SERVER_HEADLESS=true`)
  launches a real Streamlit server on port 8501.
- `curl http://localhost:8501/` returns HTTP 200 with real HTML content.
- `curl http://localhost:8501/_stcore/health` returns "ok" (HTTP 200) --
  this specifically confirms the app script (`gui.py`, which drives the
  same `Coder.create()` backend as the CLI) executed successfully, not
  just that the base Streamlit server started.

Conclusion: gui.py is genuinely functional, not bit-rotted. It remains
uncovered by the automated test suite (still no test_gui.py) and
untouched by CI, so this manual verification should be repeated after
any change that touches `Coder.create()`, `InputOutput`, or gui.py
itself -- but as of this fork's baseline, it is confirmed working and
safe to carry forward into ForgePair rather than treated as an unknown.

### 11.7 Full test suite categorization (36 files, 12,264 lines)

By subsystem, from `tests/basic/` (34 files) + `tests/browser/` (1) +
`tests/help/` (1) + `tests/scrape/` (2):

- Core coder/edit-format: test_coder.py, test_editblock.py,
  test_find_or_blocks.py, test_udiff.py, test_wholefile.py — the
  central edit-application logic is well covered.
- Model layer: test_models.py, test_model_info_manager.py,
  test_openrouter.py, test_reasoning.py, test_aws_credentials.py —
  confirms the dynamic-metadata system (§6 of this review) has real
  test coverage, reinforcing that it's safe to reuse as-is.
- Git integration: test_repo.py, test_sanity_check_repo.py.
  **No test specifically targets the GitPython index-version-3 bug
  (#211)** — consistent with it being a real, unfixed, uncovered gap
  rather than something already guarded against.
- Repo-map: test_repomap.py — the PageRank-based system (§11.2) does
  have dedicated test coverage.
- CLI/UX: test_commands.py, test_io.py, test_main.py, test_editor.py,
  test_linter.py, test_run_cmd.py, test_watch.py, test_history.py,
  test_sendchat.py.
- Onboarding/config: test_onboarding.py, test_deprecated.py,
  test_ssl_verification.py.
- Support systems: test_analytics.py, test_exceptions.py,
  test_special.py, test_urls.py, test_utils.py, test_voice.py.
- Web/browser: tests/browser/test_browser.py,
  tests/scrape/test_scrape.py, tests/scrape/test_playwright_disable.py.
- Docs: tests/help/test_help.py.

**Confirmed gaps in coverage** (not tested anywhere in the 36 files):
- `gui.py` (Streamlit GUI) — no test_gui.py, as noted in §11.6.
- The three dead `*_func_coder.py` files — no corresponding tests,
  consistent with §11.5's dead-code finding.
- `report.py`'s crash-reporting/GitHub-issue-filing flow — no
  test_report.py; this is user-facing and un-tested, worth a test in
  ForgePair if this mechanism (or its redesigned triage-aware
  successor per the product spec) is carried forward.
- `patch_coder.py` has no dedicated `test_patch.py`/`test_patch_coder.py`
  — notable given it's one of the most complex, newest (per the "adapted
  from apply_patch.py" comment, likely the most recently added) edit
  formats, and per this review the most intricate hand-written parser
  in the codebase. This is a real risk spot: complex, relatively new,
  untested code — flag for priority test-writing if `PatchCoder` is
  carried into ForgePair.

## 12. Overall conclusion of the full deconstruction

Every open item from the initial pass has been closed. Nothing found in
this closing pass changes the fork recommendation — if anything it
strengthens it further: three more genuinely non-trivial, already-
debugged subsystems were confirmed (chat summarization, exception
normalization with self-validating drift detection, the full
PageRank repo-map weighting scheme) that would be expensive to
reproduce from scratch for no product benefit. The one clear action
item is cleanup, not caution: delete the three dead `*_func_coder.py`
files, and treat `patch_coder.py` and `gui.py` as the two areas
needing explicit new test coverage / runtime verification before
ForgePair relies on them, since both are real capabilities but under-
verified in the current codebase as inherited.

## 13. Phase 1 execution corrections (2026-09-08)

While executing BUILD_PLAN.md Phase 1 against the actual fork, two
findings from this review needed correction based on ground-truth
investigation rather than static reading:

1. **§10's tree-sitter dual-binding-path item was an oversimplification.**
   `USING_TSL_PACK` (in repomap.py) actually gates two separate things,
   only one of which is dead. The `CACHE_VERSION` selection and an
   `all_nodes` construction branch WERE dead (tree-sitter-language-pack
   is a hard, unconditional dependency via grep-ast, so the flag is
   always True) and were simplified. But `get_scm_fname()`'s fallback
   to the legacy `tree-sitter-languages` query directory is NOT dead --
   confirmed via directory diff that 11 languages (php, typescript,
   kotlin, scala, haskell, fortran, csharp, hcl, julia, ql, zig) only
   have query files under the legacy directory, not the new one.
   Removing that fallback would have silently broken repo-map support
   for those languages. Lesson: "two binding paths" framing was too
   coarse; the actual finding needed function-level granularity.

2. **gui.py's liveness is now confirmed** (see updated §11.6 above) --
   was flagged as an open unknown, now verified working end-to-end.

3. **The two unused fuzzy-match strategies in search_replace.py**
   (`dmp_apply`, `git_cherry_pick_sr_onto_so`) were investigated further
   and found genuinely ambiguous -- not clearly dead code, but also not
   clearly deliberate: they're referenced by a commented-out debug/
   benchmark harness (`proc()`/`short_names` at the bottom of the file)
   that itself has zero test coverage. Per explicit decision, this was
   deferred rather than resolved unilaterally at the time.

   RESOLVED (2026-09-09): re-audited during a Phase-by-phase status
   check and found genuinely dead per the criteria this item itself
   set: no test coverage, no caller outside each other, and no caller
   outside the debug/benchmark harness -- where both were ALREADY
   commented out of the harness's own default strategy list, not just
   absent from the live production chains. `dmp_apply` was also
   functionally redundant with `dmp_lines_apply` (already live), same
   technique operating on lines instead of characters. Deleted both,
   plus `map_patches()` (only caller was `dmp_apply`, now orphaned).
   Verified the debug harness still runs correctly end-to-end after
   removal (real fixture set, real passing results), not just an
   import-time check. See BUILD_PLAN.md Phase 1 item 5.

See BUILD_PLAN.md Phase 1 for the full list of changes made and their
verification (test suite results before/after each step).
