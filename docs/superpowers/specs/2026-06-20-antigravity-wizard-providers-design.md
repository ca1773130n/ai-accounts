# Design: Antigravity migration, 3-step wizard, new OAuth/API-key providers

Date: 2026-06-20
Status: awaiting approval

## Goals (from user)

1. Google deprecated the Gemini CLI and launched **Antigravity** — switch the
   "Gemini" account to Antigravity when adding an account.
2. Reduce the wizard's **displayed steps to 3** (narrow-mobile breaks today) and
   remove the **config-dir confirm** step.
3. Add support for **more providers** that do OAuth or API key, incl.
   **OpenRouter**.

## Grounded reality (verified against installed tooling, not assumed)

- **There is no real "Antigravity CLI" npm package.** The `antigravity` npm
  package is a joke placeholder ("placeholder for the haters"). Antigravity is
  Google's IDE, not a terminal CLI.
- The installed **`cliproxyapi` already has `-antigravity-login`** (native OAuth).
  In this codebase a "gemini" account's OAuth *already* delegates to
  `cliproxyapi --login` (see `gemini.py` `_GeminiCliProxySession`). So
  "use Antigravity" = **swap the cliproxy login flag** `--login` →
  `-antigravity-login` + relabel. No new CLI to install. This *helps* goal #2.
- **`cliproxyapi` does NOT support Qwen or iFlow OAuth.** Its OAuth logins are:
  `claude`, `codex`, `antigravity`, `kimi`, plain Google. So the
  "Qwen + iFlow OAuth" the user picked is not wireable; **Kimi (Moonshot)** is
  the available extra OAuth provider. Qwen/iFlow remain reachable as **API key**
  via the new Generic OpenAI-compatible backend below.

## Decisions locked with user

- Antigravity: **replace Gemini in place** (keep internal `kind="gemini"` to
  avoid a DB/config migration; only display name, login flow, and labels change
  — existing accounts keep working unchanged).
- Wizard: collapse to **Setup / Login / Done**, drop config-dir confirm step.
- New providers: **OpenRouter (API key)** + **Generic OpenAI-compatible** +
  one OAuth provider. (OAuth provider corrected from Qwen/iFlow → **Kimi**,
  pending user nod.)

---

## Part 1 — Antigravity (replace Gemini in place)

Keep `kind="gemini"` internally (no migration). Changes:

- **`cliproxy/manager.py`** `flag_map`: `"gemini": "--login"` →
  `"gemini": "-antigravity-login"`. (One line. This is the substantive change —
  Antigravity OAuth instead of plain Google-account login.)
- **`backends/gemini.py`** metadata: `display_name` "Gemini" → "Antigravity",
  rewrite the `cli_browser` flow `display_name`/`description` to Antigravity
  wording. Keep the `api_key` flow (Google AI Studio key still valid — labelled
  "Gemini API key").
- **`install/backend_cli.py`**: drop the `@google/gemini-cli` install strategy
  for this kind (Antigravity needs no terminal CLI). The wizard's CLI step
  becomes a non-blocking note (see Part 2), so no install is required.
- **Wizard labels**: `DEFAULT_CONFIG_DIR_MAP.gemini` and the tour copy stay
  functionally the same; only user-visible "Gemini" strings → "Antigravity".

Skipped: renaming the `kind` string everywhere. It's an internal id; renaming
touches DB rows, config dirs, env vars, the cliproxy auth filename
(`gemini-<email>.json`) for zero user benefit. `// ponytail: kind stays
"gemini", display is "Antigravity" — rename the id only if it ever leaks to users.`

## Part 2 — 3-step wizard + drop config-dir confirm

Today the step indicator shows up to 5 dots (`subscription, cli, login, [proxy],
plan`). Collapse the **displayed** indicator to 3 phases; keep internal
`currentStep` navigation (lowest-risk).

- Add a `DISPLAY_PHASES` map: `subscription,cli → "Setup"`;
  `login,proxy → "Login"`; `plan → "Finish"`. Render 3 dots from the deduped
  phase list; the active dot = the phase of `currentStep`.
- **Drop the config-dir confirm UI** on the cli step (the `configPath` input,
  "Customize path", and `accountWizard.tour.cli.path.*`). `configPath` keeps
  auto-generating silently (logic already exists in `suggestConfigPath`); an
  optional "Advanced" `<details>` toggle exposes it for power users. Server still
  auto-creates the dir on login (unchanged).
- The cli step shrinks to a one-line CLI-detected badge (non-blocking). For
  Antigravity / keyless providers there's nothing to install, so the badge reads
  "No CLI required".

Skipped: rewriting the wizard into literally 3 screens/components. Regrouping the
indicator + deleting the config-dir block delivers the mobile fix with a fraction
of the churn. `// ponytail: 3 display phases over 5 internal steps; split into 3
components only if the steps ever need independent reuse.`

## Part 3 — New providers

All register the same way: instantiate in `apps/playground/server.py` backends
tuple, export from `backends/__init__.py`, add a `_models_fallback` entry, and
(for keyless ones) a no-op/guard in `install/backend_cli.py`. Wizard hardcoded
maps (`DEFAULT_CONFIG_DIR_MAP`, `apiKeyEnv` envMap, `PROXY_SUPPORTED_KINDS`) get
entries as needed.

### 3a. OpenRouter (`kind="openrouter"`, API key only)

Near-trivial: `backends/opencode.py` *already* talks to `openrouter.ai` for
chat + list_models. New `openrouter.py` = OpenCode's api_key session + chat +
list_models, **minus** the `cli_browser` flow and CLI install. `install_check`
is a no-op (no binary). `_env` sets `OPENROUTER_API_KEY`.

### 3b. Generic OpenAI-compatible (`kind="openai_compat"`, API key + base URL)

One backend that covers Qwen, iFlow, Together, Groq, DeepSeek, Mistral, etc.
- Login flow `api_key` with **two** inputs: `api_key` (secret) + `base_url`
  (text, e.g. `https://dashscope.aliyuncs.com/compatible-mode/v1`).
- `base_url` stored in the account's `config` dict; `chat()`/`list_models()`
  read it and hit `{base_url}/chat/completions` and `{base_url}/models`
  (OpenAI-shaped, same parsing as opencode).
- This is the only new backend with genuinely new modeling (config-stored
  base_url threaded into chat).

### 3c. Kimi / Moonshot (`kind="kimi"`, OAuth via cliproxy)

- Add `"kimi": "-kimi-login"` to the cliproxy `flag_map`.
- New `kimi.py` modeled on gemini's `_GeminiCliProxySession` (cliproxy OAuth
  delegation) + `_chat_via_cliproxy` for chat; `validate` via
  `cliproxy_list_models("kimi")`. No api_key flow initially.
- Add `kimi` to `PROXY_SUPPORTED_KINDS` in the wizard.

Skipped this round: separate Qwen/iFlow OAuth backends (not supported by
cliproxy); they're covered by 3b. Bedrock/Vertex/etc. — not requested.

---

## Testing

- `cliproxy/manager.py`: unit-assert `flag_map["gemini"] == "-antigravity-login"`
  and `flag_map["kimi"] == "-kimi-login"`.
- `openai_compat`: one `test_*` asserting `chat()` posts to the configured
  `base_url` (httpx mock) — the money/routing path.
- Wizard: extend the existing step test to assert the indicator renders exactly
  3 phases and the config-path input is absent by default.
- OpenRouter: reuse opencode's chat test shape (httpx mock on openrouter.ai).

## Out of scope

- Renaming the internal `gemini` kind.
- Qwen/iFlow OAuth (cliproxy lacks it).
- New install strategies for keyless backends beyond a guard.
