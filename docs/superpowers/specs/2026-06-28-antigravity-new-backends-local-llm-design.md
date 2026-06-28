# Antigravity migration + new AI backends + custom local LLM — design

**Date:** 2026-06-28
**Status:** approved (decisions captured below), pending spec review
**Scope:** three user asks — (1) "gemini cli is dead; support Antigravity, wire
all", (2) add more AI backend CLIs, (3) support a custom local LLM server.

## Decisions (locked with user)

- **Antigravity:** full `gemini → antigravity` rename, **safe login paths only**.
  Google AI Studio API key (default) + Antigravity subscription via CLIProxyAPI.
  **No** native `cloudcode-pa /v1internal` client in this repo — that internal
  IDE gateway carries account-ban + breakage risk and stays inside the external
  cliproxy binary.
- **New CLIs:** DeepSeek, Qwen, Goose, Aider, Crush.
- **Local LLM:** extend `openai_compat.py` (optional key + localhost presets);
  no new backend.
- **Agents (Goose/Aider/Crush):** PTY-primary. `chat()` is headless where the
  tool supports it (Goose), best-effort/ceiling-noted otherwise.
- **Process:** spec → review → wave-by-wave build.

## Non-goals

- Native Antigravity OAuth client hitting `/v1internal` (ban risk; rejected).
- Qwen OAuth (discontinued upstream 2026-04-15, non-headless — dead).
- Robust TUI-scraping `chat()` for Aider/Crush (PTY covers the real use).
- Crush/Charm OAuth providers (Hyper, Claude Max) — v1 is api-key only.

## Backend contract (from `scratchpad/research/00-contract.md`)

There is **no global registry/enum**. Adding a backend =

1. new class in `packages/core/src/ai_accounts_core/backends/<kind>.py`
   satisfying `BackendProtocol`: `kind`, `supported_login_flows`, `metadata`,
   and async `detect / begin_login / validate / list_models / chat / get_usage
   / pty`. Subclass `CliBackendBase` for `_run()` + default `detect()`.
2. export from `backends/__init__.py` (`__all__`).
3. add `"<kind>"` to `_STATIC` in `backends/_models_fallback.py`; end
   `list_models()` with `return fallback("<kind>")`.
4. instantiate in the `backends=(...)` tuple in `apps/playground/server.py`.
5. (CLI backends) add a probe branch in `services/discovery.py:_probe_command`.
6. update the frontend per-kind maps (see "Frontend" below).
7. tests.

Chat + PTY dispatch is fully dynamic by `kind` — **zero** edits to
`routes/*` or `services/{chat,pty}.py`.

cliproxy-routed backends additionally touch `cliproxy/manager.py` `flag_map`,
`cliproxy/cliproxy_compat.toml` `[providers]`, and `cliproxy/_compat.py`
`_DEFAULT_OWNED_BY`.

## Archetypes

### A. Thin OpenAI-shaped api-key backend (DeepSeek, Qwen)

Model after `backends/openrouter.py`. Keyless metadata
(`InstallCheck(command=["true"], version_regex=r"(\d+)?")`,
`isolation_env_var=None`), `supported_login_flows = frozenset({"api_key"})`,
keyless `detect() → DetectResult(installed=True)`, an `_ApiKeySession`
(`TextPrompt(prompt_id="api_key", hidden=True)`), `validate()` = `GET
{base}/models` 200, `list_models()` parses OpenAI `{data:[{id,name,
context_length}]}` then `fallback("<kind>")`, `chat()` streams `POST
{base}/chat/completions`, `_env()` sets `<X>_API_KEY`, `get_usage() → []`,
`pty()` unsupported.

**DeepSeek** (`deepseek.py`, kind `deepseek`):
- base_url `https://api.deepseek.com` (Bearer). `/models` + `/chat/completions`
  confirmed OpenAI-shaped.
- env `DEEPSEEK_API_KEY`.
- live models `deepseek-v4-flash`, `deepseek-v4-pro`; legacy
  `deepseek-chat`/`deepseek-reasoner` deprecate 2026-07-24. `_STATIC["deepseek"]
  = ("deepseek-v4-flash", "deepseek-v4-pro")` (live `/models` self-corrects).

**Qwen** (`qwen.py`, kind `qwen`):
- base_url `https://dashscope.aliyuncs.com/compatible-mode/v1`
  (intl: `https://dashscope-intl.aliyuncs.com/compatible-mode/v1`). Offer a
  region `MenuPrompt` (CN / Intl / Custom) before the key prompt.
- env `DASHSCOPE_API_KEY`.
- `_STATIC["qwen"] = ("qwen3-coder-plus", "qwen3-coder-flash")`.
- Note: value-add over generic openai_compat is branding + region preset only
  (Qwen's free OAuth lane is dead). Shipped per explicit user request.

### B. Local LLM — extend `openai_compat.py` (no new file)

Credential stays JSON `{"api_key", "base_url"}`; **api_key may be empty**.

- `_decode_credential` unchanged; **`validate()`**: `if not base_url: return
  False` (drop the `or not api_key`). Send `Authorization` only when key is
  non-empty. Accept HTTP 200 **regardless of `data` length** (servers with no
  model loaded return `{"data": []}`). On `/models` 404 or connection refused,
  fall back to a `POST {base}/chat/completions` reachability probe before
  failing.
- **login session**: prepend a `MenuPrompt` of presets, each filling `base_url`:
  Ollama `http://localhost:11434/v1`, LM Studio `http://localhost:1234/v1`,
  vLLM `http://localhost:8000/v1`, llama.cpp `http://localhost:8080/v1`,
  oobabooga `http://localhost:5000/v1`, **Custom** (free-text base_url). Then an
  **optional** api_key `TextPrompt` (empty allowed). Frontend renders
  `MenuPrompt`/`TextPrompt` already → **no Vue changes**.
- `list_models()` already tolerates empty key; ensure empty-list path returns
  `fallback("openai_compat")` (which is `()`), giving a correct empty dropdown.

### C. CLI/PTY agent backend (Goose, Aider, Crush)

Model after `backends/opencode.py` (`CliBackendBase`, install-check, isolated
config dir, PTY). Credential JSON `{"provider", "api_key", "model"?}` (BYO
provider key). `pty()` launches the interactive tool with isolation env +
injected provider key. `list_models()` returns a static/curated `fallback`.
`get_usage() → []`.

**Goose** (`goose.py`, kind `goose`):
- install `goose --version` → `r"(\d+\.\d+\.\d+)"`.
- isolation `_env`: `GOOSE_PATH_ROOT=<isolation_dir>` **and
  `GOOSE_DISABLE_KEYRING=true`** (secrets otherwise collide in the shared system
  keyring — `GOOSE_PATH_ROOT` does not scope it). Also `GOOSE_PROVIDER`,
  `GOOSE_MODEL`, and the provider key env (`ANTHROPIC_API_KEY` / `OPENAI_API_KEY`
  / `OPENROUTER_API_KEY` …).
- `chat()`: subprocess `goose run -t <prompt> --no-session --output-format
  stream-json`; parse stream-json lines → `ChatStreamEvent` tokens.
  `# ponytail: chat() parses goose run stream-json; PTY is the fallback if the
  framing shifts.`
- `pty()`: `goose session`.

**Aider** (`aider.py`, kind `aider`):
- install `aider --version`; PyPI `aider-chat`.
- isolation: `isolation_env_var=None`; `_env` sets `HOME=<isolation_dir>` (so it
  does not auto-load host `~/.aider.conf.yml`/`~/.env`) + `<PROVIDER>_API_KEY`;
  run with `--no-git`.
- `chat()`: best-effort one-shot `aider --message <prompt> --yes` stdout
  capture. `# ponytail: PTY-primary; chat() is a one-shot scrape with no token
  stream — interactive use goes through pty().`
- `pty()`: `aider --model <model>`.
- `list_models()`: parse `aider --list-models <provider>` or curated static.

**Crush** (`crush.py`, kind `crush`):
- install `crush --version` → `r"(\d+\.\d+\.\d+)"`; `brew install
  charmbracelet/tap/crush` or `npm i -g @charmland/crush`.
- isolation `_env`: `CRUSH_GLOBAL_CONFIG=<dir>/crush.json` +
  `CRUSH_GLOBAL_DATA=<dir>/data`; write an isolated `crush.json` carrying the
  provider + api_key at login.
- `chat()`: unsupported (pure TUI). `# ponytail: crush is TUI-only; no headless
  chat — pty() only.`
- `pty()`: `crush`.
- `list_models()`: curated static from the Catwalk catalog.

## Antigravity rename (`gemini → antigravity`)

Per contract §(d), exhaustive. **Core:**

1. `backends/gemini.py` → `backends/antigravity.py`; `GeminiBackend` →
   `AntigravityBackend`; `kind = "antigravity"`; all internal `"gemini"`
   literals (LoginSession `backend_kind`, `fallback(...)`,
   `start_cliproxy_login(...)`).
2. `backends/__init__.py` import + `__all__`.
3. `_models_fallback.py` `_STATIC` key `gemini → antigravity`.
4. `apps/playground/server.py` import + tuple entry.
5. `cliproxy/manager.py` `flag_map` key `gemini → antigravity` (value stays
   `-antigravity-login`). Fix the stale `8085` callback-port comment → `51121`
   (verify at implementation).
6. `cliproxy/cliproxy_compat.toml` `[providers]` `gemini → antigravity = "google"`.
7. `cliproxy/_compat.py` `_DEFAULT_OWNED_BY` key.
8. `services/discovery.py` `_probe_command` branch + docstring.
9. `domain/backend.py` `BackendKind.GEMINI` → `ANTIGRAVITY = "antigravity"`;
   plus comment mentions in `install/backend_cli.py`,
   `login/cli_orchestrator.py`, `services/accounts.py`, `domain/chat_events.py`.
- **Isolation env:** `GEMINI_CLI_HOME` → `ANTIGRAVITY_HOME` (read the old name as
  a fallback alias for one release).
- **Login flows:** keep order — `api_key` (Google AI Studio, default) first,
  `cli_browser` (CLIProxyAPI `--antigravity-login`) second.

**Data migration** (this is why the team stopped at a label-only change before):

- New sqlite migration in `adapters/storage_sqlite/migrations.py`:
  `UPDATE backends SET kind='antigravity' WHERE kind='gemini'` (and any other
  `kind`-keyed table/rows). Guarded + idempotent.
- One-time config-dir move: if `~/.gemini` exists and `~/.antigravity` does not,
  rename it (best-effort, logged, never raises). Runs once at startup / migration.

**Frontend** (kind-keyed maps — same list applies to the new kinds):

1. `vue-styled/src/utils/assistantLabel.ts` `BACKEND_DISPLAY_NAMES`.
2. `vue-styled/src/components/AiChatSelector.vue` kind→label.
3. `vue-styled/src/components/AllModeResponses.vue` kind→{bg,fg,label}.
4. `vue-styled/src/components/AccountWizard.vue`: `PROXY_SUPPORTED_KINDS`
   (antigravity ✓), `DEFAULT_CONFIG_DIR_MAP` (antigravity `~/.antigravity`,
   goose `~/.config/goose`), `apiKeyEnv.envMap` (`DEEPSEEK`, `DASHSCOPE`,
   provider-based for agents), `NO_CLI_KINDS` (deepseek, qwen ✓; goose/aider/
   crush ✗), the ~323 comment.
5. `vue-styled/src/components/OnboardingFlow.vue` backend list + flow map.
6. `vue-styled/src/components/LoginStream.vue` `backendKind === 'gemini'` →
   `'antigravity'`.
7. `apps/playground/src/App.vue` `--kind-gemini` → `--kind-antigravity`,
   `.account-row--gemini`, intro copy.

## Testing

- **Python** (`packages/core/tests/backends/`): `test_deepseek.py`,
  `test_qwen.py`, `test_goose_backend.py`, `test_aider_backend.py`,
  `test_crush_backend.py`; extend `openai_compat` tests for keyless + preset;
  rename `test_gemini_*` → `test_antigravity_*`; a migration test
  (`gemini`-row → `antigravity`); update
  `test_static_fallback_omits_deprecated.py`.
  Each backend: `validate()` happy/empty-key/non-200, `list_models()` live +
  fallback, `detect()`, login session event sequence, `_env()` isolation vars.
- **Vue** (`packages/vue-styled/tests/`): `AccountWizard.test.ts`,
  `AiChatPanel.test.ts` — `gemini`→`Antigravity` labels, new kinds in maps.
- **Grep guard:** `grep -rn "gemini\|Gemini"` over `*.py/*.ts/*.vue/*.toml`
  (excluding `node_modules/.venv/.worktrees`) returns zero non-comment hits.
- `just lint && just typecheck && just test` green.

## Sequencing

- **Wave 1 (low-risk, high-value):** Antigravity rename + migration; DeepSeek;
  Qwen; local-LLM `openai_compat` extension. Each independently shippable.
- **Wave 2 (CLI/PTY agents):** Goose, Aider, Crush (parallelizable — separate
  files; isolation in worktrees to avoid frontend-map edit conflicts).
- Frontend per-kind map edits are the one shared-file hotspot across both waves
  — batch them per wave to avoid churn.

## Risks / open questions

- Antigravity cliproxy callback port `51121` vs stale `8085` — confirm against
  installed CLIProxyAPI at implementation.
- DeepSeek/Qwen static fallback ids drift across releases — kept minimal; live
  `/models` is the source of truth.
- Goose `--provider`/`--model` run-flag names disagree across docs — verify the
  `goose run` stream-json framing on a real install before locking `chat()`.
- Aider host-config bleed — `HOME` override is mandatory, add a test asserting
  it doesn't read the real `~/.aider.conf.yml`.
- Qwen separate-backend value is thin; revisit collapsing into an openai_compat
  preset if maintenance cost shows up.
