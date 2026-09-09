---
parent: Connecting to LLMs
nav_order: 510
---

# GitHub Copilot

Aider supports GitHub Copilot two ways:

1. **Native provider (recommended)** -- litellm's `github_copilot/`
   provider, which handles its own OAuth device-flow login and token
   refresh automatically. No manual token copying required.
2. **Manual OpenAI-compatible endpoint** -- Copilot's OpenAI-style REST
   API, configured by hand with an existing token. Documented below as
   a fallback for anyone who already has this working, or whose litellm
   version predates the native provider.

---

## Native provider (recommended)

```bash
aider --model github_copilot/gpt-4o
```

The first time you use a `github_copilot/*` model, litellm's native
provider will prompt you to visit `https://github.com/login/device`
and enter a short code to authorize aider via GitHub's OAuth device
flow -- no manual token copying from `apps.json` or any IDE required.
Once authorized, the access token and API key are cached locally
(default: `~/.config/litellm/github_copilot/`) and refreshed
automatically; you won't be prompted again until the token expires.

Aider automatically sends the `Editor-Version` and
`Copilot-Integration-Id` headers Copilot's API requires for this
provider -- you don't need to configure them via
`~/.aider.model.settings.yml` yourself.

Discover which models your Copilot subscription allows the same way
as the manual path below (see "Discover available models"), but
prefix with `github_copilot/` instead of `openai/`:

```bash
aider --model github_copilot/claude-3.7-sonnet-thought
```

### Configuration file (`~/.aider.conf.yml`)

```yaml
model: github_copilot/gpt-4o
weak-model: github_copilot/gpt-4o-mini
```

No `openai-api-base`/`openai-api-key` needed for this path -- the
native provider manages its own credentials.

### Custom token storage location

Set `GITHUB_COPILOT_TOKEN_DIR` to change where the native provider
caches its login token (default `~/.config/litellm/github_copilot/`).

---

## Manual OpenAI-compatible endpoint (fallback)

Aider can also connect to GitHub Copilot's LLMs because Copilot exposes a standard **OpenAI-style**
endpoint at:

```
https://api.githubcopilot.com
```

First, install aider:

{% include install.md %}

---

## Configure your environment

```bash
# macOS/Linux
export OPENAI_API_BASE=https://api.githubcopilot.com
export OPENAI_API_KEY=<oauth_token>

# Windows (PowerShell)
setx OPENAI_API_BASE https://api.githubcopilot.com
setx OPENAI_API_KEY  <oauth_token>
# …restart the shell after setx commands
```

---

### Where do I get the token?
The easiest path is to sign in to Copilot from any JetBrains IDE (PyCharm, GoLand, etc).
After you authenticate a file appears:

```
~/.config/github-copilot/apps.json
```

On Windows the config can be found in:

```
~\AppData\Local\github-copilot\apps.json
```

Copy the `oauth_token` value – that string is your `OPENAI_API_KEY`.

*Note:* tokens created by the Neovim **copilot.lua** plugin (old `hosts.json`) sometimes lack the
needed scopes. If you see “access to this endpoint is forbidden”, regenerate the token with a
JetBrains IDE.

---

## Discover available models

Copilot hosts many models (OpenAI, Anthropic, Google, etc).  
List the models your subscription allows with:

```bash
curl -s https://api.githubcopilot.com/models \
  -H "Authorization: Bearer $OPENAI_API_KEY" \
  -H "Content-Type: application/json" \
  -H "Copilot-Integration-Id: vscode-chat" | jq -r '.data[].id'
```

Each returned ID can be used with aider by **prefixing it with `openai/`**:

```bash
aider --model openai/gpt-4o
# or
aider --model openai/claude-3.7-sonnet-thought
```

---

## Quick start

```bash
# change into your project
cd /to/your/project

# talk to Copilot
aider --model openai/gpt-4o
```

---

## Optional config file (`~/.aider.conf.yml`)

```yaml
openai-api-base: https://api.githubcopilot.com
openai-api-key:  "<oauth_token>"
model:           openai/gpt-4o
weak-model:      openai/gpt-4o-mini
show-model-warnings: false
```

---

## FAQ

* Calls made through aider are billed through your Copilot subscription  
  (aider will still print *estimated* costs).
* The Copilot docs explicitly allow third-party “agents” that hit this API – aider is playing by
  the rules.
* Aider talks directly to the REST endpoint—no web-UI scraping or browser automation.
* Both the native provider and the manual endpoint above talk to the same underlying Copilot
  service and are billed identically -- the difference is purely how authentication is handled.

