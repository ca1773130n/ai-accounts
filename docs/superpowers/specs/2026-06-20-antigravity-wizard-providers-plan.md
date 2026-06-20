# Implementation Plan: Antigravity + 3-step wizard + new providers

Branch: `feat/antigravity-wizard-providers`. Spec:
`2026-06-20-antigravity-wizard-providers-design.md`.

Agents own **disjoint file sets** to avoid edit conflicts. Pinned symbol names
are contractual — Phase-2 wiring imports them exactly.

## Pinned names / kinds

| Backend | file | class | kind | display |
|--|--|--|--|--|
| OpenRouter | `backends/openrouter.py` | `OpenRouterBackend` | `openrouter` | `OpenRouter` |
| Generic OpenAI-compat | `backends/openai_compat.py` | `OpenAiCompatBackend` | `openai_compat` | `OpenAI-compatible (Custom)` |
| Kimi | `backends/kimi.py` | `KimiBackend` | `kimi` | `Kimi (Moonshot)` |

## Phase 1 — create new files (parallel; new files only, no shared edits)

### A1 — OpenRouterBackend (`openrouter.py` + `tests/backends/test_openrouter.py`)
- Template: `backends/opencode.py` (it already talks to `openrouter.ai`).
- Keep ONLY the `api_key` login flow + `chat()`/`list_models()` hitting
  `https://openrouter.ai/api/v1`. Drop `cli_browser`, `OPENCODE_HOME`, the
  `opencode` CLI shellouts.
- Keyless: no CLI binary. Override `detect()` to return available (read
  `_base.py` `CliBackendBase.detect`; if it shells a binary, override). Set
  `install_check` to a benign `InstallCheck(command=["true"], version_regex=r"(\d+)?")`.
- `_env`: `OPENROUTER_API_KEY=<key>`. `get_usage` → `[]`.
- Test: httpx-mock `chat()` posts to `openrouter.ai/api/v1/chat/completions`
  and yields token+done. (assert-based; vitest-free — pytest.)

### A2 — OpenAiCompatBackend (`openai_compat.py` + `tests/backends/test_openai_compat.py`)
- Two-input `api_key` flow: session yields a `base_url` TextPrompt THEN an
  `api_key` TextPrompt (sequential prompts work — see gemini cli_browser).
  Store credential as **JSON bytes** `{"api_key": ..., "base_url": ...}`.
- `metadata.login_flows[0].requires_inputs` = `[InputSpec(base_url, text),
  InputSpec(api_key, secret)]` (UI hint only).
- `validate`/`list_models`/`chat` decode the JSON credential, read `base_url`,
  hit `{base_url}/models` and `{base_url}/chat/completions` (OpenAI shape, same
  parsing as opencode). Empty/invalid base_url → fail gracefully.
- Keyless detect()/install_check as in A1. `get_usage` → `[]`.
- Test: assert `chat()` posts to the configured `base_url` (httpx mock) — the
  routing path. Assert credential round-trips base_url.

### A3 — KimiBackend (`kimi.py` + `tests/backends/test_kimi.py`)
- Template: gemini's `_GeminiCliProxySession` but `backend_kind="kimi"`,
  `start_cliproxy_login("kimi")`. Single `cli_browser` flow.
- `validate` → `bool(await cliproxy_list_models("kimi"))`. `chat()` →
  `_chat_via_cliproxy(request)`. `list_models` → cliproxy then
  `fallback("kimi")`. Keyless detect(). `get_usage` → `[]`.
- Test: assert flow_kind/backend_kind and that begin_login("cli_browser")
  returns the cliproxy session; monkeypatch `start_cliproxy_login` to assert it
  is called with `"kimi"`.

### A4 — Wizard frontend (`packages/vue-styled/src/components/AccountWizard.vue`)
- **3 displayed phases.** Add `DISPLAY_PHASES`: `subscription,cli→"Setup"`;
  `login,proxy→"Login"`; `plan→"Finish"`. Replace the step-indicator render to
  iterate the 3 deduped phases; active = phase of `currentStep`. Keep internal
  `WizardStep`/`STEP_ORDER`/`goNext`/`goPrev` unchanged.
- **Remove config-dir confirm UI**: delete the `configPath` input block,
  "Customize path" control, and `accountWizard.tour.cli.path.*` usage from the
  cli-step template. Keep `configPath`/`suggestConfigPath` logic (still used at
  save). Put the path behind an optional `<details>`"Advanced" toggle.
- The cli step becomes a one-line badge; for keyless kinds show
  "No CLI required".
- **Antigravity relabel**: user-facing "Gemini" → "Antigravity" strings (the
  `gemini` key in `DEFAULT_CONFIG_DIR_MAP` stays `.gemini`; only labels change).
- Add map entries for new kinds: `DEFAULT_CONFIG_DIR_MAP` (`openrouter`,
  `openai_compat`, `kimi`), `apiKeyEnv` envMap (`OPENROUTER`, `OPENAI`, `KIMI`),
  and `PROXY_SUPPORTED_KINDS` add `kimi`.
- Don't break the existing wizard step test; update it for the 3-phase indicator
  and absent config-path input.

## Phase 2 — wiring (single agent, BARRIER after Phase 1; shared Python files)

- `cliproxy/manager.py` `flag_map`: `"gemini": "--login"` →
  `"gemini": "-antigravity-login"`; add `"kimi": "-kimi-login"`. Update the
  nearby comment.
- `backends/gemini.py`: `display_name` → `"Antigravity"`; rewrite the
  `cli_browser` flow `display_name`/`description` to Antigravity wording
  (subscription via Google Antigravity). Keep `kind="gemini"`, env var, config
  paths untouched.
- `install/backend_cli.py`: remove the `"gemini"` install strategy (Antigravity
  needs no terminal CLI).
- `backends/__init__.py`: import + export `OpenRouterBackend`,
  `OpenAiCompatBackend`, `KimiBackend`.
- `apps/playground/server.py`: add the three to the `backends=(...)` tuple.
- `_models_fallback.py` `_STATIC`: add `"openrouter": ()`, `"openai_compat": ()`,
  `"kimi": ()` (keeps `fallback()` keys explicit).
- Only wire backends whose Phase-1 file actually got created.

## Phase 3 — verify (single agent)

- `uv run pytest packages/core/tests/backends -q` (new + existing backend tests).
- `uv run ruff check packages/core/src` (or `just lint`).
- `pnpm --filter @ai-accounts/vue-styled typecheck` and `... test`.
- Report pass/fail with the failing output verbatim. Do NOT claim success
  without command output.

## Phase 4 — adversarial review (single agent) + targeted fixes

- Review the full diff for: protocol completeness (all `BackendProtocol`
  methods present on new backends), credential JSON handling in openai_compat,
  the cliproxy flag change, wizard indicator math (exactly 3 phases, no orphan
  config-path refs), and any silent failures.
- Emit a findings list; a fix agent applies only the real, high-confidence ones.

## Out of scope (per spec)
Renaming internal `gemini` kind; Qwen/iFlow OAuth; install strategies for
keyless backends beyond the benign `install_check`.
