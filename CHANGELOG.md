# Changelog

All notable changes to ai-accounts packages in this monorepo.

## 0.4.6 — 2026-07-11

npm-installable council CLI and opt-in account keep-alive.

### Added

- **`@ai-accounts/council`** (new npm package). `npm install -g @ai-accounts/council` provides the `aia-council` binary — a zero-dependency Node port (Node ≥ 18.17, global fetch + `node:util` parseArgs) with the identical contract to the Python CLI: same flags/env vars, progress on stderr, decision JSON on stdout, same exit codes and mid-stream-drop handling. Verified end-to-end against a live server side-by-side with the Python CLI. Claude Code skill users now need no Python on the client machine.
- **Keep-alive loop** (`ai-accounts-litestar`). `AiAccountsConfig.keep_alive_interval_seconds` starts a background loop that sends `AccountService.keep_alive`'s 1-token probe through every READY account each interval, so idle OAuth access tokens keep refreshing (cheapest model per kind — Haiku for Claude). ERROR accounts are retried too: a clean ping promotes them back to READY, so the loop doubles as recovery after e.g. a CLIProxyAPI outage. Library default is `None` (embedders opt in — background token spend shouldn't appear on upgrade); the **playground defaults it ON at 2 h** (`AIA_KEEP_ALIVE_SECONDS` to tune, `0` to disable). This activates the previously dormant `keep_alive()` service method.

## 0.4.5 — 2026-07-11

Adds **council mode**: delegate a decision to a debating panel of your AI accounts — say "council it" in a Claude Code session and the verdict comes back with rationale, dissent, and a vote tally. Adapted from [karpathy/llm-council](https://github.com/karpathy/llm-council) for decision-making.

### Added

- **`CouncilService`** (`ai-accounts-core`, `services/council.py`). Given a question + 2–10 options + context, five role-lensed members (pragmatist, architect, risk-analyst, user-advocate, contrarian) are seated round-robin over READY accounts (one account backs all roles; several accounts share them). Stages: independent positions with `VOTE: n` → anonymized rebuttal round(s) (member accounts/providers are never revealed to each other) → tally → an impartial chairman issues a strict-JSON decision `{choice, confidence, rationale, dissent}`, with a majority-vote fallback and declared tie-breaking. Seating applies the scheduler's rate-limit criteria (skips cooling-down / ≥95%-used accounts) and records `mark_used`; rounds are hard-capped (≤5) at both the API edge and the service.
- **`POST /api/v1/council`** (`ai-accounts-litestar`, `routes/council.py`). One-shot SSE stream of `CouncilEvent`s (`council_start`, `position`, `rebuttal`, `member_error`, `votes`, `decision`/`council_error`) with heartbeats; request bounds enforced via msgspec constraints.
- **`aia-council` CLI** (`ai-accounts-core`, `cli_council.py` — the repo's first console script). Streams deliberation progress to stderr, prints the decision JSON to stdout; `--json` for machine consumption; exit 0 decision / 1 failure / 2 usage; `AIA_URL` + `AI_ACCOUNTS_API_KEY` env support; a mid-stream drop after the decision arrived still exits 0 with the decision.
- **Claude Code plugin `council`** (`claude-plugin/`, marketplace at `.claude-plugin/marketplace.json`). Install with `/plugin marketplace add ca1773130n/ai-accounts` → `/plugin install council@ai-accounts` (or copy the skill dir). Saying "council it" on a pending decision makes Claude assemble the question/options/context brief, run `aia-council`, and proceed with the council's verdict.

## 0.4.4 — 2026-07-10

Auto-discovery now recognizes self-hosted Claude Code setups.

### Added

- **Discovery/import of self-hosted Claude Code dirs** (`ai-accounts-core`, `services/discovery.py` + `services/accounts.py`). The "detect existing logins" scan reads each `~/.claude*` candidate's `settings.json`; a dir carrying `env.ANTHROPIC_BASE_URL` surfaces as a `claude_custom` candidate, and one-click import bakes the base URL (normalized), a plaintext `env` API key/token, the model (`env.ANTHROPIC_MODEL` or top-level `model`, else a `default` placeholder), and the config dir into the credential — so the imported account chats and spawns the CLI against the self-hosted endpoint. Keys behind `apiKeyHelper` and missing model lists are completed via the existing AccountReauth flow. Hosts that don't register `ClaudeCustomBackend` keep the old behavior.

### Fixed

- Such dirs previously imported as **plain `claude` accounts that silently chatted against the wrong endpoint** (CLIProxyAPI / api.anthropic.com instead of the configured base URL); the kind classification above closes that hole.

## 0.4.3 — 2026-07-07

Surfaces vault-key mismatches as account status instead of opaque 500s.

### Fixed

- **Credential decrypt failures now surface as account status** (`ai-accounts-core`, `services/accounts.py` + `ai-accounts-litestar`, `errors.py`). When a stored credential can't be decrypted — almost always the server running with a different `AI_ACCOUNTS_VAULT_KEY` than the one that encrypted it — `validate()`/`list_models()` previously escaped as raw 500 tracebacks and the chat panel showed a misleading "No models available for <kind>" while the account card still said READY. Now the account flips to ERROR with a human-readable `last_error` explaining the vault key mismatch and how to fix it, and the API returns a structured `503 credential_unreadable`.

## 0.4.2 — 2026-07-06

Adds the **self-hosted Claude Code backend** (`claude_custom`): register any Anthropic-compatible endpoint (LiteLLM, claude-code-router, a corporate gateway) as a transparent Claude Code account — chat-able from the playground panel in single/all/compound modes — and fixes a discovery bug where one kind's home-dir glob could break another kind's account.

### Added

- **`claude_custom` backend** (`ai-accounts-core`, `backends/claude_custom.py`). Login is a prompt flow (base URL → API-key-or-keyless menu → manual model list `id` or `id=Display Name`, first entry = default model); everything chat/pty need — base URL, optional key, model list, custom `CLAUDE_CONFIG_DIR` — is baked into the encrypted credential JSON, the only channel that reaches every code path. `chat()` streams Anthropic `/v1/messages` SSE against the custom base URL (both `x-api-key` and `Bearer` sent; keyless supported; in-band `{"type":"error"}` events surface as chat errors). `pty()` spawns the real `claude` CLI with `ANTHROPIC_BASE_URL`, `ANTHROPIC_MODEL`, and the account's config dir, stripping ambient `ANTHROPIC_API_KEY`/`ANTHROPIC_AUTH_TOKEN` so the operator's real Anthropic credentials never reach a third-party host. `validate()` probes `{base_url}/v1/models` with a 1-token `/v1/messages` fallback.
- **Frontend kind maps** (`@ai-accounts/vue-styled`) for `claude_custom` — "Claude (self-hosted)" labels/colors, `~/.custom-claude` default config dir, and no-CLI wizard badge. The account wizard, re-auth, and chat panel pick the new kind up automatically from backend metadata.

### Fixed

- **Discovery no longer syncs status across kinds** (`ai-accounts-core`, `services/accounts.py`). Claude's `.claude*` home glob could match another kind's `config_path` (e.g. a `claude_custom` dir), probe it as an OAuth Claude account, and flip the healthy row READY → ERROR, knocking it out of the scheduler. `discover_existing` now ignores candidates whose probed kind differs from the owning row's kind.

## 0.4.1 — 2026-06-30

Adds **`AccountReauth`** (`@ai-accounts/vue-styled`): a per-account "Re-auth" control that re-runs the backend's login flow against the existing account id, so an expired credential (lapsed OAuth token, rotated key) is refreshed in place without removing + re-adding. Reuses `LoginStream`; resolves login flows from the backend registry (flow chooser when a backend offers more than one). Wired into the playground account blocks. Playground web port is now env-driven via `AIA_WEB_PORT`.

## 0.4.0 — 2026-06-28

Completes the Gemini → **Antigravity** migration (the kind is now genuinely `antigravity`, not an alias), and adds five backends plus keyless local-LLM support. Also brings CI to green and lands the deferred code-review follow-ups.

### Added

- **DeepSeek backend** (`ai-accounts-core`, `backends/deepseek.py`). API-key backend over DeepSeek's OpenAI-compatible API (`https://api.deepseek.com/v1`). Keyless install (no CLI). Static fallback models: DeepSeek V4 Flash / Pro.
- **Qwen / DashScope as an OpenAI-compatible preset** (`ai-accounts-core`, `backends/openai_compat.py`). Qwen is no longer a standalone backend — it is now selectable from the `openai_compat` preset menu (China / International), with the API-key prompt required for these cloud endpoints.
- **Keyless local-LLM support in the OpenAI-compatible backend** (`ai-accounts-core`, `backends/openai_compat.py`). `validate()` now succeeds with an empty API key (no `Authorization` header sent) and falls back to probing `/chat/completions` when `/models` is absent. The login flow opens with a preset menu — **Ollama** (:11434), **LM Studio** (:1234), **vLLM** (:8000), **llama.cpp** (:8080), **oobabooga** (:5000), or Custom — and the API-key prompt is optional.
- **Goose backend** (`ai-accounts-core`, `backends/goose.py`). PTY-primary CLI agent; `chat()` parses `goose run … --output-format stream-json`. Per-account isolation via `GOOSE_PATH_ROOT`, with `GOOSE_DISABLE_KEYRING=true` and provider key env (anthropic/openai/openrouter).
- **Aider backend** (`ai-accounts-core`, `backends/aider.py`). PTY-primary CLI agent; isolates host config by pinning `HOME` to the per-account isolation dir. `chat()` is a best-effort one-shot via `aider --message`.
- **Crush backend** (`ai-accounts-core`, `backends/crush.py`). PTY-only CLI agent; login writes an isolated `crush.json`, `_env` sets `CRUSH_GLOBAL_CONFIG`/`CRUSH_GLOBAL_DATA`. `chat()` returns an error event (TUI-only, no headless).
- **SQLite schema v3 data migration** (`ai-accounts-core`, `adapters/storage_sqlite/migrations.py`). Rewrites existing `backends` rows from `kind='gemini'` to `kind='antigravity'` so accounts created before this release keep working.

### Changed

- **Gemini backend fully renamed to Antigravity** (`ai-accounts-core`, `backends/gemini.py` → `backends/antigravity.py`). `GeminiBackend` → `AntigravityBackend`, kind `"gemini"` → `"antigravity"`, isolation env `GEMINI_HOME` → `ANTIGRAVITY_HOME`, with a best-effort one-time config-dir move `~/.gemini` → `~/.antigravity`. The rename propagates through `BackendKind`, the cliproxy flag/compat maps, the static model fallbacks, the playground server registry, and all `@ai-accounts/vue-styled` kind maps (labels, colours, CSS vars, wizard config-dir/api-key maps).
- **Frontend backend maps extended** (`@ai-accounts/vue-styled`) for `deepseek`, `goose`, `aider`, `crush` — display names, selector labels, response colours, onboarding list, and wizard config-dir / api-key-env / no-CLI maps.

### Fixed

- **CI is green** (`.github/workflows/ci.yml`). Fixed pre-existing pipeline bugs: removed the pnpm `packageManager` / `setup-node` version clash, switched the Python install to `uv sync --all-extras --all-packages`, run the package build before type-checking, and install `just` (`extractions/setup-just`) in the runner. Added a flat-config `eslint.config.mjs` so the lint job resolves.

### Review follow-ups

These land the deferred items from the backend-roster code review:

- **Antigravity passes the API key as an `x-goog-api-key` header** (`ai-accounts-core`, `backends/antigravity.py`) across `validate()`, `list_models()`, and `chat()`, matching Google's Generative Language API.
- **CLIProxyAPI log/config files use `tempfile.mkstemp`** (`ai-accounts-core`, `cliproxy/manager.py`) — atomic creation with no TOCTOU window, replacing the predictable temp path.
- **Goose installer pinned** (`ai-accounts-core`, `install/backend_cli.py`) to a known-good release (`v1.39.0`) instead of tracking the latest install script.
- **OpenAI-compatible login skips the API-key prompt for keyless presets** and surfaces a placeholder model when `/models` is absent (`ai-accounts-core`, `backends/openai_compat.py`).
- **Agent backends surface the configured model** (`ai-accounts-core`, `backends/{goose,aider,crush}.py`) from `list_models()` so the UI reflects the active model even without a live models endpoint.
- **Frontend label maps** (`@ai-accounts/vue-styled`) rounded out for the new backend kinds.

## 0.3.17 — 2026-06-20

Google deprecated the Gemini CLI in favour of **Antigravity**; the Gemini account now authenticates through Antigravity. The add-account wizard collapses to three mobile-friendly steps, and three new provider backends ship.

### Added

- **OpenRouter backend** (`ai-accounts-core`, `backends/openrouter.py`). API-key backend over OpenRouter's OpenAI-compatible `/api/v1`. Keyless (no CLI to install). (#30)
- **OpenAI-compatible (Custom) backend** (`ai-accounts-core`, `backends/openai_compat.py`). Takes a base URL + API key (stored together as a JSON credential) and talks to any `/v1/chat/completions` + `/v1/models` endpoint — covers Qwen, iFlow, Together, Groq, DeepSeek, Mistral, etc. from a single backend. (#30)
- **Kimi (Moonshot) backend** (`ai-accounts-core`, `backends/kimi.py`). OAuth via CLIProxyAPI's `-kimi-login`; `kimi → moonshot` added to the cliproxy `owned_by` compat map. (#30)

### Changed

- **Gemini account now uses Antigravity OAuth** (`ai-accounts-core`, `cliproxy/manager.py`, `backends/gemini.py`). The cliproxy login flag moves from the bare Google `--login` to `-antigravity-login`, and the backend presents as **Antigravity**. The internal kind stays `"gemini"` so existing accounts keep working with no migration. The `@google/gemini-cli` install step is dropped (Antigravity needs no terminal CLI); `GeminiBackend.detect()` now reports keyless. (#30)
- **Add-account wizard collapses to 3 steps** (`@ai-accounts/vue-styled`, `AccountWizard.vue`). The step indicator now shows **Setup / Login / Finish** instead of up to five dots — fixes the layout breaking on narrow-mobile widths. The config-directory confirm step is removed; the path is auto-generated and tucked behind an "Advanced" toggle. Keyless backends show a "No CLI required" badge. (#30)

## 0.3.16 — 2026-06-14

Idle-account keep-alive, per-message backend/model labelling in the chat UI, and login-flow reliability fixes.

### Added

- **`AccountService.keep_alive()`** (`ai-accounts-core`, `services/accounts.py`). Refreshes idle OAuth tokens so long-lived accounts don't lapse between uses. (fe5c848)
- **Chat bubbles labelled by answering backend + model** (`@ai-accounts/vue-styled`). Each response shows which backend/model produced it. (1aa4cb7)

### Changed

- **Claude keep-alive pings use Haiku** to avoid burning premium-model quota on liveness checks. (3238914)

### Fixed

- **cliproxy login prints the OAuth URL reliably** — provide a `config.yaml` and pass `-no-browser` so the binary emits the URL instead of dying on missing config / trying to open a browser on a headless host. (b7714e7)
- **Login flow**: wake the code prompt on eager paste (post-code hang), add a post-OAuth completion watchdog that fails with CLI output instead of hanging, and require a selection cursor before treating numbered lines as a menu. (6d3e601, c026fbf, d600c43)

## 0.3.15 — 2026-06-07

Discovery no longer kills valid codex backends: free login-status probe + timeout-tolerant status sync. Claude cli_browser login opens the paste-code page, not the CLI's private localhost callback.

### Fixed

- **Claude cli_browser login: rewrite the CLI's localhost-callback OAuth URL to the paste-code page** (`ai-accounts-core`, `backends/claude.py`, `login/interactive.py`). `claude /login` hands `open` a URL whose `redirect_uri` targets the CLI's *own* random-port localhost callback server (`http://localhost:NNNNN/callback`). After 0.3.14 made the captured (browser-opened) URL win, the operator's browser landed on that localhost page — unreachable when the sidecar is on another host, and the wrong flow for the paste-code wizard even locally (the success line then stays buffered behind the TUI redraw gate and the wizard never completes). `run_interactive_cli_login` now accepts an optional `captured_url_transform`; the Claude backend supplies one that rewrites `redirect_uri` to `https://platform.claude.com/oauth/code/callback`, reproducing the paste-variant URL the CLI itself prints (same client_id, PKCE challenge, and state) so the pasted code exchanges cleanly. (0b548ac)
- **Codex discovery probe: `codex login status` instead of a paid model call** (`ai-accounts-core`, `services/discovery.py`). The old `codex exec hello` probe was a real model call under the 12s probe_timeout — codex routinely takes longer, so valid logins probed as logged-out, and every Discover click burned upstream tokens. The new probe is free and instant; since `codex login status` exits 0 even when logged out, the runner inspects the status text on BOTH streams (codex 0.121 prints to stdout, 0.128+ to stderr), mirroring `backends/codex.py validate()`. (6c61c44)
- **`discover_existing()` no longer downgrades READY backends on probe timeout** (`ai-accounts-core`, `services/accounts.py`). A slow CLI is no evidence the login is dead, but the status sync treated any probe failure as authoritative and flipped already-imported backends READY → ERROR — knocking them out of `scheduler.pick()` until the next `validate()` (downstream symptom: "No ai-accounts backend available" with a perfectly valid account). Timeouts are now inconclusive: the READY row is kept and the discovered config surfaces as logged-in with the timeout noted in `error`. Definitive not-logged-in results still downgrade. (6c61c44)

## 0.3.14 — 2026-06-07

Login-wizard reliability: the cli_browser flow no longer hangs on "Preparing sign-in…" when the OAuth URL detection misses, plus keychain-sweep fixes.

### Fixed

- **cli_browser login: surface the OAuth URL reliably; fail fast instead of hanging** (`ai-accounts-core`, `login/interactive.py`). Three compounding defects left the wizard's "Preparing sign-in…" spinner up forever after answering the login-method menu: (1) the fake-browser capture file — the only channel carrying the *complete* OAuth URL — was polled only during idle ticks, which Claude 2.1.x's "Opening browser…" spinner animation starves; it is now polled on every loop iteration. (2) The TUI paints the URL with cursor-positioning escapes that `strip_ansi` renders as spaces *inside* the URL (`https://cl ud .com/…`), so the permissive generic regex emitted bare fragments like `https://cl`; generic matches must now look like a complete URL (dotted host + path). (3) A new url-wait watchdog (90 s, disabled once a URL is emitted, reset on menu/text answers) fails the session with the recent CLI output instead of spinning silently when every detector misses. (da25300)
- **Keychain dump parser drops acct-less items** (`ai-accounts-core`, `backends/claude.py`). The 0.3.13-era disambiguating parser only emitted `(service, account)` pairs when an `acct` attribute was present — entries without one parsed to nothing and the keychain looked empty, regressing the corrupted-entry sweep. Acct-less items are now flushed as `(service, None)` at item boundaries, matching the documented contract. (e97cca1)
- **Disambiguate duplicate Claude Code credential entries** (`ai-accounts-core`). `security find-generic-password -s SVC` returns the *first* match when two genp items share a service name (e.g. an MCP-plugin OAuth orphan next to the real account), making discovery falsely report "not signed in". The dump parser now yields svce+acct pairs so lookups are account-scoped via `-a`, with an `expiresAt` check and an overall `asyncio.wait_for` budget; the keychain quick-check also short-circuits the token-costing `claude -p hello` probe. (fb576d8)
- **Two real bugs surfaced by ruff** — an F821 undefined name and a B023 loop-variable capture. (3a7dc1d)
- **`just bump` re-links editable workspace packages** so the release pipeline's `uv run pytest` doesn't fail collection with stale dist-info. (e8ea975)

### Changed

- **Lint pass** — `ruff format` + safe auto-fixes across the Python packages, no behavior change. (70ac8c0)
- **argv smoke test skips on a hung CLI** — a binary that can't answer `--version`/`--help` within 10 s is a broken local install, not subcommand drift; treat it like "not on PATH". (ee8d89c)

## 0.3.13 — 2026-05-19

Codebase review pass: dedup the four CLI backends, unify the chat wire shape, externalize the cliproxyapi compatibility table, and add the e2e SSE test that would have caught the 0.3.9/0.3.10/0.3.12 chat regressions.

### Added

- **Live model cache** (`ai-accounts-core`, `backends/_models_fallback.py`). `cliproxy_list_models()` now persists every successful `/v1/models` response to `~/.ai-accounts/models_cache.json` (override via `AI_ACCOUNTS_CACHE_DIR`). Offline / cliproxy-stopped calls serve the cached snapshot before falling through to the version-pinned static set — eliminates the empty-dropdown UX when the wizard added an account through cliproxy but the proxy isn't running on the next launch. (1f33a18)
- **`CliBackendBase` mixin** (`ai-accounts-core`, `backends/_base.py`). `ClaudeBackend`, `CodexBackend`, `GeminiBackend`, `OpenCodeBackend` now inherit shared `_run()` + `detect()` instead of carrying four byte-identical copies. ~100 LOC of duplication removed; future per-CLI quirks (validate, list_models, chat) stay in the subclass where they belong.
- **Versioned cliproxyapi compat table** (`ai-accounts-core`, `cliproxy/cliproxy_compat.toml` + `cliproxy/_compat.py`). The device-code regex, SSRF callback allowlists (ports, paths, hosts), and the kind→`owned_by` provider map are loaded from a TOML data file. Future cliproxyapi releases that shift a port or callback prefix become a one-line diff instead of edits across `manager.py`. Falls back to the previous hardcoded defaults on any parse error.
- **End-to-end SSE wire-shape test** (`ai-accounts-litestar`, `tests/test_chat_send_e2e.py`). Drives `POST /api/v1/chat/send` through `AsyncTestClient` for `mode=single`, `mode=all`, and `mode=compound`, asserting the dict shape of every SSE event (`ChatDelta.payload`, `AllModeEvent.text`, `CompoundEvent` synthesis frames, monotonic `_seq`). The three chat regressions in 0.3.9/0.3.10/0.3.12 escaped because no test asserted the byte-level wire shape for fan-out modes; this closes that gap.

### Changed

- **Unified chat wire shape on `payload`** (`ai-accounts-core`, `@ai-accounts/ts-core`, `@ai-accounts/vue-headless`). `ChatDelta.text → ChatDelta.payload` end-to-end, matching the `SmartChatEvent.token` shape `useSmartChat.dispatch` already consumes. The text→payload rename shim added to `routes/chat_send.py` in 0.3.9 is deleted — there is one canonical name for the field now. **Breaking** for any direct consumer of the `ChatDelta` TS type; in-tree call sites (`useConversation`) are updated.
- **Static model fallback consolidated** (`ai-accounts-core`). Per-backend hardcoded `_STATIC` lists in `claude.py` and `codex.py` moved into `backends/_models_fallback.py`. Each backend now calls `fallback(provider)` instead of duplicating the curated list — adding/removing a model is a one-file edit. Resolves the drift class that needed three separate fixes across 0.3.9/0.3.10/0.3.12.
- **Core test layout** — 12 flat tests under `packages/core/tests/` moved into matching subdirs (`backends/`, `domain/`, `services/`, `storage/`) so navigation mirrors the source tree. Per-test `AI_ACCOUNTS_CACHE_DIR` isolation (new `conftest.py` in `core` + `litestar`) so a real cliproxyapi on the dev machine can't shadow static-fallback assertions.

### Documentation

- **README — opencode in the packages table** and a new **Known Limitations** section that promotes the macOS Claude keychain isolation constraint from inline source comments to a place anyone reading the README before install will see it. The constraint (keychain entries are not scoped by `CLAUDE_CONFIG_DIR`, so a second OAuth `/login` on darwin replaces the first) is tracked for a future release; the wizard already shows a consent banner before the 2nd Claude add.
- **`docs/superpowers/REVIEW-2026-05-19.md`** — the source review that produced this release. Lists all 8 findings with effort/impact and the rationale for each.

## 0.3.12 — 2026-05-17

Auto-discovery of existing CLI logins, chat-bubble safety + rendering fixes, OAuth probe fallbacks, and release-pipeline reliability.

### Added

- **Auto-detect existing CLI logins** (`ai-accounts-core`, `ai-accounts-litestar`, `@ai-accounts/ts-core`, `apps/playground`). Globs `~/.claude*`, `~/.codex*`, `~/.gemini*`, `~/.opencode*` and runs a real-prompt liveness probe (`claude -p hello`, `codex exec --skip-git-repo-check hello`, `gemini -p hello`, `opencode run hello`) against each in parallel. One-click import via `POST /api/v1/discovery/import` reuses the existing `config_path` so no re-auth is needed. Already-imported accounts are also re-probed — their backend status syncs `READY ↔ ERROR` to the probe result, so a stale "ready" row (token expired, manual logout) surfaces immediately on the next Auto-detect. (303e559, da80415)
- **`AiChatPanelManaged` CLI runner toggle** (`@ai-accounts/vue-styled`) — host components can expose a managed CLI-runner pane. (4ee9ce5, #27)

### Fixed

- **Security: DOMPurify-sanitize `marked.parse` output in `ChatBubble`** (`@ai-accounts/vue-styled`). Untrusted markdown from chat completions can contain HTML that marked happily passes through; DOMPurify scrubs script/event-handler payloads before insertion. (43bf725)
- **Codex local cache + claude keychain OAuth probe + direct `/v1/models`** — three fixes for the model-list surface that unblock the codex CLI's account-aware live list (v0.7.12), the claude OAuth token stored in keychain / `.credentials.json` (v0.7.11), and the direct `/v1/models` HTTP call with refreshed static fallback (v0.7.10). (b8b1c4a, 62515d9, d364295)
- **Chat: decode gzipped proxy error bodies** + soften "model not supported" rendering so error messages aren't binary blobs. (baa2acd)
- **Chat: `AiChatPanel` fills parent width** instead of shrinking to content. (1db698b)
- **Chat: restore list indent on rendered markdown** (regression from the marked upgrade). (2b705b0)
- **`ChatBubble`: render markdown headings/blockquotes/tables/links visibly** — vue-styled was filtering them out. (#29, b585dc3)
- **`ChatBubble`: Invalid Date guard** so a malformed timestamp doesn't leak the string into the UI. (#28, 11a3a41)
- **Wizard method-picker default-flow click no longer no-ops** when the user clicks the already-active flow. (bf515d1)
- **Release pipeline determinism**: `just release` now builds before testing (JS workspace tests need `ts-core/dist` to exist) and tests mock all four codex `list_models` sources so a real `~/.codex/models_cache.json` on the dev machine can't shadow the static-set assertion. (4221b59, f58c668)

### Documentation

- This entry. Per-package CHANGELOGs (`ts-core`, `vue-headless`, `vue-styled`) get matching summaries.

### Chore

- `.gitignore` covers context-mode plugin artefacts, root-level `*.dylib`, runtime caches (`tsx-*/`, `pytest-of-*/`, `uv-*.lock`), and leaked `aia-cliproxy-*/` temp dirs.
- `pnpm-lock.yaml` records the `dompurify@3.4.2` entry from 43bf725.

---

## 0.3.11 — 2026-05-05

Gemini subscription login, wizard method picker, and login-flow correctness.

### Added

- **Gemini subscription login via `cliproxyapi --login`** (`ai-accounts-core`, `@ai-accounts/vue-styled`). New `cli_browser` flow for `GeminiBackend` — delegates to cliproxyapi's Google OAuth handshake (Gemini Code Assist / Pro / Ultra subscriptions). `cliproxy/manager.py` flag map corrected: `gemini → --login` (the bare flag — cliproxy has no `--gemini-login` subcommand). (08e18a8)
- **Wizard method picker** for backends advertising >1 login flow (`@ai-accounts/vue-styled`, `AccountWizard.vue`). Shows a card listing each available flow with description so the user picks explicitly. A compact mid-flow switcher lets them bail to a different flow without leaving the wizard. (e3a00b6, 79f00a4)
- **`useLoginSession.write_eager(text)`** (`@ai-accounts/vue-headless`, `@ai-accounts/ts-core`) — direct PTY write fallback when the CLI never emits its prompt. (carried in from work prior to v0.3.10 documented in earlier entries)
- **`useLoginSession.reset()`** for re-opening the wizard against the same backend.
- **`just playground` / `playground-api` / `playground-build`** recipes (`justfile`). Pre-flight kill of any stale listeners on the API port and Vite's 6173 so the next launch always succeeds. Clear error if you accidentally pass 6173 as the API port. (e50e3b7, 26a490e, 950c5a3)

### Fixed

- **Wizard advanced past login on bogus credentials** (`ai-accounts-litestar`, `routes/login.py`). `LoginComplete` was emitted to the SSE before `validate()` ran, so the wizard auto-advanced before the backend was actually verified. The route now holds `LoginComplete` until `store_credential` + `validate` succeed; emits a failed event otherwise. (50dbfdf)
- **Gemini default to api_key** (`ai-accounts-core`, `backends/gemini.py`). cliproxyapi's hardcoded Google OAuth client hits Google's "first-party native app" consent gate that frequently hangs — defaulting to api_key gives users a working path; cli_browser stays available via the picker for those whose OAuth client isn't blocked. (18346b0)
- **Gemini cli_browser prompt explains the localhost-redirect hang** — sign-in completes but the browser tries to load `localhost:8085/oauth2callback` (unreachable when the playground is on a remote host); the user copies the URL from the address bar. (91decf8)
- **Login-flow polish** (`@ai-accounts/vue-styled`, `LoginStream.vue`): hide eager paste form for device-code flows (codex), drop the over-eager prompt watcher that broke gemini's textPrompt-only flow, stop the spinner showing after intermediate menu/prompt picks, make the verifying state escapable, show CLI stdout for debugging, surface respond errors. (03380ac, b4b1d56, 9432614, 1863335)
- **Wizard: surface login-start failures instead of `console.warn`** — was leaving the wizard on a spinner forever when `/begin` failed. (d6a6d79)
- **`justfile`: shell-quoting glitch in release verify line** — was printing the just process-id instead of `npm view` output. (aa43e05)

---

## 0.3.10 — 2026-05-03

Back-migrated Agented chat components, live model discovery via cliproxyapi, and orchestrator error handling.

### Added

- **Back-migrated chat components from Agented** (`@ai-accounts/vue-styled`):
  - `AiChatPanelManaged` — caller-managed sibling of `AiChatPanel` (host owns the session ref). (e83b170)
  - `AiChatSelector` standalone component for cross-backend account/model selection. (cb3d6c9)
  - `ChatModeSelector` standalone component (`single`/`all`/`compound`). (36075f6)
  - Upgraded `AllModeResponses`, `CompoundSynthesis`, `ProcessGroup`, `MessageActions`, and `ChatBubble` with Agented features (back-migrated from MessageBubble). (7e40958, 0c5fc63, 29a4c30, a126858, dedcc9f)
- **Live model discovery from CLIProxyAPI when registered** (`ai-accounts-core`, claude/codex/gemini backends). When cliproxy is running and an account is registered through it, `list_models()` queries cliproxyapi's live `/v1/models` instead of returning the static fallback — eliminates the drift class where a curated list contains a model name cliproxy doesn't recognize (502 "unknown provider"). (f2a543f)

### Fixed

- **Chat: surface cliproxy error body to UI** (`ai-accounts-core`, `backends/_cliproxy_chat.py`). Was emitting generic `"Proxy error 502"`; now parses the OpenAI-style `{"error":{"message":...}}` body and includes the detail in `ChatStreamEvent.payload`. (b4d2c78)
- **Chat orchestrator: drop `model="auto"` fallback** — when `list_models()` returned empty or threw, the orchestrator was posting `model="auto"` which 502'd with "unknown provider for model auto". Now emits an explicit `backend_error` / `synthesis_error` and skips the backend. (b4d2c78)
- **`LoginStream` `showStdout=true` test prop** (`@ai-accounts/vue-styled`) — pre-existing scrollback test was never passing the prop, so `aia-terminal__output` never rendered and the assertion failed silently. (6b7b624)
- **`AiChatSelector` defaults — drop `chatMode: undefined` under exactOptionalPropertyTypes** (`@ai-accounts/vue-styled`). (e58ffa9)

### Added (justfile + tooling)

- **`just release VERSION`** — codifies the bump → test → build → tag → push → npm publish flow. Refuses dirty trees and non-main branches. (b4d2c78)
- **`just bump VERSION`** — lockstep version bump across all five packages (3 JS package.json + 2 Python pyproject.toml + 2 source `version` constants). (b4d2c78)
- **`AccountWizard` macOS Keychain warning** before the second Claude add (`@ai-accounts/vue-styled`). Claude CLI's keychain entry is global per user — adding a second account replaces the first. Warns before the user commits. (569eb15)
- **Playground env overrides** (`apps/playground/server.py`): `AIA_HOST` + `AIA_PORT`. (569eb15)
- **Tests**: 9-case suite for `cliproxy_list_models` covering filter, unreachable, malformed body, defensive defaults; orchestrator no-models paths; `/login/status` endpoint; `_chat_via_cliproxy` error parsing. (569eb15, 6f4438a)
- **README rewrite** + per-package CHANGELOG backfill for versions 0.2.2 → 0.3.9. (569eb15)

### Documentation

- `MAINTENANCE.md` and `ARCHITECTURE.md` version anchors refreshed.

---

## 0.3.9 — 2026-05-03

End-to-end fixes for the playground webui — codex device-code login, claude credential validation on macOS, multi-backend chat routing, and a polished playground app. Entries for 0.3.3 through 0.3.8 (which shipped on npm but were not entered here in real time) were backfilled from `git log` in this same release pass — see entries below.

### Added

- **Playground chat panel** (`apps/playground`) — `<AiChatPanel density="detailed">` mounted below the accounts list. Selects a ready backend automatically, lazy-loads its model list from `GET /api/v1/backends/{id}/models`, defaults `selectedModel` to the first available so the first send doesn't post `model=""`, and resets the session when the user switches backend or account (the server-side session is bound to its original `backend_id` — without reset, messages route through the old binding regardless of dropdown state).
- **Remove account** (`apps/playground`) — per-row Remove button with confirm dialog → `DELETE /api/v1/backends/{id}` → list refresh. Files under the backend's config directory are NOT deleted (documented in the confirm dialog).
- **Cliproxy device-code login flow for Codex** (`ai-accounts-core`, `cliproxy/manager.py`). `start_cliproxy_login("codex")` now spawns `cliproxyapi --codex-device-login` (was `--codex-login`). The browser-callback flow can't complete when the playground is reached over a remote URL — the OAuth provider redirects to localhost on the *user's* machine, not the playground host. Device-code emits a URL+code that works anywhere.
- **Cliproxy login completion polling** (`ai-accounts-litestar`, `routes/cliproxy.py`; `@ai-accounts/ts-core`; `@ai-accounts/vue-styled`). `POST /api/v1/cliproxy/login/begin` now returns a `session_id`, and `GET /api/v1/cliproxy/login/status?session_id=…` exposes the spawned cliproxyapi process's terminal state (`running`/`completed`/`failed`/`timeout`). The `_reap()` task drains stdout (so cliproxyapi can't block on a full pipe) and records the final state. `AccountWizard` polls every 2s after device-code is emitted and auto-advances on completion. The misleading "paste callback URL" UI is hidden in device-code mode and replaced with a "Waiting for you to enter the code…" indicator.
- **`backend_kind` + `account_label` on fan-out events** (`ai-accounts-core`, `domain/chat_events.py`, `services/chat_orchestrator.py`). `AllModeEvent` and `CompoundEvent` now carry the backend's kind and a friendly display name alongside the `bkd-…` id, so the Smart Chat panel cards can render "Claude · spatiotemporal.traveler@gmail.com" with the correct color instead of an opaque hash.
- **`BackendAccountOption` type** (`@ai-accounts/ts-core`). `BackendOption.accounts` is now `Array<{id, label}>` (was `string[]`) so the Account dropdown shows the email/display_name while emitting the backend id as `account_id`. The previously read-only Account `<select>` in `ChatControls` is now wired to `selectedAccount` + `update:selectedAccount`.
- **`useSmartChat.resetSession()`** (`@ai-accounts/vue-headless`) drops `sessionId` + visible chat state so consumers can start a fresh conversation when the user switches backend.
- **`AiAccountsClient.listModels(backendId)`** (`@ai-accounts/ts-core`) wraps `GET /api/v1/backends/{id}/models` for callers that need to populate model dropdowns per backend.
- **`AiAccountsClient.cliproxyLoginStatus(sessionId)`** for the new login-completion polling endpoint.

### Fixed

- **Codex device code length truncated** (`ai-accounts-core`, `cliproxy/manager.py`). `_DEVICE_CODE_RE` was `[A-Z0-9]{4}-?[A-Z0-9]{4}` and silently captured only the first 8 alphanumeric characters of the cliproxy 4-5 codex format (e.g. captured `FXEJ-GY37` from `FXEJ-GY37O`). The wizard showed an 8-char code while the OpenAI device page expected 9 — login always failed. Second group widened to `{4,8}`; greedy matching captures the full code while still working for Claude's 4-4 format.
- **Cliproxy `auth-dir` mismatch** (`ai-accounts-core`, `cliproxy/manager.py`). `write_cliproxy_config` created an empty `~/.cli-proxy-api/auth/` subdir and pointed `auth-dir` at it. But cliproxyapi's own login subcommands write credential files (`codex-…json`, `claude-…json`, `gemini-…json`) into the config directory itself — the server scanned an empty subdir, registered zero providers, and rejected every chat with `unknown provider for model X`. `auth-dir` now points at the config directory.
- **Claude validate broken on macOS** (`ai-accounts-core`, `backends/claude.py`). Claude CLI on macOS stores credentials in the system Keychain (service `Claude Safe Storage`, account `Claude Key`), NOT in `<isolation>/.credentials.json`. The file-probe `validate()` from 0.3.7 silently returned False on every macOS login → freshly-logged-in backends stuck in `error`. `validate()` now runs `security find-generic-password` first on darwin and accepts a 0 exit as success; falls back to the file probe for other platforms / unusual setups. **Known limitation, documented inline:** macOS Keychain entries are not scoped by `CLAUDE_CONFIG_DIR`, so multiple "isolated" claude accounts on darwin share one credential — a second login swaps out the first.
- **Static model lists out of sync with cliproxyapi** (`ai-accounts-core`). `claude.list_models()` advertised `claude-opus-4-7` first, but cliproxyapi 6.8.30 has no provider mapping for it → 502 `unknown provider for model claude-opus-4-7`. Replaced with the 10 claude models cliproxyapi 6.8.30 advertises (`claude-opus-4-6`, `claude-sonnet-4-6`, `claude-haiku-4-5-20251001`, etc.). `codex.list_models()` was shelling out to `codex models list --json` — the subcommand doesn't exist in codex 0.128.0 (same drift class as the earlier claude/gemini fixes), so the call always returned `[]`. Replaced with the 10 codex-flavored models cliproxyapi advertises (`gpt-5-codex`, `gpt-5.3-codex`, etc.).
- **Streaming responses rendered as "undefinedundefined…"** (`ai-accounts-litestar`, `routes/chat_send.py`). `ChatDelta` carries token text in `text`, but the frontend's `useSmartChat.dispatch` types `'token'` events as `{kind: 'token'; payload: string}` and reads `event.payload`. The route now copies `text → payload` at the SSE boundary for `kind in {token, error}`; All/Compound events (which already used `text`) are untouched.
- **Compound mode 401/429 from gemini provider** (`ai-accounts-core`, `services/chat_orchestrator.py`). `send_all`/`send_compound` passed `model="auto"` to each backend. cliproxyapi has no `"auto"` provider mapping, so it fell through to a default — apparently the gemini provider — and returned Google-style 401 (invalid OAuth) and 429 (RESOURCE_EXHAUSTED) from stale gemini credentials in cliproxyapi's auth dir. The orchestrator now resolves the backend's first advertised model via `list_models()` before each request; same fix applied to the synthesis call.
- **Missing CSS tokens collapsed wizard borders** (`@ai-accounts/vue-styled`, `styles/tokens.css`). The `AccountWizard` and `LoginStream` components were authored against an unprefixed token vocabulary (`--text-primary`, `--border-default`, `--accent-cyan`, …) but the library only shipped `--aia-*`-prefixed tokens. 19 tokens were undefined; 11 of them had no `var(…, fallback)` either, so rules like `border: 1px solid var(--border-default)` silently became invalid → rounded box borders, panel backgrounds, and accent chips collapsed in the popup. Added 19 component-side aliases mapping onto the existing `--aia-*` palette; consumers can override any of them in their own `:root`.
- **Chat panel posted `model=""` after backend switch** (`@ai-accounts/vue-styled`, `AiChatPanel.vue`). `selectBackend()` clears `selectedModel`. `handleSend` now lazy-loads models for the picked backend and defaults `selectedModel` to the first available before `createSession()` (was `400 "Expected str of length >= 1 at .model"`).

### Changed

- **Playground UI rewrite** (`apps/playground/src/App.vue`) — wider 960px container with proper vertical rhythm, card-style sections, per-kind colored left rail on account rows (claude/codex/gemini/opencode), pill status badges with colored dot + glow on `ready`, ellipsis-clamped names, monospace metadata chips, modal backdrop blur + click-outside-to-close, responsive breakpoint at 640px. Primary "Add account" CTA moved to the header instead of buried inside a section.

### Documentation

- This entry. Per-package `CHANGELOG.md` files still skip from `0.2.2` to `0.3.9` (changesets-flow gap); backfilling those is tracked separately. The root changelog gap from 0.3.3 to 0.3.8 was backfilled from `git log` in this same release pass — entries below.

---

## 0.3.8 — 2026-04-22

Claude CLI v2 paste-code reliability and OAuth error surfacing.
Backfilled from `git log v0.3.7..d347f2e` 2026-05-03.

### Fixed

- **Force Claude v1 `/login` REPL flow** (`ai-accounts-core`, `backends/claude.py`). Claude CLI v2 (`claude auth login --claudeai`) does not read the OAuth code from stdin, so paste-code never delivered. Pin the backend to the v1 REPL flow (which does), and after paste send a best-effort follow-up Enter to flush the v2.1 TUI's buffered "Login successful" line so the regex-driven login loop can complete. Broaden success/error regex coverage. (d347f2e)
- **`useLoginSession.reset()`** (`@ai-accounts/vue-headless`) added so the wizard's "Add another account" flow clears prior status/URL state instead of showing stale values. (d347f2e)

### Added

- **OAuth error detection in interactive PTY** (`ai-accounts-core`, `login/interactive.py`). New `_OAUTH_ERROR_RE` matches "OAuth error", "invalid grant/code/token/credentials", and HTTP 401/403/4xx in PTY output and yields `LoginFailed` instead of leaving the wizard hung waiting for a success event that would never come. (3eac129)
- **"Verifying authorization code…" spinner** (`@ai-accounts/vue-styled`, `LoginStream.vue`) during the post-submit window for both the eager-paste path and the response-path. Purple-accent CSS spinner; clears on terminal status. (3eac129)

---

## 0.3.7 — 2026-04-18

Direct PTY write fallback for paste-code, when Claude CLI v2 fails to
emit the "Paste code here" prompt at all. Backfilled from `git log
v0.3.6..v0.3.7` 2026-05-03.

### Added

- **`session.write_eager(text)`** (`ai-accounts-core`,
  `ai-accounts-litestar`, `@ai-accounts/ts-core`,
  `@ai-accounts/vue-headless`, `@ai-accounts/vue-styled`).
  Claude CLI v2 occasionally never emits the `"Paste code here if prompted >"` text prompt, leaving the user with a queued code and no way to deliver it. New `LoginSession.write_eager(text)` writes directly to the CLI's stdin, bypassing prompt detection. Wire-up: `_ClaudeCliBrowserSession.write_eager()` calls `orchestrator.write(code + "\r")`; `POST /api/v1/backends/{id}/login/write` exposes it; `client.writeEagerLogin()` and `useLoginSession.writeEager()` plumb it to the UI; `LoginStream` calls `writeEager` first and falls back to `queue + respond` on throw. (248e5aa)

---

## 0.3.6 — 2026-04-18

Eager paste-code form so users who finish OAuth before Claude CLI v2.1
emits its prompt aren't stuck staring at an empty UI. Backfilled from
`git log v0.3.5..v0.3.6` 2026-05-03.

### Added

- **Eager paste-code form in `LoginStream`** (`@ai-accounts/vue-styled`).
  Claude CLI v2.1.x prints `"Paste code here if prompted >"` ~10 seconds AFTER the OAuth URL (during the spinner while it waits for the browser callback). Users who completed OAuth in another tab returned to find only the URL, no input, and assumed the UI was broken. `LoginStream` now renders a secondary paste-code form as soon as the OAuth URL arrives. If the CLI's own `textPrompt` has already fired, the eager form is hidden. Otherwise, user-submitted codes are queued locally and auto-flushed via `props.session.respond()` once the real `textPrompt` event lands. (95d3d12)

---

## 0.3.5 — 2026-04-18

SSE parser CRLF compatibility. Backfilled from `git log v0.3.4..v0.3.5`
2026-05-03.

### Fixed

- **`parseSseLoginEvents` normalises CRLF → LF**
  (`@ai-accounts/ts-core`, `client/login-stream.ts`). Litestar's `ServerSentEvent` emits frames separated by CRLF (`\r\n\r\n`), but the parser searched only for LF (`\n\n`) and silently yielded nothing — the login wizard hung on "Starting login session…" while events were already streaming. Root cause verified via browser console instrumentation: `buffer.indexOf('\n\n')` returned `-1` against `'event: login\r\ndata: {…}\r\n\r\n'`. Fix: normalise CRLF → LF on each decoded chunk. Regression tests cover both CRLF (Litestar) and LF (other SSE emitters). (717f166)

---

## 0.3.4 — 2026-04-18

Claude CLI 2.1.112 OAuth host change. Backfilled from `git log
v0.3.3..v0.3.4` 2026-05-03.

### Fixed

- **Match `https://claude.com/*` OAuth URLs** (`ai-accounts-core`, `backends/claude.py`). Claude CLI v2.1.112 prints its OAuth URL as `https://claude.com/cai/oauth/authorize?…` (new `claude.com` host; the previous regex only matched `claude.ai`, `console.anthropic.com`, and `platform.claude.com`). On PTY output the URL never matched → `UrlPrompt` was never emitted → the wizard sat on "Starting login session…" forever. Regex extended; info logs added on URL detection (both backend regex and generic fallback) so future host changes are easier to diagnose from the sidecar log. (e0b403d)
- **`uv.lock` synced to 0.3.3** baseline. (a34df78)

---

## 0.3.3 — 2026-04-18

Login UX polish ported from Agented commit f52c55a + SSE reconnect
replay. Backfilled from `git log v0.3.2..v0.3.3` 2026-05-03.

### Added

- **UrlPrompt SSE replay to late subscribers**
  (`ai-accounts-core`, `ai-accounts-litestar`).
  Fixes the case where a login client reconnects (page refresh, network blip) AFTER the OAuth URL was emitted but BEFORE the user clicked it. Previously the reconnect got only new events and sat on a spinner. `LoginSession` now caches the last `UrlPrompt` via a new `events_with_replay()` wrapper; `/login/stream` replays the cached prompt to the new subscriber before entering the live event loop, deduping against the wrapper's first live event so the same URL isn't emitted back-to-back. In-memory per-process replay only — full multi-subscriber broadcast and persistence across backend restarts are separate architectural concerns. (704427c)
- **Account name optional in wizard** (`@ai-accounts/vue-styled`, `AccountWizard.vue`). Pre-fills the default config path (`~/.claude`, `~/.codex`, `~/.gemini`, `~/.opencode`) on mount and on backend-kind change. Blank names persist as `"default"` for DB NOT-NULL compatibility (via `resolveDisplayName`). Hint text: "(optional — leave blank to use the default config directory)". (5afb55b)
- **`forceFreshAccountPrompt()` helper** (`@ai-accounts/vue-styled`). Appends `prompt=select_account&consent` + `login_hint` to Google OAuth URLs (gemini/codex) and `prompt=login` + `login_hint` to Claude OAuth URLs. Prevents wrong-account logins when the default browser is already signed in to a different account. Exported from the package root. (5afb55b)
- **"Copy for Incognito" button + ⌘⇧N hint box in `LoginStream`** with the Cmd-Shift-N / Ctrl-Shift-N instruction. Auto-dismiss on close; "Copied!" state for 2.5s after clipboard write. (5afb55b)

### Changed

- **`AccountWizard` forwards `backendKind` + `email` to `LoginStream`** so `forceFreshAccountPrompt` can pick the right provider flavor without hard-coding. (5afb55b)

---

## 0.3.2 — 2026-04-17

Stable release rolling up all 0.3.2-alpha.1 work plus post-release audit closures.

### Added
- **Claude v2 auth** (`ai-accounts-core`, `ClaudeBackend`) — `begin_login("cli_browser")` now uses `claude auth login --claudeai --email <email>` when an `email` is configured, falling back to the v1 interactive `/login` flow otherwise. v2 uses the public `platform.claude.com/oauth/code/callback` redirect (no localhost binding), so it works on remote boxes without a paste-callback workaround. `--email` also pre-fills Google's account picker. `ClaudeBackend.metadata` advertises `email` as an optional input on the `cli_browser` flow.
- **Codex OAuth URL detection** (`ai-accounts-core`, `CodexBackend`) — `_CODEX_URL_RE` now matches both `chatgpt.com/auth/*` and `auth.openai.com/*`, so the interactive-login state machine emits `UrlPrompt` immediately for either host.
- **PTY child orphan protection** (`ai-accounts-core`) — `PR_SET_PDEATHSIG` now set in both `cli_orchestrator.os.forkpty()` and `pty/handle.os.fork()` child branches. Linux-only via `prctl`; macOS silently no-ops (accepted platform limitation). Closes **RISKS-AND-BUGS H-5**.

### Fixed
- **Gemini OAuth: `client_secret` + peek-don't-pop PKCE state** (`ai-accounts-core`). The token-exchange POST to `oauth2.googleapis.com` now includes `client_secret` (required by Google for the web-client credential type Gemini CLI uses — publicly embedded in Gemini CLI, treated as a configuration constant). `_GeminiDirectOAuthSession.events()` now retries on token-exchange failure up to 3 times, keeping the PKCE `code_verifier`/`state` alive across attempts — so a transient Google 5xx or a typo in the auth code no longer wipes PKCE state and forces a hard re-login.
- **IPv6 callback** (`ai-accounts-core`, `forward_cliproxy_callback`) — now tries `[::1]` first, then `127.0.0.1`, then `localhost`. Claude CLI v2.1.92+ binds the local callback server to IPv6 loopback on macOS with IPv6-first stacks; cliproxyapi still listens on IPv4. Trying IPv6 first and falling back preserves both paths.
- **Claude URL capture hardening** — URL regex now matches `platform.claude.com` alongside `claude.ai` / `console.anthropic.com`, so the interactive login picks up v2 OAuth URLs.
- **`AccountService.delete`: `rmtree` failures logged** (`ai-accounts-core`) — `shutil.rmtree(isolation_dir, ignore_errors=True)` replaced with a `try/except OSError` that logs a warning, so stale credential directories can no longer accumulate invisibly on permission/filesystem issues. Closes **SILENT-FAILURES H-04**.
- **`_ACTIVE_PROCS` keyed on UUID** (`ai-accounts-litestar`, `routes/cliproxy.py`) — replaced `str(id(proc))` with `uuid.uuid4().hex`. Python object-id reuse after GC can no longer overwrite a live reaper entry. Closes **RISKS-AND-BUGS L-2**.
- **cliproxy fake-browser temp dir cleanup on every exit path** (`ai-accounts-core`, `cliproxy/manager.py`) — `CliproxyLoginInfo` carries a new `fake_dir` field; the three previously-leaky error paths in `start_cliproxy_login` and the reaper `finally` in `routes/cliproxy.py` all clean it up. Extends **SILENT H-04 / M-10** closure.

### Removed
- Stale `feat/0.3.0-alpha.1`, `feat/0.3.0-alpha.2-4`, `feat/smart-chat-panel`, `feat/usage-scheduler`, `fix/claude-login-config-and-menu-ui` branches pruned on origin. No code impact; housekeeping only.

### Documentation
- `docs/superpowers/MAINTENANCE.md` refreshed to 0.3.x reality — version refs updated, obsolete "chat() / pty() raise NotImplementedError" tech-debt section removed (those shipped in 0.3.0-alpha.2/4), proper release history table, and two new operator-facing sections for the **0.3.1 auth middleware** (5.6) and **schema-migration system** (5.7).
- `docs/superpowers/RISKS-AND-BUGS.md` and `SILENT-FAILURES.md` gained "Status at 0.3.1" blocks with per-item FIXED / PARTIAL / OPEN annotations grounded in real file:line refs. 13 RISKS items now closed (up from 11 in 0.3.1); C-5 reclassified as architectural tradeoff tracked for 0.4.0; H-07 reclassified as accepted top-level-handler design.
- New plan file: `docs/superpowers/plans/2026-04-17-ai-accounts-0.3.2-alpha.1.md` documents the Agented-parity motivation, per-commit scope, and release checklist.

---

## 0.3.2-alpha.1 — 2026-04-17

Prerelease. Superseded by 0.3.2 stable above — see that entry for the full scope.

---

## 0.3.1 — 2026-04-17

Security hardening, schema-migration root-cause fix, and cleanup of issues found by an automated code review pass.

### Security
- **Auth middleware now actually enforces `config.auth`** (`ai-accounts-litestar`). Previously the configured `AuthProtocol` provider was only *checked* at startup — no middleware was installed, so every endpoint was effectively unauthenticated even with `ApiKeyAuth` configured. The new `AuthMiddleware` wraps every request (exempting `/health` and `/schema`), calls `authenticate()`, returns 401 on `None` principal, and exposes the principal via `scope["state"]["principal"]`. Production guard also now refuses to start with `auth=None`.
- **Login sessions bound to `backend_id`** (`ai-accounts-core`, `ai-accounts-litestar`). `LoginSessionRegistry.register()` now requires a `backend_id=` kwarg; `get()` takes an optional `backend_id` verifier. All login routes (`/stream`, `/respond`, `/cancel`) pass the route's `backend_id` to the registry, closing three cross-backend attach / credential-misroute paths that a leaked `session_id` could have exploited. Mismatches look like not-found to prevent probing.
- **Login auto-store/validate failures now emit an explicit SSE error frame** instead of being swallowed — clients no longer see "login complete" while the backend is actually unusable.

### Fixed
- **Real versioned schema migrations** (`ai-accounts-core`). `SqliteStorage.migrate()` previously used `CREATE TABLE IF NOT EXISTS` only, which silently left pre-existing tables with out-of-date columns when new columns were added. Pre-0.3.0 databases lacked `rate_limited_until`, `rate_limit_reason`, `last_used_at`, and `last_polled_at` on `backends`, forcing downstream consumers (notably HypePaper) to hand-roll backfill logic. New `migrations.py` module adds a versioned `MIGRATIONS` list, idempotent `ALTER TABLE` statements with duplicate-column tolerance, and a `CURRENT_VERSION=2` baseline. Fresh DBs run the baseline schema and jump to current; pre-0.3.0 DBs walk the migration list and self-heal.
- **SSE framing bugs in the TypeScript clients** (`@ai-accounts/ts-core`). `chat-stream.ts` and `smart-chat-stream.ts` split event frames on `\n\n` only, dropped events on servers emitting CRLF, parsed each `data:` line independently (losing multi-line payloads), and never flushed the decoder + residual buffer on stream close. Unified into a single `parseSseFrames` helper in `sse-parser.ts` that handles CRLF/LF, multi-line `data:` joined with `\n`, EOF flush, and `response.body` null-guard.
- **`ChatStateService` concurrency and mutation hazards** (`ai-accounts-core`). Single process-wide `threading.Lock` replaced with per-session locks so unrelated sessions no longer serialize on each other. Events returned from `replay()` / `get_event_log()` are now deep-copied — callers mutating a returned dict can no longer corrupt the retained log. New `replay_with_gap()` returns `ReplayResult(events, gap)` so callers detect eviction instead of silently missing history; `chat_send.py` emits an explicit `{kind: "gap"}` SSE event to reconnecting clients when this happens.
- **`conversations.py` input validation + error translation** (`ai-accounts-litestar`). Added msgspec min/max length constraints on `backend_id`, `model`, `title`, and `content`. `KeyError` on unknown session now returns 404 instead of falling through to 500. The streaming endpoint preflights session existence before opening the SSE response and wraps in-stream errors into structured SSE error frames.
- **`useSmartScroll` lifecycle** (`@ai-accounts/vue-headless`). Listeners and the `MutationObserver` previously attached only to the element present at mount; swapping `containerRef` left stale listeners on the old node and auto-scroll silently broke. Now watches `containerRef` with `flush: 'post'` and reattaches on change. Also observes `characterData: true` so streaming-token text-node mutations trigger auto-scroll.

### Changed
- **`AccountService.create` now dedups on re-run** (`ai-accounts-core`). Re-running the "Add Account" flow for the same underlying credentials no longer creates duplicate backend rows. Match keys in priority order: `(kind, config_path)` for CLI-managed creds, `(kind, api_key_env)` for API-key flows, `(kind, email)` as a last resort. When a match exists, `display_name` and `config` are merged into the existing row instead of spawning a duplicate.

### Developer experience
- Migrated auth middleware from deprecated `AbstractMiddleware` to `ASGIMiddleware` (litestar 2.15+), eliminating the deprecation warning.

---

## 0.3.0 — 2026-04-16

Stable release consolidating all alpha work: multi-backend login, smart chat, PTY sessions, and security hardening.

See alpha entries below for detailed per-feature changelogs.

### Fixed (since alpha.3)
- SSE reconnect seq-seed bug — post-eviction reconnects now produce monotonic seq IDs
- 5 silent `catch` blocks in `useStreamingParser` now log with context
- Heartbeat timeout now aborts in-flight fetch via AbortController
- Compound synthesis no longer silently falls back to `"claude"` on error
- `pty.fork()` → `os.forkpty()` for Python 3.14 compatibility

### Changed (since alpha.3)
- Heartbeat tuning: server 30s→20s, client 65s→90s
- `sendChat()` now accepts `{ signal, lastEventId }` options

---

## 0.3.0-alpha.3 — 2026-04-15

Smart AI chat panel v2 — real-time tool call visibility, resilient streaming, and message actions on top of the alpha.2 chat foundation.

### Added
- `ToolCallEvent` domain type (`ai-accounts-core`) — emitted by `ChatOrchestrator` when backends invoke tools
- `ChatStateService` (`ai-accounts-core`) — per-session seq numbering, event replay, and SSE reconnection support
- `tool_call` event streaming on `POST /api/v1/chat/send` SSE (`ai-accounts-litestar`)
- `@ai-accounts/ts-core`: `tool_call` variant on `SmartChatEvent` + `ProcessGroup` types
- `@ai-accounts/vue-headless`:
  - `useProcessGroups` composable — groups sequential tool calls into collapsible process groups
  - `useStreamingParser` composable — incremental markdown parsing via `streaming-markdown` (smd.js)
  - `useSmartChat`: seq-based event deduplication, heartbeat watchdog, finalization state
- `@ai-accounts/vue-styled`:
  - `ProcessGroup` component (tool-type badges + collapse)
  - `MessageActions` component (copy, retry, edit) wired into `ChatBubble`
  - `FinalizationBanner` component
  - `AiChatPanel` integration with density-aware defaults

### Fixed
- `tool_call` dispatch and `MessageActions` prop typing
- `vue-headless` dependency name — was typo `smd`, corrected to `streaming-markdown`

## 0.3.0-alpha.2 — 2026-04-11

### Fixed
- **`_ClaudeCliBrowserSession` stuck at "Starting login session..."** — port of `claude /login` did not handle Claude Code's interactive first-run TUI (theme picker, menu prompts, REPL idle detection). Ported Agented's interactive loop: emits a `ProgressUpdate` immediately, detects numbered menu options (`❯ 1. Dark mode`) and emits as `TextPrompt`, navigates via arrow keys on respond, detects REPL idle + re-sends `/login`, parses the OAuth URL. Shared impl in `ai_accounts_core/login/interactive.py`. End-to-end verified against real `claude 2.1.101`.
- **`AccountWizard` account name was required** — `subscriptionValid` gated `goNext` on non-empty name. Now genuinely optional; falls back to backend metadata `display_name` at save time. Label changed from "Name *" to "Name (optional)".

### Added
- `CliOrchestrator.poll_output()` — timeout-based output polling for interactive loops
- `parse_menu_options`, `send_menu_selection`, `MenuOption` helpers
- `run_interactive_cli_login()` shared state machine in `login/interactive.py`
- `_NUMBERED_OPTION_RE`, `_LOGIN_SUCCESS_RE`, `_URL_IN_OUTPUT_RE` module-level patterns

#### PTY Session System (originally planned as alpha.4)
- `AsyncPtyHandle` — async PTY subprocess wrapper with read/write/resize (`ai_accounts_core/pty/handle.py`)
- `PtyService` — session lifecycle management: spawn/attach/kill backed by `SessionRepository`
- `BackendProtocol.pty()` — implementations for Claude, Codex, Gemini, OpenCode backends
- `FakeBackend.pty()` + `AsyncPtyHandle`-based fake for test fixtures
- Litestar: `POST /api/v1/pty/spawn`, `/kill`, `/resize` + WebSocket `/ws/pty/{session_id}` binary frame bridge
- `@ai-accounts/ts-core`: `PtySocket` reconnect-capable WebSocket client + `spawnPty()`, `killPty()`, `resizePty()` methods
- `@ai-accounts/vue-headless`: `usePtySession` composable with reactive state
- `@ai-accounts/vue-styled`: `TerminalView.vue` component with xterm.js integration
- `xterm` + `@xterm/addon-fit` dependencies added to `vue-styled`

#### Security Hardening (originally planned as alpha.5)
- Fix SSRF port bypass in `cliproxy/manager.py` — validate port in allowed range, not just host
- Fix fd leak in `backends/claude.py` cleanup paths — narrow `except` catches to `(OSError, ProcessLookupError)` + log
- Replace silent key-format leak in error messages
- Narrow `finally`-block catches across backends; log previously-swallowed errors
- Log `rmtree` failures during account deletion instead of silently ignoring
- Add `GET /api/v1/backends/{id}/models` route + `list_models()` wiring across backends
- PR review fixes: typed DTOs, 204-no-content for empty pick responses, kind-filter fallback, timeout double-wrap removal, `backend_id` keying, structured logging, port validation, stderr capture
- Enable SQLite WAL mode for concurrent read performance
- Path traversal hardening via `Path.is_relative_to()` checks

### Test coverage
- 14 new unit tests for menu parsing + regexes + diff-line false-positive regression
- Rewritten Claude cli_browser login test with faked `time.monotonic` for deterministic timing
- 5 `AsyncPtyHandle` + `PtyService` tests (spawn/attach/kill roundtrip)
- 2 Litestar PTY REST route tests (spawn/kill)
- 5 `cliproxy/manager` unit tests
- 6 direct `run_interactive_cli_login` state-machine tests
- 3 real-subprocess `CliOrchestrator` tests (echo + cat + claude --version)

### Fixed (Python 3.14 compatibility)
- `cli_orchestrator.py` — replace removed `pty.fork()` with `os.forkpty()` (Python 3.14+)
- `test_strip_ansi_cursor_positioning` — align test with intentional semantics where cursor-row reposition (`ESC[H`) yields `\n` and column-only movement yields space

## 0.3.0-alpha.1 — 2026-04-11

### Added
- `LoginSession` ABC + `LoginEvent` discriminated union + `LoginSessionRegistry` — central abstraction for interactive backend login flows (`ai-accounts-core`)
- `CliOrchestrator` — PTY-based subprocess runner ported from Agented, supports stdout streaming, stdin writes, graceful terminate (`ai-accounts-core`)
- `BackendMetadata` + `BackendRegistry` served at `GET /api/v1/backends/_meta` — Python-side source of truth for backend capabilities, login flows, install commands, config schema
- `POST /api/v1/backends/{id}/login/begin` + SSE `GET /login/stream` + `/respond` + `/cancel` — interactive login route family (`ai-accounts-litestar`)
- `POST /api/v1/backends/{kind}/install` — per-backend CLI auto-installer
- `POST /api/v1/cliproxy/install` + `/cliproxy/status` + `/cliproxy/login/begin` + `/cliproxy/login/callback-forward` — CLIProxyAPI install and account registration
- `ClaudeBackend`, `CodexBackend`, `GeminiBackend`, `OpenCodeBackend` — real login flows:
  - Claude: `cli_browser` + `api_key`
  - Codex: `oauth_device` + `cli_browser` + `api_key`
  - Gemini: `oauth_device` + `direct_oauth` (PKCE) + `api_key`
  - OpenCode: `cli_browser` + `api_key`
- `AiAccountsClient` new methods: `beginLogin`, `streamLogin` (SSE consumer), `respondLogin`, `cancelLogin`, `getBackendMetadata`, `installBackendCli`, `cliproxyStatus`, `cliproxyInstall`, `cliproxyLoginBegin`, `cliproxyCallbackForward` (`@ai-accounts/ts-core`)
- `AiAccountsEvent` typed discriminated union (wizard + login lifecycle events) + event bus through `aiAccountsPlugin` (`@ai-accounts/vue-headless`)
- `aiAccountsPlugin`, `useAiAccounts`, `useBackendRegistry`, `useLoginSession` composables (`@ai-accounts/vue-headless`)
- `AccountWizard` (ported from Agented's polished 1947-line wizard), `BackendPicker`, `LoginStream`, `AccountEditForm` (`@ai-accounts/vue-styled`)

### Breaking
- `BackendProtocol.login()` / `poll_login()` removed. Backends now implement `begin_login(flow_kind, config, vault_ctx, isolation_dir) -> LoginSession`. Clean break from 0.2.x.
- `AccountService.login()` / `poll_login()` removed. Use `AccountService.begin_login(account_id, flow_kind, inputs) -> LoginSession`.
- Legacy `LoginResponseDTO` / `OAuthDeviceLoginDTO` / `LoginRequest` / `PollLoginRequest` removed from `ai-accounts-litestar`.
- Legacy `/api/v1/backends/{id}/login` and `/login/poll` routes removed. Use new SSE-based `/login/begin`, `/login/stream`, `/login/respond`, `/login/cancel`.

### Deprecated
- All 0.2.x releases — upgrade to 0.3.0-alpha.1.

### Migration
- Host apps: install `aiAccountsPlugin` at app root with `{client, onEvent?}`. Use `<AccountWizard>` from `@ai-accounts/vue-styled`. Old `backendApi` shim pattern no longer needed.
- Python host apps: construct `AiAccountsConfig(..., login_session_ttl_seconds=600.0)` and pass to `create_app`. Backends must provide `metadata: ClassVar[BackendMetadata]` and `begin_login()`.

### Notes
- Chat panel, PTY session management, and conversation store are deferred to `0.3.0-alpha.2` and `0.3.0-alpha.3`.

## 0.2.0 — 2026-04-11

### Added

- `OnboardingService` state machine (welcome → detect → pick → login → done), persisted via `OnboardingRepository`
- `GeminiBackend` with API-key and OAuth device flow (driven via `gemini auth login` CLI subprocess)
- `CodexBackend` with API-key and OAuth device flow (driven via `codex auth login` CLI subprocess)
- `<OnboardingFlow>` Vue component with tabbed API-key vs OAuth login, verification URL + copy-code UI, auto-polling
- `useOnboarding` Vue composable
- `createOnboardingFlow` TypeScript state machine in `ts-core`
- `POST /api/v1/onboarding/*` HTTP routes
- `POST /api/v1/backends/{id}/login/poll` HTTP route for OAuth polling
- Per-account isolation directories under `AiAccountsConfig.backend_dirs_path` (default `./backend_dirs`)
- `BackendProtocol.supported_login_flows: ClassVar[frozenset[str]]`

### Changed (BREAKING)

- `BackendProtocol.login()` returns `LoginResult` (tagged union) instead of `bytes`
- `BackendProtocol.login/validate/list_models/chat/pty` all take a new `isolation_dir: Path` kwarg
- `BackendProtocol.poll_login(handle, isolation_dir)` added
- `AccountService.__init__` requires `isolation_base_dir: Path`
- `AccountService.login()` returns `LoginResponse` (kind=complete|pending) instead of `Backend`
- `AccountService.delete()` cascades to the isolation directory (`shutil.rmtree`)
- `AiAccountsClient.loginBackend()` TypeScript return type changes from `unknown` to `LoginResponseDTO`
- `AiAccountsConfig` gains `backend_dirs_path: Path`

### Migration guide

If you are a third-party author of a `BackendProtocol` implementation:

1. Add `supported_login_flows: ClassVar[frozenset[str]] = frozenset({"api_key"})` to your class
2. Change method signatures to accept `isolation_dir: Path` as a keyword-only argument
3. Change `login()` to return `CredentialLogin(credential=...)` for API-key flows instead of returning bytes directly. Return `LoginError(code, message)` on validation failures — don't raise
4. Implement `poll_login(handle, isolation_dir)`. For backends that only support synchronous flows, return `LoginError(code="not_pollable", ...)`
5. Use `isolation_dir` to isolate per-account CLI state. Set the appropriate env var (`CLAUDE_CONFIG_DIR`, `GEMINI_CLI_HOME`, `CODEX_HOME`, etc.) when invoking the CLI

## 0.1.0 — 2026-04-11

Initial release. See Phase 0+1 plan for feature list.
