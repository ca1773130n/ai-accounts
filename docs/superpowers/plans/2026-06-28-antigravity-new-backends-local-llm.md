# Antigravity + New Backends + Local LLM — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the `gemini→antigravity` rename (safe login paths only), add five backends (DeepSeek, Qwen, Goose, Aider, Crush), and make `openai_compat` work with keyless local LLM servers.

**Architecture:** Three archetypes — (A) thin OpenAI-shaped api-key backends cloned from `openrouter.py` (DeepSeek, Qwen); (B) `openai_compat.py` extended for optional key + localhost presets (local LLM); (C) PTY-primary CLI agent backends cloned from `opencode.py` (Goose, Aider, Crush). Antigravity is a full kind rename + sqlite migration. Backends self-register via `backends/__init__.py` + the `apps/playground/server.py` tuple; chat/PTY dispatch is dynamic by kind.

**Tech Stack:** Python 3.11, msgspec, httpx, Litestar; Vue 3 / TypeScript (vue-styled); pytest + vue-tsc; `just` recipes; `uv` + `pnpm`.

## Global Constraints

- No new runtime dependencies — httpx + stdlib only.
- Keyless backend metadata: `install_check=InstallCheck(command=["true"], version_regex=r"(\d+)?")`, `isolation_env_var=None`, `detect()` returns `DetectResult(installed=True)`.
- API-key backends model `backends/openrouter.py` exactly (session class, `validate`/`list_models`/`chat`/`_env`).
- CLI backends model `backends/opencode.py` (`CliBackendBase`, `_CLI_NAME`, `_ISOLATION_ENV_VAR`, `pty()` via `AsyncPtyHandle.spawn`).
- Login events from `ai_accounts_core.login`: `TextPrompt`, `MenuPrompt(prompt_id, prompt, options=[MenuOption(value,label)])`, `LoginComplete(account_id="", backend_status="validating")`, `LoginFailed(code,message)`, `PromptAnswer`. Always handle `__cancel__` and the 300s timeout exactly as `openrouter.py`.
- `Model(id, display_name, context_window=None)` from `protocols/backend.py`.
- `ChatStreamEvent(kind, payload)` with `kind ∈ {"token","tool_call","done","error"}`.
- Isolation dirs MUST be absolute (`.resolve()`), created with `mkdir(parents=True, exist_ok=True)`.
- Tests model `packages/core/tests/backends/test_openrouter.py` (api-key) and `test_kimi.py` / existing `test_gemini_*` (CLI/cliproxy) for httpx mocking + login-event assertions.
- Grep guard (must return zero non-comment hits after Task 7): `grep -rn "gemini\|Gemini" --include="*.py" --include="*.ts" --include="*.vue" --include="*.toml" . | grep -vE "node_modules|.venv|.worktrees|__pycache__"`.
- After each wave: `just lint && just typecheck && just test` green.

---

## PHASE 1 — Antigravity rename (sequential; must finish before any new-backend task)

### Task 1: Rename `gemini` kind → `antigravity` across core + cliproxy + frontend

**Files:**
- Rename: `packages/core/src/ai_accounts_core/backends/gemini.py` → `backends/antigravity.py` (use `git mv`)
- Modify: `backends/__init__.py`, `backends/_models_fallback.py`, `apps/playground/server.py`, `cliproxy/manager.py`, `cliproxy/cliproxy_compat.toml`, `cliproxy/_compat.py`, `services/discovery.py`, `domain/backend.py`, and comment-only mentions in `install/backend_cli.py`, `login/cli_orchestrator.py`, `services/accounts.py`, `domain/chat_events.py`
- Frontend: `packages/vue-styled/src/utils/assistantLabel.ts`, `components/AiChatSelector.vue`, `components/AllModeResponses.vue`, `components/AccountWizard.vue`, `components/OnboardingFlow.vue`, `components/LoginStream.vue`, `apps/playground/src/App.vue`
- Test: rename `packages/core/tests/backends/test_gemini_*.py` → `test_antigravity_*.py`; `packages/vue-styled/tests/AiChatPanel.test.ts`, `AccountWizard.test.ts`

**Interfaces:**
- Produces: class `AntigravityBackend` with `kind="antigravity"`, `_ISOLATION_ENV_VAR="ANTIGRAVITY_HOME"`, `supported_login_flows=frozenset({"api_key","cli_browser"})`. `_STATIC["antigravity"]`, cliproxy `flag_map["antigravity"]="-antigravity-login"`, `cliproxy_compat.toml [providers] antigravity="google"`, `BackendKind.ANTIGRAVITY="antigravity"`.

- [ ] **Step 1:** Rename the test files first and update every `"gemini"`/`Gemini`/`GeminiBackend` token inside them to `antigravity`/`Antigravity`/`AntigravityBackend`. Run `pytest packages/core/tests/backends/test_antigravity_backend.py -v` → Expected: FAIL (import error / kind mismatch).
- [ ] **Step 2:** `git mv backends/gemini.py backends/antigravity.py`. In the new file: rename class `GeminiBackend`→`AntigravityBackend`; set `kind="antigravity"`; `_ISOLATION_ENV_VAR="ANTIGRAVITY_HOME"`; replace every internal literal `"gemini"` (LoginSession `backend_kind`, `fallback("gemini")`, `start_cliproxy_login("gemini")`) with `"antigravity"`. Keep `display_name="Antigravity"`, keep both login flows (api_key first). Fix the stale cliproxy callback-port comment `8085`→`51121`.
- [ ] **Step 3:** Add a guarded config-dir migration helper at module scope and call it from `AntigravityBackend.__init__`:

```python
def _migrate_legacy_config_dir() -> None:
    """One-time best-effort move ~/.gemini -> ~/.antigravity. Never raises."""
    import shutil
    from pathlib import Path
    old, new = Path.home() / ".gemini", Path.home() / ".antigravity"
    try:
        if old.exists() and not new.exists():
            shutil.move(str(old), str(new))
    except Exception:  # pragma: no cover - best effort
        pass
```

- [ ] **Step 4:** Update shared core files: `backends/__init__.py` (`from .antigravity import AntigravityBackend`, swap in `__all__`); `_models_fallback.py` `_STATIC` key `"gemini"`→`"antigravity"`; `apps/playground/server.py` import + tuple entry; `cliproxy/manager.py` `flag_map` key; `cliproxy/cliproxy_compat.toml` `[providers]`; `cliproxy/_compat.py` `_DEFAULT_OWNED_BY`; `services/discovery.py` `_probe_command` branch + docstring; `domain/backend.py` `BackendKind.GEMINI`→`ANTIGRAVITY="antigravity"`; comment mentions in the four files listed above.
- [ ] **Step 5:** Update frontend kind maps (gemini→antigravity) in all 7 files: `assistantLabel.ts` `BACKEND_DISPLAY_NAMES`; `AiChatSelector.vue`; `AllModeResponses.vue` (`{bg,fg,label}`); `AccountWizard.vue` (`PROXY_SUPPORTED_KINDS`, `DEFAULT_CONFIG_DIR_MAP` value `~/.antigravity`, `apiKeyEnv.envMap`, `NO_CLI_KINDS`, the ~323 comment); `OnboardingFlow.vue` (list + flow map); `LoginStream.vue` (`backendKind === 'antigravity'`); `App.vue` (`--kind-antigravity` CSS var, `.account-row--antigravity`, intro copy).
- [ ] **Step 6:** Run `pytest packages/core/tests/backends/test_antigravity_backend.py -v` → Expected: PASS. Run the grep guard → Expected: zero non-comment hits.
- [ ] **Step 7:** Commit: `git add -A && git commit -m "refactor: rename gemini backend kind to antigravity (core + cliproxy + frontend)"`

### Task 2: SQLite migration `kind='gemini'` → `'antigravity'`

**Files:**
- Modify: `packages/core/src/ai_accounts_core/adapters/storage_sqlite/migrations.py`
- Test: `packages/core/tests/adapters/test_migration_antigravity.py` (model existing migration tests)

**Interfaces:**
- Consumes: `Migration(version, description, statements)`, `CURRENT_VERSION` from migrations.py.
- Produces: `CURRENT_VERSION = 3`.

- [ ] **Step 1:** Write failing test: create a sqlite DB at schema v2 with a `backends` row `kind='gemini'`, run `migrate()`, assert the row's `kind` is now `'antigravity'` and `schema_version` is 3. Run → Expected: FAIL.
- [ ] **Step 2:** In `migrations.py` bump `CURRENT_VERSION = 3` and append to `MIGRATIONS`:

```python
Migration(
    version=3,
    description="rename backend kind 'gemini' to 'antigravity'",
    statements=(
        "UPDATE backends SET kind='antigravity' WHERE kind='gemini'",
    ),
),
```

- [ ] **Step 3:** Run the migration test → Expected: PASS. (No `schema.sql` baseline change — this is a data update; fresh DBs have no gemini rows.)
- [ ] **Step 4:** Commit: `git commit -am "feat(storage): migrate kind gemini->antigravity (schema v3)"`

---

## PHASE 2 — Thin/local backends (parallel; own files only, no shared-registry edits, no commit)

### Task 3: DeepSeek backend

**Files:**
- Create: `packages/core/src/ai_accounts_core/backends/deepseek.py`
- Test: `packages/core/tests/backends/test_deepseek.py`

**Interfaces:**
- Produces: `class DeepSeekBackend(CliBackendBase)` `kind="deepseek"`, `supported_login_flows=frozenset({"api_key"})`, `_DEEPSEEK_BASE="https://api.deepseek.com"`, `_env` sets `DEEPSEEK_API_KEY`. (Wired into registries by Task 8.)

- [ ] **Step 1:** Write failing test `test_deepseek.py` modeled on `test_openrouter.py`: assert `DeepSeekBackend().kind == "deepseek"`; `validate()` returns True on a mocked 200 `/models` and False on 401; `list_models()` parses a mocked `{data:[{id:"deepseek-v4-pro"}]}`; an empty key makes `validate()` False. Run → Expected: FAIL (module missing).
- [ ] **Step 2:** Create `deepseek.py` by cloning `openrouter.py`: rename session `_DeepSeekApiKeySession` (`backend_kind="deepseek"`, prompt `"DeepSeek API key"`), class `DeepSeekBackend`, `kind="deepseek"`, `_DEEPSEEK_BASE="https://api.deepseek.com"`, metadata `display_name="DeepSeek"` (keyless `install_check`), `validate`/`list_models`/`chat` hit `{_DEEPSEEK_BASE}/v1/...` (DeepSeek accepts `/v1`), `_env` returns `{**os.environ, "DEEPSEEK_API_KEY": credential.decode()}`, `list_models` ends `return fallback("deepseek")`.
- [ ] **Step 3:** Run `pytest packages/core/tests/backends/test_deepseek.py -v` → Expected: PASS. **Do not commit** (Phase 3 wires + commits).

### Task 4: Qwen backend

**Files:**
- Create: `packages/core/src/ai_accounts_core/backends/qwen.py`
- Test: `packages/core/tests/backends/test_qwen.py`

**Interfaces:**
- Produces: `class QwenBackend(CliBackendBase)` `kind="qwen"`, `_env` sets `DASHSCOPE_API_KEY`, base default `https://dashscope.aliyuncs.com/compatible-mode/v1`, region selectable.

- [ ] **Step 1:** Write failing test modeled on `test_openrouter.py`: `kind == "qwen"`; the login session first emits a `MenuPrompt` (CN/Intl/Custom) then an `api_key` `TextPrompt`; `validate()` True on mocked 200; credential is JSON `{"api_key","base_url"}`. Run → Expected: FAIL.
- [ ] **Step 2:** Create `qwen.py` cloned from `openrouter.py` but the session yields `MenuPrompt(prompt_id="region", prompt="DashScope region", options=[MenuOption("cn","China (dashscope.aliyuncs.com)"), MenuOption("intl","International (dashscope-intl)"), MenuOption("custom","Custom base URL")])`, resolves `base_url` (custom → follow-up `TextPrompt`), then `TextPrompt(prompt_id="api_key", hidden=True)`; credential = `json.dumps({"api_key":k,"base_url":b}).encode()`. `validate`/`list_models`/`chat` decode that JSON (reuse the `openai_compat._decode_credential` pattern), `_env` sets `DASHSCOPE_API_KEY`, `list_models` ends `return fallback("qwen")`.
- [ ] **Step 3:** Run `pytest packages/core/tests/backends/test_qwen.py -v` → Expected: PASS. **Do not commit.**

### Task 5: Local LLM — extend `openai_compat.py` (optional key + presets)

**Files:**
- Modify: `packages/core/src/ai_accounts_core/backends/openai_compat.py`
- Test: `packages/core/tests/backends/test_openai_compat.py` (extend)

**Interfaces:**
- Produces: `validate()` succeeds with empty key; login session emits a preset `MenuPrompt`.

- [ ] **Step 1:** Write failing tests: (a) `validate(json {"base_url":"http://x/v1","api_key":""})` returns True on mocked 200 with `{"data":[]}` (empty list still valid, no Authorization header sent); (b) `validate()` falls back to a mocked `/chat/completions` 200 when `/models` returns 404; (c) the login session first emits a `MenuPrompt` whose options include `ollama`,`lmstudio`,`vllm`,`llamacpp`,`oobabooga`,`custom`. Run → Expected: FAIL.
- [ ] **Step 2:** Edit `validate()`:

```python
async def validate(self, credential: bytes, *, isolation_dir: Path) -> bool:
    base_url, api_key = _decode_credential(credential)
    if not base_url:
        return False
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    try:
        async with httpx.AsyncClient(timeout=10.0) as http:
            resp = await http.get(f"{base_url}/models", headers=headers)
            if resp.status_code == 200:
                return True
            # /models may be absent (old llama.cpp) — probe chat as reachability.
            probe = await http.post(
                f"{base_url}/chat/completions", headers=headers,
                json={"model": "probe", "messages": [{"role": "user", "content": "ping"}], "max_tokens": 1},
            )
            return probe.status_code in (200, 400, 422)  # reachable & speaking OpenAI
    except (httpx.HTTPError, OSError):
        return False
```

- [ ] **Step 3:** In the login session, prepend before the base_url prompt:

```python
PRESETS = {
    "ollama": "http://localhost:11434/v1", "lmstudio": "http://localhost:1234/v1",
    "vllm": "http://localhost:8000/v1", "llamacpp": "http://localhost:8080/v1",
    "oobabooga": "http://localhost:5000/v1",
}
yield MenuPrompt(prompt_id="preset", prompt="Local server (or Custom)", options=[
    MenuOption("ollama","Ollama (:11434)"), MenuOption("lmstudio","LM Studio (:1234)"),
    MenuOption("vllm","vLLM (:8000)"), MenuOption("llamacpp","llama.cpp (:8080)"),
    MenuOption("oobabooga","oobabooga (:5000)"), MenuOption("custom","Custom base URL")])
```
Resolve the answer: a preset fills `base_url` and skips the base_url `TextPrompt`; `custom` keeps the existing base_url prompt. Then make the api_key prompt **optional** — an empty answer is allowed (do not `LoginFailed` on empty key); store `json.dumps({"api_key": key, "base_url": base_url}).encode()`.

- [ ] **Step 4:** Run `pytest packages/core/tests/backends/test_openai_compat.py -v` → Expected: PASS. **Do not commit.**

---

## PHASE 3 — Wire Wave 1 + frontend (sequential)

### Task 6: Register DeepSeek + Qwen; verify Antigravity wiring

**Files:** Modify `backends/__init__.py`, `backends/_models_fallback.py`, `apps/playground/server.py`

- [ ] **Step 1:** `backends/__init__.py` — add `from .deepseek import DeepSeekBackend` and `from .qwen import QwenBackend`, add both to `__all__`.
- [ ] **Step 2:** `_models_fallback.py` `_STATIC` — add `"deepseek": (Model(id="deepseek-v4-flash", display_name="DeepSeek V4 Flash"), Model(id="deepseek-v4-pro", display_name="DeepSeek V4 Pro"))` and `"qwen": (Model(id="qwen3-coder-plus", display_name="Qwen3 Coder Plus"), Model(id="qwen3-coder-flash", display_name="Qwen3 Coder Flash"))`.
- [ ] **Step 3:** `apps/playground/server.py` — import + add `DeepSeekBackend()`, `QwenBackend()` to the `backends=(...)` tuple.
- [ ] **Step 4:** Run `pytest packages/core/tests/backends -v` → Expected: PASS (all backends import cleanly).
- [ ] **Step 5:** Commit: `git add -A && git commit -m "feat(backends): add DeepSeek + Qwen; keyless local-LLM openai_compat"`

### Task 7: Frontend maps for antigravity + deepseek + qwen + local presets

**Files:** Modify the 7 frontend files from Task 1 Step 5; `packages/vue-styled/tests/*`

- [ ] **Step 1:** Add `deepseek`, `qwen` entries to `BACKEND_DISPLAY_NAMES` (assistantLabel.ts), `AiChatSelector.vue` label map, `AllModeResponses.vue` color map, `AccountWizard.vue` `apiKeyEnv.envMap` (`deepseek→DEEPSEEK`, `qwen→DASHSCOPE`) + `NO_CLI_KINDS` (both ✓), and the `OnboardingFlow.vue` backend list. (local LLM reuses the existing `openai_compat` kind — no new map entry.)
- [ ] **Step 2:** Update/extend `AccountWizard.test.ts` + `AiChatPanel.test.ts` to expect `Antigravity` (not Gemini) and the two new kinds. Run `pnpm --filter @ai-accounts/vue-styled test` → Expected: PASS.
- [ ] **Step 3:** Run the grep guard → Expected: zero non-comment hits. Run `just typecheck` → Expected: PASS.
- [ ] **Step 4:** Commit: `git add -A && git commit -m "feat(ui): wire antigravity/deepseek/qwen labels + local-LLM presets"`

---

## PHASE 4 — Agent backends (parallel; own files only, no commit)

### Task 8: Goose backend

**Files:** Create `backends/goose.py`; Test `tests/backends/test_goose_backend.py`

**Interfaces:** `class GooseBackend(CliBackendBase)` `kind="goose"`, `_CLI_NAME="goose"`. Credential JSON `{"provider","api_key","model"}`. `_env` sets `GOOSE_PATH_ROOT=<iso>`, `GOOSE_DISABLE_KEYRING="true"`, `GOOSE_PROVIDER`, `GOOSE_MODEL`, and the provider key env.

- [ ] **Step 1:** Write failing test (model `test_opencode.py`/`test_openrouter.py`): `kind=="goose"`; login session prompts provider (`MenuPrompt`) then api_key then model; `_env(...)` includes `GOOSE_PATH_ROOT` and `GOOSE_DISABLE_KEYRING=="true"` and the correct `<PROVIDER>_API_KEY`; `chat()` yields token events when fed a mocked `goose run` stream-json stdout. Run → Expected: FAIL.
- [ ] **Step 2:** Implement `goose.py`. `install_check=InstallCheck(["goose","--version"], r"(\d+\.\d+\.\d+)")`. Login session collects `{provider, api_key, model}` → JSON credential. `_env` as in Interfaces (map provider→key env: anthropic→`ANTHROPIC_API_KEY`, openai→`OPENAI_API_KEY`, openrouter→`OPENROUTER_API_KEY`). `chat()`:

```python
async def chat(self, request, credential, *, isolation_dir):
    import json as _json
    env = self._env(credential, isolation_dir)
    proc = await asyncio.create_subprocess_exec(
        "goose", "run", "-t", request.messages[-1].content,
        "--no-session", "--output-format", "stream-json",
        env=env, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
    )
    assert proc.stdout is not None
    async for raw in proc.stdout:
        line = raw.decode("utf-8", "replace").strip()
        if not line:
            continue
        try:
            ev = _json.loads(line)
        except ValueError:
            continue
        text = ev.get("content") or ev.get("text")
        if text:
            yield ChatStreamEvent(kind="token", payload=text)
    await proc.wait()
    yield ChatStreamEvent(kind="done", payload={"model": request.model})
    # ponytail: chat() parses `goose run` stream-json; pty() is the fallback if framing shifts.
```
`pty()`: spawn `["goose","session"]` via `AsyncPtyHandle.spawn` with `_env`. `list_models` → `fallback("goose")`. `get_usage` → `[]`.
- [ ] **Step 3:** Run `pytest packages/core/tests/backends/test_goose_backend.py -v` → Expected: PASS. **Do not commit.**

### Task 9: Aider backend

**Files:** Create `backends/aider.py`; Test `tests/backends/test_aider_backend.py`

**Interfaces:** `class AiderBackend(CliBackendBase)` `kind="aider"`, `_CLI_NAME="aider"`, `isolation_env_var=None`. Credential JSON `{"provider","api_key","model"}`. `_env` sets `HOME=<iso>` + `<PROVIDER>_API_KEY`.

- [ ] **Step 1:** Write failing test: `kind=="aider"`; `_env(...)["HOME"]` equals the resolved isolation dir (asserts host `~/.aider.conf.yml` can't leak); provider key env set; `pty()` returns a handle. Run → Expected: FAIL.
- [ ] **Step 2:** Implement `aider.py`. `install_check=InstallCheck(["aider","--version"], r"(\d+\.\d+\.\d+)")`. `_env` returns `{**os.environ, "HOME": str(isolation_dir.resolve()), "<PROVIDER>_API_KEY": key}`. `pty()`: `["aider","--model",model,"--no-git"]`. `chat()`: best-effort one-shot:

```python
async def chat(self, request, credential, *, isolation_dir):
    env = self._env(credential, isolation_dir)
    proc = await asyncio.create_subprocess_exec(
        "aider", "--model", request.model, "--no-git", "--yes",
        "--message", request.messages[-1].content,
        env=env, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        cwd=str(isolation_dir.resolve()),
    )
    out, _ = await proc.communicate()
    yield ChatStreamEvent(kind="token", payload=out.decode("utf-8", "replace"))
    yield ChatStreamEvent(kind="done", payload={"model": request.model})
    # ponytail: PTY-primary; chat() is a one-shot stdout scrape, no token stream.
```
`list_models` → `fallback("aider")`. `get_usage` → `[]`.
- [ ] **Step 3:** Run the test → Expected: PASS. **Do not commit.**

### Task 10: Crush backend

**Files:** Create `backends/crush.py`; Test `tests/backends/test_crush_backend.py`

**Interfaces:** `class CrushBackend(CliBackendBase)` `kind="crush"`, `_CLI_NAME="crush"`. Credential JSON `{"provider","api_key","model"}`. `_env` sets `CRUSH_GLOBAL_CONFIG=<iso>/crush.json`, `CRUSH_GLOBAL_DATA=<iso>/data`.

- [ ] **Step 1:** Write failing test: `kind=="crush"`; login writes an isolated `crush.json` containing the provider+api_key under the isolation dir; `_env` sets `CRUSH_GLOBAL_CONFIG`/`CRUSH_GLOBAL_DATA`; `chat()` yields an `error` event (TUI-only, no headless). Run → Expected: FAIL.
- [ ] **Step 2:** Implement `crush.py`. `install_check=InstallCheck(["crush","--version"], r"(\d+\.\d+\.\d+)")`. On login, write `<iso>/crush.json` with the provider/api_key. `_env` sets the two `CRUSH_GLOBAL_*` vars. `pty()`: `["crush"]`. `chat()`: `yield ChatStreamEvent(kind="error", payload="crush is TUI-only; use an interactive PTY session")` `# ponytail: crush is TUI-only; no headless chat — pty() only.` `list_models` → `fallback("crush")`. `get_usage` → `[]`.
- [ ] **Step 3:** Run the test → Expected: PASS. **Do not commit.**

---

## PHASE 5 — Wire Wave 2 + finalize (sequential)

### Task 11: Register Goose + Aider + Crush

**Files:** Modify `backends/__init__.py`, `backends/_models_fallback.py`, `apps/playground/server.py`, `services/discovery.py`

- [ ] **Step 1:** `__init__.py` — import + `__all__` for `GooseBackend`, `AiderBackend`, `CrushBackend`.
- [ ] **Step 2:** `_models_fallback.py` `_STATIC` — add `"goose": ()`, `"aider": ()`, `"crush": ()` (curated lists optional; live/empty is acceptable).
- [ ] **Step 3:** `apps/playground/server.py` — add the three to the tuple.
- [ ] **Step 4:** `services/discovery.py` `_probe_command` — add probe branches for `goose`/`aider`/`crush` (config-dir presence) if auto-discovery is wanted; otherwise skip.
- [ ] **Step 5:** Run `pytest packages/core/tests/backends -v` → Expected: PASS.
- [ ] **Step 6:** Commit: `git add -A && git commit -m "feat(backends): add Goose, Aider, Crush (PTY-primary)"`

### Task 12: Frontend maps for goose/aider/crush

**Files:** Modify the 7 frontend files; `packages/vue-styled/tests/*`

- [ ] **Step 1:** Add `goose`,`aider`,`crush` to `BACKEND_DISPLAY_NAMES`, `AiChatSelector.vue`, `AllModeResponses.vue`, `OnboardingFlow.vue` list; `AccountWizard.vue` `DEFAULT_CONFIG_DIR_MAP` (`goose→~/.config/goose`), and leave them OUT of `NO_CLI_KINDS` (they have CLIs).
- [ ] **Step 2:** Update Vue tests to include the three kinds. Run `pnpm --filter @ai-accounts/vue-styled test` → Expected: PASS.
- [ ] **Step 3:** Commit: `git add -A && git commit -m "feat(ui): wire goose/aider/crush backend labels"`

### Task 13: Full-suite gate + CHANGELOG

**Files:** Modify `CHANGELOG.md`, `README.md` (backend list)

- [ ] **Step 1:** Run `just lint && just typecheck && just test` → Expected: all PASS. Run the grep guard → zero non-comment hits.
- [ ] **Step 2:** Add a CHANGELOG entry (Antigravity rename, DeepSeek/Qwen/Goose/Aider/Crush, keyless local LLM) and update the README backend list.
- [ ] **Step 3:** Commit: `git add -A && git commit -m "docs: changelog + readme for antigravity + new backends + local LLM"`

---

## Self-Review

- **Spec coverage:** Antigravity rename+migration (T1,T2,T7) ✓; DeepSeek (T3,T6,T7) ✓; Qwen (T4,T6,T7) ✓; local LLM keyless+presets (T5) ✓; Goose/Aider/Crush (T8–T12) ✓; tests + grep guard (each task + T13) ✓; safe-paths-only Antigravity (no /v1internal code) ✓; PTY-primary agents ✓.
- **Placeholder scan:** none — every code step shows code; clones name their template + exact deltas.
- **Type consistency:** `Model(id, display_name, context_window)`, `ChatStreamEvent(kind,payload)`, `MenuPrompt(prompt_id,prompt,options=[MenuOption(value,label)])`, `LoginComplete(account_id="", backend_status="validating")` used consistently across tasks.
- **Ordering:** Phase 1 (antigravity rename) precedes all new-backend tasks because it transiently breaks `backends/__init__.py` imports; Phase 2/4 create own files only (no shared-registry edits) so they parallelize safely; Phase 3/5 do the shared-file wiring sequentially.
