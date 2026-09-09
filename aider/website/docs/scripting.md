---
parent: More info
nav_order: 400
description: You can script aider via the command line or python.
---

# Scripting aider

You can script aider via the command line or python.

## Command line

Aider takes a `--message` argument, where you can give it a natural language instruction.
It will do that one thing, apply the edits to the files and then exit.
So you could do:

```bash
aider --message "make a script that prints hello" hello.js
```

Or you can write simple shell scripts to apply the same instruction to many files:

```bash
for FILE in *.py ; do
    aider --message "add descriptive docstrings to all the functions" $FILE
done
```

Use `aider --help` to see all the 
[command line options](/docs/config/options.html),
but these are useful for scripting:

```
--stream, --no-stream
                      Enable/disable streaming responses (default: True) [env var:
                      AIDER_STREAM]
--message COMMAND, --msg COMMAND, -m COMMAND
                      Specify a single message to send GPT, process reply then exit
                      (disables chat mode) [env var: AIDER_MESSAGE]
--message-file MESSAGE_FILE, -f MESSAGE_FILE
                      Specify a file containing the message to send GPT, process reply,
                      then exit (disables chat mode) [env var: AIDER_MESSAGE_FILE]
--yes                 Always say yes to every confirmation [env var: AIDER_YES]
--auto-commits, --no-auto-commits
                      Enable/disable auto commit of GPT changes (default: True) [env var:
                      AIDER_AUTO_COMMITS]
--dirty-commits, --no-dirty-commits
                      Enable/disable commits when repo is found dirty (default: True) [env
                      var: AIDER_DIRTY_COMMITS]
--dry-run, --no-dry-run
                      Perform a dry run without modifying files (default: False) [env var:
                      AIDER_DRY_RUN]
--commit              Commit all pending changes with a suitable commit message, then exit
                      [env var: AIDER_COMMIT]
```


## Python

You can also script aider from python:

```python
from aider.coders import Coder
from aider.models import Model

# This is a list of files to add to the chat
fnames = ["greeting.py"]

model = Model("gpt-4-turbo")

# Create a coder object
coder = Coder.create(main_model=model, fnames=fnames)

# This will execute one instruction on those files and then return
coder.run("make a script that prints hello world")

# Send another instruction
coder.run("make it say goodbye")

# You can run in-chat "/" commands too
coder.run("/tokens")

```

See the
[Coder.create() and Coder.__init__() methods](https://github.com/Aider-AI/aider/blob/main/aider/coders/base_coder.py)
for all the supported arguments.

It can also be helpful to set the equivalent of `--yes` by doing this:

```python
from aider.io import InputOutput
io = InputOutput(yes=True)
# ...
coder = Coder.create(model=model, fnames=fnames, io=io)
```

{: .note }
The python scripting API is not officially supported or documented,
and could change in future releases without providing backwards compatibility.

## Editor/IDE integration via shell-out

Aider is terminal-first by design -- full IDE extensions are
intentionally out of scope for now -- but the CLI flags above provide
a stable enough contract for an editor extension or script to shell
out to aider for a single scripted task, without needing to talk to
aider's internal Python API directly:

- **Invocation**: `aider --message "<instruction>" --yes-always <files...>`
  (or `--message-file <path>` for longer/templated instructions) runs one
  instruction non-interactively against the given files and exits --
  no chat loop, no prompts left waiting for input.
- **Exit codes**: aider currently distinguishes only two outcomes --
  `0` (the run completed, though this does not by itself guarantee an
  edit was actually applied -- e.g. `--dry-run` also exits `0`) and `1`
  (something on the error paths failed: bad arguments, git/repo
  problems, LLM/API errors, malformed edit responses, etc.). There is
  currently no differentiated exit code for e.g. "edits were rejected"
  vs. "provider error" vs. "malformed LLM response" -- if your
  integration needs to distinguish these, parse aider's stdout/stderr
  output rather than relying on the exit code alone, or use the Python
  scripting API above where you get direct access to
  `coder.aider_edited_files` and similar attributes after each `run()`
  call.
- **Non-interactive mode**: pair `--message`/`--message-file` with
  `--yes-always` for scripting -- without it, aider may still prompt
  for confirmations (e.g. adding a mentioned file, `--confirm-edits`)
  and hang waiting for input that will never come in a non-interactive
  context.
- **Editor-adjacent workflow without a dedicated plugin**: for
  in-editor triggering without shelling out to the CLI at all, see
  [Aider in your IDE](/docs/usage/watch.html) -- `--watch-files` lets
  aider watch your repo for `AI!`/`AI?` comments added in any editor
  and act on them, which covers much of what a dedicated IDE plugin
  would provide.
