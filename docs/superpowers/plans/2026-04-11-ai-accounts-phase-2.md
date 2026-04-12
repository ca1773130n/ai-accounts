# ai-accounts Phase 2 Implementation Plan — Onboarding + Gemini + Codex

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `ai-accounts@0.2.0` adding the onboarding state machine + component, two new AI backends (Gemini and Codex with both API-key and OAuth device flows), and per-account isolation dirs so multiple accounts per backend kind don't stomp on each other.

**Architecture:** Extends v0.1.0 with a breaking `BackendProtocol` change: `login/validate/list_models` take a new `isolation_dir: Path` kwarg, and `login` returns a `LoginResult` tagged union (`CredentialLogin` for API-key flows, `OAuthDeviceLogin` for device-code flows). OAuth is driven via a polling endpoint (`POST /backends/{id}/login/poll`) — SSE streaming is deferred to Phase 3. Per-account state directories live under `<base>/backend_dirs/<bkd-id>/`, derived from backend id so no schema migration is needed. Onboarding is a new service with its own Protocol-backed state machine, HTTP routes, Vue composable, and themed component.

**Tech Stack:** Python 3.11+, Litestar 2.12+, msgspec, aiosqlite, cryptography. TypeScript 5.5+, Vue 3.4+, tsup, Vite, Vitest. `uv` + `pnpm` workspaces. Apache-2.0.

**Spec reference:** `docs/superpowers/specs/2026-04-11-ai-accounts-package-design.md` (Phase 2 scope).

**Base:** ai-accounts@0.1.0 (tag `v0.1.0`, live on PyPI as `ai-accounts-core==0.1.0` and `ai-accounts-litestar==0.1.0`; JS packages not yet on npm).

**Scope boundary:** This plan covers Phase 2 only. Phase 3 (chat), Phase 4 (PTY/sessions), Phase 5 (auth hardening + OIDC), Phase 6 (1.0 prep) are separate plans, written after this phase lands green.

**Known regressions carried forward from Phase 1:** Agented's `feat/ai-accounts-phase-1` branch has undefined DTO fields in the `backendApi` shim and a broken inline save form in `BackendDetailPage.vue`. This plan does NOT fix them — they are tracked separately. Phase 2's Agented-migration tasks (Part F) only touch onboarding views.

## Prerequisite check (run BEFORE Task 1)

```
cd ~/Developer/Projects/ai-accounts
git log --oneline | head -3   # must show d4a8d51 as HEAD
git tag                       # must show v0.1.0
uv run pytest 2>&1 | tail -3  # 81 passing
pnpm -r test 2>&1 | tail -5   # 24 passing
```

If any fail, STOP. Phase 2 depends on Phase 1 being green.

---

## Plan structure

- **Part A — Protocol evolution** (Tasks 1-4): BackendProtocol breaking change, update Claude/OpenCode, AccountService isolation dir management.
- **Part B — New backends** (Tasks 5-6): GeminiBackend and CodexBackend, each with api_key + oauth_device flows.
- **Part C — Onboarding + routes** (Tasks 7-9): OnboardingService, Litestar route updates, new onboarding routes.
- **Part D — Frontend** (Tasks 10-14): ts-core regeneration, onboardingFlow state machine, Vue composable + component, AccountWizard updates.
- **Part E — Playground + release** (Tasks 15-16): playground switches to OnboardingFlow, version bump + publish.
- **Part F — Agented migration** (Tasks 17-20): rebuild, swap OnboardingAutomationPage, delete superseded code, integration test.

---

# Part A — Protocol evolution

## Task 1: BackendProtocol breaking change

**Files:**
- Modify: `packages/core/src/ai_accounts_core/protocols/backend.py`
- Modify: `packages/core/src/ai_accounts_core/testing/fakes.py` (FakeBackend)
- Modify: `packages/core/tests/test_protocols.py`
- Create: `packages/core/tests/test_login_result.py`

### Design

New `BackendProtocol` surface:

```python
class LoginFlow(msgspec.Struct, frozen=True, kw_only=True):
    kind: str  # "api_key" | "oauth_device"
    inputs: dict[str, str] = {}


class CredentialLogin(msgspec.Struct, tag="credential", tag_field="type", frozen=True, kw_only=True):
    credential: bytes


class OAuthDeviceLogin(msgspec.Struct, tag="oauth_device", tag_field="type", frozen=True, kw_only=True):
    verification_uri: str
    user_code: str
    expires_at: datetime
    handle: str  # opaque, backend-internal


class LoginError(msgspec.Struct, tag="error", tag_field="type", frozen=True, kw_only=True):
    code: str
    message: str


LoginResult = CredentialLogin | OAuthDeviceLogin | LoginError


class BackendProtocol(Protocol):
    kind: ClassVar[str]
    supported_login_flows: ClassVar[frozenset[str]]

    async def detect(self) -> DetectResult: ...
    async def login(self, flow: LoginFlow, *, isolation_dir: Path) -> LoginResult: ...
    async def poll_login(self, handle: str, *, isolation_dir: Path) -> LoginResult: ...
    async def validate(self, credential: bytes, *, isolation_dir: Path) -> bool: ...
    async def list_models(self, credential: bytes, *, isolation_dir: Path) -> list[Model]: ...
    async def chat(self, request, credential, *, isolation_dir) -> AsyncIterator: ...
    async def pty(self, request, credential, *, isolation_dir) -> PtyHandle: ...
```

**Semantics:**
- `login(flow.kind=="api_key", ...)` returns `CredentialLogin(credential=<plaintext bytes>)` synchronously.
- `login(flow.kind=="oauth_device", ...)` starts the backend's OAuth flow (typically a CLI subprocess in the isolation dir), returns `OAuthDeviceLogin(uri, code, expires, handle)` immediately. Backend retains subprocess state keyed by `handle`.
- `poll_login(handle)` checks status. Returns `OAuthDeviceLogin(...)` (still pending, same handle), `CredentialLogin(credential=b"")` (done — state in isolation dir), or `LoginError(code, message)`.
- `validate(credential, isolation_dir)` uses BOTH credential (API-key) AND isolation dir (OAuth state). Empty credential + valid isolation dir = OAuth login still valid.
- Each backend declares `supported_login_flows`. Frontend uses this to show only the right login options.

### Step 1: Write failing tests

`packages/core/tests/test_login_result.py`:

```python
from datetime import UTC, datetime

import msgspec

from ai_accounts_core.protocols.backend import (
    CredentialLogin,
    LoginError,
    LoginResult,
    OAuthDeviceLogin,
)


def test_credential_login_roundtrip():
    login = CredentialLogin(credential=b"sk-ant-abc")
    encoded = msgspec.json.encode(login)
    decoded = msgspec.json.decode(encoded, type=LoginResult)
    assert decoded == login
    assert isinstance(decoded, CredentialLogin)


def test_oauth_device_login_roundtrip():
    login = OAuthDeviceLogin(
        verification_uri="https://accounts.google.com/o/oauth2/device/usercode",
        user_code="ABCD-1234",
        expires_at=datetime(2026, 4, 11, 18, 0, 0, tzinfo=UTC),
        handle="oauth-abc123",
    )
    encoded = msgspec.json.encode(login)
    decoded = msgspec.json.decode(encoded, type=LoginResult)
    assert decoded == login
    assert isinstance(decoded, OAuthDeviceLogin)


def test_login_error_roundtrip():
    err = LoginError(code="timeout", message="user did not complete auth in 15 minutes")
    encoded = msgspec.json.encode(err)
    decoded = msgspec.json.decode(encoded, type=LoginResult)
    assert decoded == err
    assert isinstance(decoded, LoginError)


def test_tagged_union_discrimination():
    raw = msgspec.json.encode(CredentialLogin(credential=b"x"))
    parsed = msgspec.json.decode(raw)
    assert parsed["type"] == "credential"
```

### Step 2: Run — expect ModuleNotFoundError

### Step 3: Replace `protocols/backend.py`

```python
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path
from typing import ClassVar, Protocol, Union, runtime_checkable

import msgspec

from ai_accounts_core.domain.backend import DetectResult
from ai_accounts_core.domain.chat import ChatMessage


class Model(msgspec.Struct, frozen=True, kw_only=True):
    id: str
    display_name: str
    context_window: int | None = None
    input_price_per_mtok: float | None = None
    output_price_per_mtok: float | None = None


class LoginFlow(msgspec.Struct, frozen=True, kw_only=True):
    kind: str
    inputs: dict[str, str] = {}


class CredentialLogin(
    msgspec.Struct, tag="credential", tag_field="type", frozen=True, kw_only=True
):
    credential: bytes


class OAuthDeviceLogin(
    msgspec.Struct, tag="oauth_device", tag_field="type", frozen=True, kw_only=True
):
    verification_uri: str
    user_code: str
    expires_at: datetime
    handle: str


class LoginError(
    msgspec.Struct, tag="error", tag_field="type", frozen=True, kw_only=True
):
    code: str
    message: str


LoginResult = Union[CredentialLogin, OAuthDeviceLogin, LoginError]


class ChatRequest(msgspec.Struct, frozen=True, kw_only=True):
    messages: tuple[ChatMessage, ...]
    model: str
    params: dict[str, object] = {}


class PtyRequest(msgspec.Struct, frozen=True, kw_only=True):
    command: tuple[str, ...]
    cols: int
    rows: int
    env: dict[str, str] = {}


class ChatStreamEvent(msgspec.Struct, frozen=True, kw_only=True):
    kind: str
    payload: object = None


class PtyHandle(Protocol):
    async def write(self, data: bytes) -> None: ...
    async def resize(self, cols: int, rows: int) -> None: ...
    async def read(self) -> AsyncIterator[bytes]: ...
    async def close(self) -> None: ...


@runtime_checkable
class BackendProtocol(Protocol):
    kind: ClassVar[str]
    supported_login_flows: ClassVar[frozenset[str]]

    async def detect(self) -> DetectResult: ...
    async def login(self, flow: LoginFlow, *, isolation_dir: Path) -> LoginResult: ...
    async def poll_login(self, handle: str, *, isolation_dir: Path) -> LoginResult: ...
    async def validate(self, credential: bytes, *, isolation_dir: Path) -> bool: ...
    async def list_models(self, credential: bytes, *, isolation_dir: Path) -> list[Model]: ...
    async def chat(
        self,
        request: ChatRequest,
        credential: bytes,
        *,
        isolation_dir: Path,
    ) -> AsyncIterator[ChatStreamEvent]: ...
    async def pty(
        self,
        request: PtyRequest,
        credential: bytes,
        *,
        isolation_dir: Path,
    ) -> PtyHandle: ...
```

### Step 4: Update `FakeBackend` in `testing/fakes.py`

Key parts: declare `supported_login_flows = frozenset({"api_key", "oauth_device"})`. Implement `login` branching on `flow.kind`:
- `api_key` → `CredentialLogin(credential=b"fake-credential")`
- `oauth_device` → create a fresh handle, record poll count = 0, return `OAuthDeviceLogin(verification_uri="https://example.com/device", user_code="FAKE-1234", expires_at=now+15min, handle=<new>)`

Implement `poll_login(handle, isolation_dir)`:
- Unknown handle → `LoginError(code="unknown_handle", message=handle)`
- Increment poll count; after 2 polls, write a marker file `<isolation_dir>/oauth_token.fake` and return `CredentialLogin(credential=b"")`.
- Otherwise return the same `OAuthDeviceLogin`.

`validate(credential, isolation_dir)`:
- `credential == b"fake-credential"` → True (API-key path)
- `credential == b"" and (isolation_dir / "oauth_token.fake").exists()` → True (OAuth path)
- else False

### Step 5: Run protocol + login_result tests

```
uv run pytest packages/core/tests/test_login_result.py packages/core/tests/test_protocols.py -v
```

Expected: 5 new + 5 existing protocol tests pass. The broader suite will be red (Claude/OpenCode backends and AccountService break because signatures changed) until Tasks 2, 3, 4 land — that's intentional TDD red state.

### Step 6: Commit

```
git add packages/core/src/ai_accounts_core/protocols/backend.py \
         packages/core/src/ai_accounts_core/testing/fakes.py \
         packages/core/tests/test_login_result.py \
         packages/core/tests/test_protocols.py
git commit -m "feat(core)!: BackendProtocol takes isolation_dir and returns LoginResult"
```

The `!` marks this as a breaking change per conventional-commits.

---

## Task 2: Update ClaudeBackend for new Protocol

**Files:**
- Modify: `packages/core/src/ai_accounts_core/backends/claude.py`
- Modify: `packages/core/tests/test_claude_backend.py`

### Step 1: Update test imports + add `isolation_dir=tmp_path / "claude"` to every method call

Add new tests specifically for the new behaviour:

```python
@pytest.mark.asyncio
async def test_login_api_key_returns_credential_login(tmp_path):
    backend = ClaudeBackend()
    result = await backend.login(
        LoginFlow(kind="api_key", inputs={"api_key": "sk-ant-abc123"}),
        isolation_dir=tmp_path / "claude",
    )
    assert isinstance(result, CredentialLogin)
    assert result.credential == b"sk-ant-abc123"


@pytest.mark.asyncio
async def test_login_unsupported_flow_returns_error(tmp_path):
    backend = ClaudeBackend()
    result = await backend.login(
        LoginFlow(kind="oauth_device", inputs={}),
        isolation_dir=tmp_path / "claude",
    )
    assert isinstance(result, LoginError)
    assert result.code == "unsupported_flow"


@pytest.mark.asyncio
async def test_validate_uses_isolation_dir_in_env(tmp_path):
    backend = ClaudeBackend()
    isolation_dir = tmp_path / "claude"
    isolation_dir.mkdir()
    with patch("shutil.which", return_value="/usr/local/bin/claude"), \
         patch.object(backend, "_run", new=AsyncMock(return_value=(0, b"ok", b""))) as mock_run:
        result = await backend.validate(b"sk-ant-test", isolation_dir=isolation_dir)
    assert result is True
    spec = mock_run.await_args.args[0]
    assert spec["env"]["ANTHROPIC_API_KEY"] == "sk-ant-test"
    assert spec["env"]["CLAUDE_CONFIG_DIR"] == str(isolation_dir)


def test_supported_login_flows_is_api_key_only():
    assert ClaudeBackend.supported_login_flows == frozenset({"api_key"})
```

Update all existing tests (detect / list_models / validate existing / etc.) to pass `isolation_dir=tmp_path / "claude"` where required.

### Step 2: Rewrite `backends/claude.py`

Key changes from v0.1.0:
- Add `_ISOLATION_ENV_VAR: ClassVar[str] = "CLAUDE_CONFIG_DIR"`
- Add `supported_login_flows: ClassVar[frozenset[str]] = frozenset({"api_key"})`
- `login(flow, *, isolation_dir)` returns `LoginResult` (CredentialLogin on success, LoginError on failure — do NOT raise ValueError)
- `poll_login(handle, *, isolation_dir)` returns `LoginError(code="not_pollable", ...)` — Claude doesn't support OAuth
- `validate(credential, *, isolation_dir)`: adds `_ISOLATION_ENV_VAR` to env, mkdir the dir first
- `list_models(credential, *, isolation_dir)`: same
- Shared helper `_env(credential, isolation_dir)` builds the env dict with both `ANTHROPIC_API_KEY` and `CLAUDE_CONFIG_DIR`
- `chat` and `pty` raise `NotImplementedError` as before, with `*, isolation_dir` kwarg

### Step 3: Run tests + commit

```
uv run pytest packages/core/tests/test_claude_backend.py -v
git add packages/core/src/ai_accounts_core/backends/claude.py packages/core/tests/test_claude_backend.py
git commit -m "feat(core): update ClaudeBackend for isolation_dir + LoginResult"
```

---

## Task 3: Update OpenCodeBackend for new Protocol

Structural clone of Task 2. Differences:
- `_ISOLATION_ENV_VAR = "OPENCODE_HOME"` (verify with `opencode --help` — if a different env var is used for CLI config dir, adapt)
- `validate` runs `[path, "auth", "check"]` with `OPENCODE_API_KEY`
- `list_models` runs `[path, "models", "--json"]`
- `supported_login_flows = frozenset({"api_key"})`

Commit:

```
git add packages/core/src/ai_accounts_core/backends/opencode.py packages/core/tests/test_opencode_backend.py
git commit -m "feat(core): update OpenCodeBackend for isolation_dir + LoginResult"
```

---

## Task 4: Update AccountService for isolation dirs + new login flow

**Files:**
- Modify: `packages/core/src/ai_accounts_core/services/accounts.py`
- Modify: `packages/core/src/ai_accounts_core/services/errors.py`
- Modify: `packages/litestar/src/ai_accounts_litestar/config.py` (add `backend_dirs_path`)
- Modify: `packages/litestar/src/ai_accounts_litestar/app.py` (pass isolation_base_dir)
- Modify: `packages/core/tests/test_account_service.py`
- Modify: `packages/litestar/tests/test_backends_routes.py` (fixture passes backend_dirs_path)

### Design

`AccountService.__init__` gains `isolation_base_dir: Path`. Per-backend isolation dir = `self._isolation_base_dir / backend_id`. Methods:

- `create(...)` creates the backend row AND `mkdir` the isolation dir.
- `delete(backend_id)` removes the backend row, credential, AND `shutil.rmtree` the isolation dir.
- `login(backend_id, *, flow_kind, inputs) -> LoginResponse` where:
  ```python
  class LoginResponse(msgspec.Struct, kw_only=True):
      kind: Literal["complete", "pending"]
      backend: Backend | None = None
      oauth: OAuthDeviceLogin | None = None
  ```
  Returns `LoginResponse(kind="complete", backend=<Backend>)` for API-key flows (after encrypting + storing credential + transitioning to VALIDATING). Returns `LoginResponse(kind="pending", oauth=<OAuthDeviceLogin>)` for OAuth. Raises `BackendValidationFailed` on `LoginError`. Raises `LoginFlowUnsupported` if the backend doesn't support the requested flow.
- `poll_login(backend_id, *, handle) -> LoginResponse`: same return type. When the underlying `poll_login` returns `CredentialLogin(credential=b"")`, persists an empty-credential row and transitions to VALIDATING.
- `validate/list_models` pass `isolation_dir=self._isolation_dir(backend_id)` to the impl.

Refactor `AccountService._handle_login_result(backend, result)` to centralize the logic that turns a `LoginResult` into a `LoginResponse`:
- `LoginError` → update status to ERROR with last_error; raise BackendValidationFailed
- `OAuthDeviceLogin` → return `LoginResponse(kind="pending", oauth=result)`, do NOT touch backend state yet
- `CredentialLogin` → encrypt credential via vault, persist `BackendCredential`, update status to VALIDATING, return `LoginResponse(kind="complete", backend=updated)`

Add `AccountService.available_kinds() -> list[str]` and `_impl_for(kind) -> BackendProtocol` helpers so `OnboardingService` doesn't reach into the private mapping.

Add `LoginFlowUnsupported` to `services/errors.py`:

```python
class LoginFlowUnsupported(ServiceError):
    code = "login_flow_unsupported"
```

### Step 1: Write failing tests

Fixture:

```python
def _make_service(tmp_path):
    from ai_accounts_core.services.accounts import AccountService
    from ai_accounts_core.testing import FakeBackend, FakeStorage, FakeVault

    storage = FakeStorage()
    vault = FakeVault()
    fake_backend = FakeBackend()
    service = AccountService(
        storage=storage,
        vault=vault,
        backends={fake_backend.kind: fake_backend},
        isolation_base_dir=tmp_path / "backend_dirs",
    )
    return service, storage, vault, fake_backend
```

Tests to add:
- `test_create_backend_ensures_isolation_dir` — after create, `tmp_path / "backend_dirs" / created.id` exists.
- `test_delete_backend_removes_isolation_dir` — after delete, the dir is gone.
- `test_login_api_key_returns_complete_response` — asserts `response.kind == "complete"` and `response.backend.status.value == "validating"`.
- `test_login_oauth_returns_pending_response` — asserts `response.kind == "pending"` and `response.oauth.handle.startswith("fake-handle-")`.
- `test_poll_login_eventually_completes` — start oauth, first poll is pending, second poll is complete.
- `test_validate_oauth_flow_reads_isolation_dir` — full oauth path → validate → status READY.

Update existing happy-path test: `test_login_then_validate_happy_path` asserts on `LoginResponse(kind="complete", backend=...)` instead of a bare `Backend`.

### Step 2: Rewrite `services/accounts.py` using the design above

Key structural pieces:
- Import `shutil` for rmtree.
- Add `self._isolation_base_dir.mkdir(parents=True, exist_ok=True)` in `__init__`.
- New method `_isolation_dir(self, backend_id)` returns `self._isolation_base_dir / backend_id`.
- New method `_handle_login_result(backend, result)` as a private coroutine.
- All Protocol method calls (`impl.login/poll_login/validate/list_models`) pass `isolation_dir=self._isolation_dir(backend.id)`.
- Module-level `LoginResponse` msgspec Struct defined before `AccountService`.
- Public `available_kinds()` and `_impl_for(kind)` methods.

### Step 3: Add `backend_dirs_path` to Litestar config + app

In `config.py`:

```python
from pathlib import Path
from typing import Any, Literal

import msgspec


class AiAccountsConfig(msgspec.Struct, kw_only=True):
    env: Literal["development", "production"] = "development"
    storage: Any = None
    vault: Any = None
    auth: Any = None
    backends: tuple[Any, ...] = ()
    cors_origins: tuple[str, ...] = ()
    backend_dirs_path: Path = Path("./backend_dirs")
```

In `app.py`, pass `isolation_base_dir=config.backend_dirs_path` into `AccountService(...)`.

Update `packages/litestar/tests/test_backends_routes.py` fixture to pass `backend_dirs_path=tmp_path / "backend_dirs"` into `AiAccountsConfig`. Update the happy-path login test to assert on the new LoginResponseDTO shape (Task 8 refines the DTO; this step is the minimum to keep the suite green).

### Step 4: Run full suite

```
uv run pytest 2>&1 | tail -10
```

Expected: all core + litestar tests pass.

### Step 5: Commit

```
git add packages/core/src/ai_accounts_core/services/accounts.py \
         packages/core/src/ai_accounts_core/services/errors.py \
         packages/core/tests/test_account_service.py \
         packages/litestar/src/ai_accounts_litestar/config.py \
         packages/litestar/src/ai_accounts_litestar/app.py \
         packages/litestar/tests/test_backends_routes.py \
         packages/litestar/tests/test_config_guard.py
git commit -m "feat(core)!: AccountService isolation dirs and OAuth poll flow"
```

---

# Part B — New backends

## Task 5: GeminiBackend

**Files:**
- Create: `packages/core/src/ai_accounts_core/backends/gemini.py`
- Modify: `packages/core/src/ai_accounts_core/backends/__init__.py`
- Create: `packages/core/tests/test_gemini_backend.py`

### Design

Google's Gemini CLI is `gemini`. Authentication:
- **API key flow:** set `GEMINI_API_KEY` env var.
- **OAuth device flow:** run `gemini auth login` which emits a verification URL + user code to stdout, then polls until the user completes in-browser. On success, tokens are written to `$GEMINI_CLI_HOME/auth.json` (or similar). The CLI blocks until complete.

`GeminiBackend.login(oauth_device, ...)` spawns `gemini auth login` in the isolation dir via `GEMINI_CLI_HOME`, reads up to 2KB of stdout to parse the verification URL + user code using regex, returns them as `OAuthDeviceLogin`, and retains the running subprocess keyed by handle. `poll_login(handle, ...)` checks whether the subprocess has exited:
- Still running (`returncode is None`) → return `OAuthDeviceLogin(...)` (same handle, re-emitting the original challenge)
- Exited rc=0 → return `CredentialLogin(credential=b"")`, cleanup
- Exited rc!=0 → return `LoginError(code="auth_failed", message=<stderr>)`, cleanup

### Step 1: Write tests (see full test file in Task 5 notes below)

Tests cover:
- `detect_finds_cli` with subprocess mocks
- `supported_login_flows == frozenset({"api_key", "oauth_device"})`
- `login_api_key` returns `CredentialLogin`
- `login_oauth_parses_verification_uri` — mock `asyncio.create_subprocess_exec` to return a FakeProc whose stdout StreamReader is fed a simulated CLI greeting. Assert `OAuthDeviceLogin` with parsed URI and code.
- `poll_login_returns_complete_on_success` — inject a FakeProc with `returncode=0` into `backend._oauth_procs[handle]`, assert `CredentialLogin`
- `poll_login_returns_pending_when_still_running` — inject `returncode=None`, assert `OAuthDeviceLogin`
- `poll_login_returns_error_on_subprocess_failure` — inject `returncode=1` + a stderr StreamReader fed with "device code expired", assert `LoginError(code="auth_failed")`

### Step 2: Write `backends/gemini.py`

Structure:
- `kind = "gemini"`, `_CLI_NAME = "gemini"`, `_ISOLATION_ENV_VAR = "GEMINI_CLI_HOME"`
- `supported_login_flows = frozenset({"api_key", "oauth_device"})`
- Instance state: `self._oauth_procs: dict[str, asyncio.subprocess.Process]` and `self._oauth_challenges: dict[str, dict[str, str]]`
- Module-level regexes:
  ```python
  _URI_RE = re.compile(
      r"https://[^\s]+/device/usercode|https://accounts\.google\.com/o/oauth2/device[^\s]*",
  )
  _CODE_RE = re.compile(r"\b([A-Z0-9]{4}-[A-Z0-9]{4})\b")
  ```
- `detect()` same shape as ClaudeBackend.detect
- `login(flow, *, isolation_dir)`:
  - `api_key` → validate input, return `CredentialLogin`
  - `oauth_device` → call `_start_oauth_device(isolation_dir)`
  - else → `LoginError(code="unsupported_flow", ...)`
- `_start_oauth_device(isolation_dir)`:
  - `shutil.which(self._CLI_NAME)` — if None, `LoginError(code="cli_missing", ...)`
  - mkdir isolation_dir
  - spawn subprocess: `[path, "auth", "login"]` with env `{GEMINI_CLI_HOME: str(isolation_dir), **os.environ}`
  - `asyncio.wait_for(proc.stdout.read(2048), timeout=10.0)` — on timeout, kill + `LoginError(code="timeout")`
  - Parse text with `_URI_RE` and `_CODE_RE` — on parse failure, kill + `LoginError(code="parse_failed")`
  - Generate `handle = new_id("oauth")`; store `self._oauth_procs[handle] = proc` and `self._oauth_challenges[handle] = {...}`
  - Return `OAuthDeviceLogin(verification_uri, user_code, expires_at=now+15min, handle)`
- `poll_login(handle, *, isolation_dir)`:
  - Look up proc in `self._oauth_procs`; missing → `LoginError(code="unknown_handle")`
  - `proc.returncode is None` → re-emit `OAuthDeviceLogin` from `self._oauth_challenges[handle]`
  - `proc.returncode == 0` → cleanup, return `CredentialLogin(credential=b"")`
  - `proc.returncode != 0` → read stderr (with short timeout), cleanup, return `LoginError(code="auth_failed", message=<stderr>)`
- `validate(credential, *, isolation_dir)`:
  - `shutil.which` check
  - build env: `{GEMINI_CLI_HOME: str(isolation_dir), **os.environ}` plus `GEMINI_API_KEY` if credential is non-empty
  - run `[path, "auth", "status"]`
  - return rc==0
- `list_models(credential, *, isolation_dir)`:
  - Same env as validate
  - run `[path, "models", "list", "--json"]`
  - parse JSON → list[Model]
  - return [] on failure
- `chat`/`pty` raise NotImplementedError
- Helper `_env(credential, isolation_dir)` and `_run(spec)` following ClaudeBackend's pattern
- Private `_cleanup_handle(handle)` pops both dicts

### Step 3: Update `backends/__init__.py`

```python
from .claude import ClaudeBackend
from .codex import CodexBackend
from .gemini import GeminiBackend
from .opencode import OpenCodeBackend

__all__ = ["ClaudeBackend", "CodexBackend", "GeminiBackend", "OpenCodeBackend"]
```

(`CodexBackend` lands in Task 6. If Task 5 is committed before Task 6, create a one-line stub `codex.py` with `class CodexBackend: pass` so the import doesn't fail. Task 6 fills it in.)

### Step 4: Run + commit

```
uv run pytest packages/core/tests/test_gemini_backend.py -v
git add packages/core/src/ai_accounts_core/backends/gemini.py \
         packages/core/src/ai_accounts_core/backends/__init__.py \
         packages/core/src/ai_accounts_core/backends/codex.py \
         packages/core/tests/test_gemini_backend.py
git commit -m "feat(core): add GeminiBackend (api_key + oauth_device)"
```

---

## Task 6: CodexBackend

**Files:**
- Modify: `packages/core/src/ai_accounts_core/backends/codex.py` (replace stub with real impl)
- Create: `packages/core/tests/test_codex_backend.py`

Structurally similar to GeminiBackend with these differences:
- `kind = "codex"`, `_CLI_NAME = "codex"`, `_ISOLATION_ENV_VAR = "CODEX_HOME"`
- API key env var: `OPENAI_API_KEY`
- OAuth CLI invocation: `codex auth login` (verify with `codex --help` — if different, adapt)
- URL regex should match OpenAI's device code URL (`https://platform.openai.com/activate` or similar — adapt once you see real CLI output)
- Code regex: OpenAI device codes are typically `XXXX-XXXX` alphanumeric

Tests mirror the Gemini tests with codex-specific fixtures.

### Commit

```
git add packages/core/src/ai_accounts_core/backends/codex.py packages/core/tests/test_codex_backend.py
git commit -m "feat(core): add CodexBackend (api_key + oauth_device)"
```

---

# Part C — Onboarding + routes

## Task 7: OnboardingService

**Files:**
- Create: `packages/core/src/ai_accounts_core/services/onboarding.py`
- Modify: `packages/core/src/ai_accounts_core/services/__init__.py`
- Create: `packages/core/tests/test_onboarding_service.py`

### Design

Wraps `AccountService` to drive a multi-step wizard state machine. State transitions:

1. `WELCOME` — initial (via `start()`, creates onboarding row)
2. `DETECT` — scan installed CLIs (via `detect_all(id)`)
3. `PICK_BACKEND` → `LOGIN` — user selects a kind (via `pick_kind(id, kind, display_name)`), service creates the actual backend row
4. `LOGIN` → `VALIDATE` (via `begin_login(id, flow_kind, inputs)` + `poll_login(id, handle)`) — completes when the credential is persisted
5. `DONE` (via `finalize(id)`) — calls `AccountService.validate` on the created backend

Multiple onboarding sessions can exist concurrently, keyed by `onboarding_id` (prefix `onb-`). State persisted through `OnboardingRepository` (exists from Phase 1).

### Public API

```python
class OnboardingService:
    def __init__(
        self,
        *,
        storage: StorageProtocol,
        accounts: AccountService,
        backend_kinds: tuple[str, ...],
    ) -> None: ...

    async def start(self) -> OnboardingState: ...
    async def get(self, onboarding_id: str) -> OnboardingState: ...
    async def detect_all(self, onboarding_id: str) -> dict[str, DetectResult]: ...
    async def pick_kind(self, onboarding_id: str, kind: str, *, display_name: str) -> Backend: ...
    async def begin_login(self, onboarding_id: str, *, flow_kind: str, inputs: dict[str, str]) -> LoginResponse: ...
    async def poll_login(self, onboarding_id: str, *, handle: str) -> LoginResponse: ...
    async def finalize(self, onboarding_id: str) -> OnboardingState: ...
```

Add `OnboardingNotFound` error class.

Also add `AccountService.available_kinds()` and `_impl_for(kind)` (mentioned in Task 4) so OnboardingService can call `detect` on each kind without reaching into `_backend_impls` directly.

### Step 1: Write tests

Fixture spins up `AccountService` + `OnboardingService` with FakeStorage + FakeVault + FakeBackend and `tmp_path / "backend_dirs"` as isolation base.

Tests cover:
- `test_start_returns_welcome_state` — starts, asserts `current_step == WELCOME` and id starts with `onb-`
- `test_detect_transitions_to_pick_backend` — after detect, state is PICK_BACKEND and results include "fake"
- `test_pick_kind_creates_backend_and_transitions_to_login` — after pick, state is LOGIN with `created_backend_id` set
- `test_begin_login_api_key_happy_path` — login returns kind=complete
- `test_finalize_validates_and_transitions_to_done`
- `test_oauth_polling_through_onboarding` — full oauth flow: begin_login pending → poll pending → poll complete → finalize → DONE
- `test_pick_kind_unknown_kind_raises` — raises `BackendKindUnknown`

### Step 2: Write `services/onboarding.py`

Key pieces:
- Constructor stores `_storage`, `_accounts`, `_backend_kinds`.
- `start()` creates `OnboardingState(id=new_id("onb"), current_step=WELCOME)` and persists via `(await storage.onboarding()).put(state)`.
- `get(id)` reads from repo; raises `OnboardingNotFound` if None.
- `detect_all(id)` iterates `self._backend_kinds`, calls `self._accounts._impl_for(kind).detect()`, persists updated state with `current_step=PICK_BACKEND`, returns results dict.
- `pick_kind(id, kind, display_name)`:
  - Raise `BackendKindUnknown` if kind not in `self._backend_kinds`
  - `backend = await self._accounts.create(kind, display_name=display_name)`
  - Persist updated state with `current_step=LOGIN, selected_backend_kind=kind, created_backend_id=backend.id`
  - Return backend
- `begin_login(id, flow_kind, inputs)` — delegates to `self._accounts.login(state.created_backend_id, ...)`. Raises `BackendNotFound` if `created_backend_id is None`.
- `poll_login(id, handle)` — delegates to `self._accounts.poll_login`.
- `finalize(id)` — `await self._accounts.validate(state.created_backend_id)`; on success persists `DONE`, on exception persists `VALIDATE` + error and re-raises.

### Step 3: Update `services/__init__.py` to export `OnboardingService`, `OnboardingNotFound`, `LoginResponse`

### Step 4: Run + commit

```
uv run pytest packages/core/tests/test_onboarding_service.py -v
git add packages/core/src/ai_accounts_core/services \
         packages/core/tests/test_onboarding_service.py
git commit -m "feat(core): add OnboardingService state machine"
```

---

## Task 8: Litestar routes — updated login + poll endpoint

**Files:**
- Modify: `packages/litestar/src/ai_accounts_litestar/dto.py`
- Modify: `packages/litestar/src/ai_accounts_litestar/routes/backends.py`
- Modify: `packages/litestar/tests/test_backends_routes.py`

### Step 1: Add DTOs

`dto.py` additions:

```python
from datetime import datetime
from typing import Literal


class OAuthDeviceLoginDTO(msgspec.Struct, kw_only=True):
    verification_uri: str
    user_code: str
    expires_at: datetime
    handle: str


class LoginResponseDTO(msgspec.Struct, kw_only=True):
    kind: Literal["complete", "pending"]
    backend: BackendDTO | None = None
    oauth: OAuthDeviceLoginDTO | None = None

    @classmethod
    def from_service(cls, response) -> "LoginResponseDTO":
        from ai_accounts_core.services.accounts import LoginResponse
        assert isinstance(response, LoginResponse)
        backend_dto = BackendDTO.from_domain(response.backend) if response.backend else None
        oauth_dto = None
        if response.oauth is not None:
            oauth_dto = OAuthDeviceLoginDTO(
                verification_uri=response.oauth.verification_uri,
                user_code=response.oauth.user_code,
                expires_at=response.oauth.expires_at,
                handle=response.oauth.handle,
            )
        return cls(kind=response.kind, backend=backend_dto, oauth=oauth_dto)


class PollLoginRequest(msgspec.Struct, kw_only=True):
    handle: str
```

### Step 2: Update the `login` handler + add `poll_login`

In `routes/backends.py`:

```python
@post("/{backend_id:str}/login")
async def login(
    self, backend_id: str, data: LoginRequest, account_service: AccountService
) -> LoginResponseDTO:
    response = await account_service.login(
        backend_id, flow_kind=data.flow_kind, inputs=data.inputs
    )
    return LoginResponseDTO.from_service(response)


@post("/{backend_id:str}/login/poll")
async def poll_login(
    self, backend_id: str, data: PollLoginRequest, account_service: AccountService
) -> LoginResponseDTO:
    response = await account_service.poll_login(backend_id, handle=data.handle)
    return LoginResponseDTO.from_service(response)
```

### Step 3: Update existing tests + add new ones

Update `test_login_validate_happy_path`: assert on the new LoginResponseDTO shape:

```python
def test_login_api_key_returns_complete(client):
    created = client.post("/api/v1/backends/", json={"kind": "fake", "display_name": "T"}).json()
    login = client.post(
        f"/api/v1/backends/{created['id']}/login",
        json={"flow_kind": "api_key", "inputs": {}},
    )
    assert login.status_code == 201
    body = login.json()
    assert body["kind"] == "complete"
    assert body["backend"]["status"] == "validating"
    assert body["oauth"] is None
```

Add new tests:
- `test_login_oauth_returns_pending_with_challenge` — asserts `body["kind"] == "pending"`, `body["oauth"]["user_code"] == "FAKE-1234"`, handle present
- `test_poll_login_eventually_completes` — start oauth, first poll pending, second poll complete

### Step 4: Run + commit

```
uv run pytest packages/litestar -v
git add packages/litestar/src/ai_accounts_litestar/dto.py \
         packages/litestar/src/ai_accounts_litestar/routes/backends.py \
         packages/litestar/tests/test_backends_routes.py
git commit -m "feat(litestar): LoginResponseDTO and /login/poll endpoint"
```

---

## Task 9: Litestar routes — /api/v1/onboarding

**Files:**
- Create: `packages/litestar/src/ai_accounts_litestar/routes/onboarding.py`
- Modify: `packages/litestar/src/ai_accounts_litestar/dto.py`
- Modify: `packages/litestar/src/ai_accounts_litestar/app.py`
- Modify: `packages/litestar/src/ai_accounts_litestar/errors.py`
- Create: `packages/litestar/tests/test_onboarding_routes.py`

### Routes

- `POST /api/v1/onboarding` → start
- `GET /api/v1/onboarding/{id}` → get state
- `POST /api/v1/onboarding/{id}/detect` → detect all
- `POST /api/v1/onboarding/{id}/pick` → pick kind (body: `{kind, display_name}`)
- `POST /api/v1/onboarding/{id}/login` → begin login (body: `{flow_kind, inputs}`)
- `POST /api/v1/onboarding/{id}/login/poll` → poll (body: `{handle}`)
- `POST /api/v1/onboarding/{id}/finalize` → finalize

### Step 1: Add DTOs

```python
class OnboardingStateDTO(msgspec.Struct, kw_only=True):
    id: str
    current_step: str
    selected_backend_kind: str | None = None
    created_backend_id: str | None = None
    error: str | None = None

    @classmethod
    def from_domain(cls, state) -> "OnboardingStateDTO":
        return cls(
            id=state.id,
            current_step=state.current_step.value,
            selected_backend_kind=state.selected_backend_kind,
            created_backend_id=state.created_backend_id,
            error=state.error,
        )


class PickKindRequest(msgspec.Struct, kw_only=True):
    kind: str
    display_name: str


class DetectResultsDTO(msgspec.Struct, kw_only=True):
    results: dict[str, DetectResultDTO]
```

### Step 2: Write `routes/onboarding.py`

Standard Litestar Controller with 7 handlers (start/get/detect/pick/login/login-poll/finalize), each delegating to `onboarding_service: OnboardingService` DI. Return appropriate DTOs from each handler.

### Step 3: Update `app.py`

- Import `OnboardingController` and `OnboardingService`
- After creating `account_service`, also create `onboarding_service = OnboardingService(storage=config.storage, accounts=account_service, backend_kinds=tuple(impls.keys()))`
- Add to dependencies: `"onboarding_service": Provide(lambda: onboarding_service, sync_to_thread=False)`
- Add `OnboardingController` to `route_handlers`

### Step 4: Update `errors.py` to map `onboarding_not_found` → 404

Add to `_STATUS_BY_CODE`:

```python
"login_flow_unsupported": 400,
"onboarding_not_found": 404,
```

### Step 5: Write route tests

Tests (all use the same `client` fixture as `test_backends_routes.py`, registered via `create_app`):

- `test_start_onboarding` — POST `/api/v1/onboarding/`, assert 201, body `{id, current_step: "welcome"}`
- `test_full_happy_path` — start → detect → pick → login (api_key) → finalize, assert final `current_step == "done"`
- `test_oauth_happy_path` — start → detect → pick → login (oauth_device) → poll → poll → finalize, asserting each intermediate response shape
- `test_onboarding_not_found` — GET `/api/v1/onboarding/onb-nope`, assert 404 with code `onboarding_not_found`

### Step 6: Run + commit

```
uv run pytest packages/litestar -v
git add packages/litestar/src/ai_accounts_litestar/routes/onboarding.py \
         packages/litestar/src/ai_accounts_litestar/dto.py \
         packages/litestar/src/ai_accounts_litestar/app.py \
         packages/litestar/src/ai_accounts_litestar/errors.py \
         packages/litestar/tests/test_onboarding_routes.py
git commit -m "feat(litestar): add /api/v1/onboarding routes"
```

---

# Part D — Frontend

## Task 10: ts-core client updates + regenerated OpenAPI

**Files:**
- Regenerate: `packages/ts-core/src/client/openapi.json`, `generated.ts` (via `just codegen`)
- Modify: `packages/ts-core/src/client/index.ts` — new types + methods
- Modify: `packages/ts-core/src/index.ts` — exports
- Modify: `packages/ts-core/src/machines/accountWizard.ts` — handle pending login response
- Modify: `packages/ts-core/tests/client.test.ts` — new tests

### Step 1: Regenerate OpenAPI

```
cd ~/Developer/Projects/ai-accounts
just codegen
git diff packages/ts-core/src/client/
```

Expected: `generated.ts` now contains paths for `/api/v1/backends/{id}/login/poll`, `/api/v1/onboarding`, `/api/v1/onboarding/{id}`, and the `LoginResponseDTO`, `OnboardingStateDTO`, `OAuthDeviceLoginDTO` types.

### Step 2: Extend `AiAccountsClient`

Add new types (LoginResponseDTO, OAuthDeviceLoginDTO, OnboardingStateDTO, DetectResultsDTO) as TypeScript interfaces in `index.ts`. Then add methods:

```typescript
async loginBackend(
  id: string,
  flowKind: string,
  inputs: Record<string, string>
): Promise<LoginResponseDTO> {
  return this.postAction<LoginResponseDTO>(id, 'login', { flow_kind: flowKind, inputs });
}

async pollBackendLogin(id: string, handle: string): Promise<LoginResponseDTO> {
  return this.postAction<LoginResponseDTO>(id, 'login/poll', { handle });
}

async startOnboarding(): Promise<OnboardingStateDTO> {
  const r = await this._fetch(`${this.baseUrl}/api/v1/onboarding/`, {
    method: 'POST',
    headers: this.headers(),
  });
  if (!r.ok) throw await toError(r);
  return (await r.json()) as OnboardingStateDTO;
}

async getOnboarding(id: string): Promise<OnboardingStateDTO> { /* GET /api/v1/onboarding/{id} */ }

async detectForOnboarding(id: string): Promise<DetectResultsDTO> {
  return this.onboardingAction<DetectResultsDTO>(id, 'detect');
}

async pickOnboardingKind(id: string, kind: string, displayName: string): Promise<BackendDTO> {
  return this.onboardingAction<BackendDTO>(id, 'pick', { kind, display_name: displayName });
}

async beginOnboardingLogin(id: string, flowKind: string, inputs: Record<string, string>): Promise<LoginResponseDTO> {
  return this.onboardingAction<LoginResponseDTO>(id, 'login', { flow_kind: flowKind, inputs });
}

async pollOnboardingLogin(id: string, handle: string): Promise<LoginResponseDTO> {
  return this.onboardingAction<LoginResponseDTO>(id, 'login/poll', { handle });
}

async finalizeOnboarding(id: string): Promise<OnboardingStateDTO> {
  return this.onboardingAction<OnboardingStateDTO>(id, 'finalize');
}

private async onboardingAction<T>(id: string, action: string, body?: unknown): Promise<T> {
  const r = await this._fetch(
    `${this.baseUrl}/api/v1/onboarding/${encodeURIComponent(id)}/${action}`,
    {
      method: 'POST',
      headers: this.headers(),
      ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
    }
  );
  if (!r.ok) throw await toError(r);
  return (await r.json()) as T;
}
```

**Breaking change:** `loginBackend` return type changes from `unknown` (v0.1.0) to `LoginResponseDTO`. Document in changeset.

### Step 3: Update `accountWizard` state machine

`submitCredential` needs to handle the new LoginResponseDTO shape. If `response.kind === "pending"`, the wizard doesn't handle oauth in its current form — transition to `error` with a message pointing users at `OnboardingFlow`:

```typescript
async submitCredential(flowKind, inputs) {
  if (!backend) {
    state = 'error';
    error = 'no backend in progress';
    emit();
    return;
  }
  state = 'validating';
  emit();
  try {
    const response = await opts.client.loginBackend(backend.id, flowKind, inputs);
    if (response.kind === 'pending') {
      state = 'error';
      error = 'OAuth flows are not supported in AccountWizard; use OnboardingFlow';
      emit();
      return;
    }
    backend = (await opts.client.validateBackend(backend.id)) as BackendDTO;
    state = 'done';
  } catch (e) {
    state = 'error';
    error = (e as { message?: string }).message ?? 'validation failed';
  }
  emit();
},
```

### Step 4: Update `src/index.ts` exports

```typescript
export type {
  ClientOptions,
  ApiError,
  BackendDTO,
  DetectResultDTO,
  LoginResponseDTO,
  OAuthDeviceLoginDTO,
  OnboardingStateDTO,
  DetectResultsDTO,
} from './client';
```

### Step 5: Write tests

Add to `tests/client.test.ts`:
- `loginBackend returns LoginResponseDTO` — mock fetch returning `{kind: "complete", backend: {...}, oauth: null}`
- `loginBackend handles pending` — mock returning `{kind: "pending", backend: null, oauth: {...}}`
- `pollBackendLogin` — similar
- `startOnboarding creates session`
- `finalizeOnboarding` — mock returning `{id, current_step: "done"}`

### Step 6: Run + commit

```
pnpm --filter @ai-accounts/ts-core test
pnpm --filter @ai-accounts/ts-core typecheck
git add packages/ts-core
git commit -m "feat(ts-core)!: LoginResponseDTO + onboarding client methods"
```

---

## Task 11: onboardingFlow state machine

**Files:**
- Create: `packages/ts-core/src/machines/onboardingFlow.ts`
- Create: `packages/ts-core/tests/onboardingFlow.test.ts`
- Modify: `packages/ts-core/src/index.ts`

### Design

```typescript
export type OnboardingMachineState =
  | 'idle'
  | 'started'
  | 'detecting'
  | 'picking_kind'
  | 'entering_credential'
  | 'oauth_challenge'
  | 'oauth_polling'
  | 'validating'
  | 'done'
  | 'error';

export interface OnboardingFlowMachine {
  readonly state: OnboardingMachineState;
  readonly kinds: Array<{ id: string; detection: DetectResultDTO }> | undefined;
  readonly selectedKind: string | undefined;
  readonly supportedFlows: string[] | undefined;
  readonly oauthChallenge: OAuthDeviceLoginDTO | undefined;
  readonly createdBackendId: string | undefined;
  readonly error: string | undefined;

  subscribe(listener: () => void): () => void;
  start(): Promise<void>;
  detect(): Promise<void>;
  pickKind(kind: string): Promise<void>;
  submitApiKey(apiKey: string): Promise<void>;
  submitOauthDevice(): Promise<void>;
  cancelOAuth(): void;
  reset(): void;
}

export interface CreateOnboardingFlowOptions {
  client: AiAccountsClient;
  supportedFlowsByKind?: Record<string, string[]>;
  pollIntervalMs?: number;  // default 2000
}
```

Transitions:
- `idle` → `started` (via `start()`, calls `client.startOnboarding()`)
- `started` → `detecting` (via `detect()`)
- `detecting` → `picking_kind` (after detect results return, stored as `kinds`)
- `picking_kind` → `entering_credential` (via `pickKind(kind)`, calls `/pick`)
- `entering_credential` → `validating` (via `submitApiKey(key)` → call `beginOnboardingLogin(api_key)` → `finalizeOnboarding` → `done`)
- `entering_credential` → `oauth_challenge` (via `submitOauthDevice()`) → `oauth_polling` (background setTimeout chain) → `validating` → `done`
- any state → `error` on failure (persisted via `error` ref)
- `reset()` → `idle`, clears all state

OAuth polling: use a recursive `setTimeout` chain (not `setInterval`) to avoid overlapping calls. Cancel via a `cancelled: boolean` flag captured in the closure. 15-minute timeout via `Date.now()` comparison.

### Step 1: Write tests

10 tests covering: start, detect, pickKind, submitApiKey happy, submitApiKey failure, submitOauthDevice → challenge shown, oauth polling → complete, oauth cancel, reset, 15-minute timeout (simulate via a very short pollIntervalMs + mock Date.now()).

### Step 2: Implement

Same closure + listener pattern as `createAccountWizard`. Start the onboarding session lazily (client must be ready). After `start()`, cache the `onboarding_id` in closure state. `submitOauthDevice()` kicks off the poll loop:

```typescript
async function submitOauthDevice() {
  if (!onboardingId) {
    state = 'error';
    error = 'not started';
    emit();
    return;
  }
  state = 'oauth_challenge';
  emit();
  try {
    const response = await opts.client.beginOnboardingLogin(onboardingId, 'oauth_device', {});
    if (response.kind !== 'pending' || !response.oauth) {
      state = 'error';
      error = 'expected pending OAuth response';
      emit();
      return;
    }
    oauthChallenge = response.oauth;
    state = 'oauth_polling';
    emit();
    schedulePoll(response.oauth.handle);
  } catch (e) {
    state = 'error';
    error = (e as Error).message ?? 'OAuth start failed';
    emit();
  }
}

function schedulePoll(handle: string) {
  const intervalMs = opts.pollIntervalMs ?? 2000;
  const deadline = Date.now() + 15 * 60 * 1000;
  const tick = async () => {
    if (cancelled || state !== 'oauth_polling') return;
    if (Date.now() > deadline) {
      state = 'error';
      error = 'OAuth login timed out';
      emit();
      return;
    }
    try {
      const result = await opts.client.pollOnboardingLogin(onboardingId!, handle);
      if (result.kind === 'complete') {
        state = 'validating';
        emit();
        const final = await opts.client.finalizeOnboarding(onboardingId!);
        createdBackendId = final.created_backend_id ?? undefined;
        state = 'done';
        emit();
        return;
      }
      setTimeout(tick, intervalMs);
    } catch (e) {
      state = 'error';
      error = (e as Error).message ?? 'polling error';
      emit();
    }
  };
  setTimeout(tick, intervalMs);
}
```

### Step 3: Re-export from `src/index.ts`

```typescript
export { createOnboardingFlow } from './machines/onboardingFlow';
export type {
  OnboardingFlowMachine,
  OnboardingMachineState,
  CreateOnboardingFlowOptions,
} from './machines/onboardingFlow';
```

### Step 4: Run + commit

```
pnpm --filter @ai-accounts/ts-core test
git add packages/ts-core/src/machines/onboardingFlow.ts \
         packages/ts-core/src/index.ts \
         packages/ts-core/tests/onboardingFlow.test.ts
git commit -m "feat(ts-core): add onboardingFlow state machine"
```

---

## Task 12: vue-headless useOnboarding composable

**Files:**
- Create: `packages/vue-headless/src/useOnboarding.ts`
- Create: `packages/vue-headless/tests/useOnboarding.test.ts`
- Modify: `packages/vue-headless/src/index.ts`

Same pattern as `useAccountWizard`: wrap `createOnboardingFlow` in Vue refs synced via `machine.subscribe()`.

### Step 1: Write `useOnboarding.ts`

```typescript
import { ref, type Ref } from 'vue';
import {
  createOnboardingFlow,
  type AiAccountsClient,
  type CreateOnboardingFlowOptions,
  type DetectResultDTO,
  type OAuthDeviceLoginDTO,
  type OnboardingFlowMachine,
  type OnboardingMachineState,
} from '@ai-accounts/ts-core';

export interface UseOnboardingOptions {
  client: AiAccountsClient;
  pollIntervalMs?: number;
}

export interface UseOnboardingReturn {
  state: Ref<OnboardingMachineState>;
  kinds: Ref<Array<{ id: string; detection: DetectResultDTO }> | undefined>;
  selectedKind: Ref<string | undefined>;
  supportedFlows: Ref<string[] | undefined>;
  oauthChallenge: Ref<OAuthDeviceLoginDTO | undefined>;
  createdBackendId: Ref<string | undefined>;
  error: Ref<string | undefined>;
  start: () => Promise<void>;
  detect: () => Promise<void>;
  pickKind: (kind: string) => Promise<void>;
  submitApiKey: (apiKey: string) => Promise<void>;
  submitOauthDevice: () => Promise<void>;
  cancelOAuth: () => void;
  reset: () => void;
}

export function useOnboarding(options: UseOnboardingOptions): UseOnboardingReturn {
  const machineOpts: CreateOnboardingFlowOptions = {
    client: options.client,
    ...(options.pollIntervalMs !== undefined ? { pollIntervalMs: options.pollIntervalMs } : {}),
  };
  const machine: OnboardingFlowMachine = createOnboardingFlow(machineOpts);

  const state = ref(machine.state);
  const kinds = ref(machine.kinds);
  const selectedKind = ref(machine.selectedKind);
  const supportedFlows = ref(machine.supportedFlows);
  const oauthChallenge = ref(machine.oauthChallenge);
  const createdBackendId = ref(machine.createdBackendId);
  const error = ref(machine.error);

  machine.subscribe(() => {
    state.value = machine.state;
    kinds.value = machine.kinds;
    selectedKind.value = machine.selectedKind;
    supportedFlows.value = machine.supportedFlows;
    oauthChallenge.value = machine.oauthChallenge;
    createdBackendId.value = machine.createdBackendId;
    error.value = machine.error;
  });

  return {
    state, kinds, selectedKind, supportedFlows, oauthChallenge, createdBackendId, error,
    start: () => machine.start(),
    detect: () => machine.detect(),
    pickKind: (k) => machine.pickKind(k),
    submitApiKey: (k) => machine.submitApiKey(k),
    submitOauthDevice: () => machine.submitOauthDevice(),
    cancelOAuth: () => machine.cancelOAuth(),
    reset: () => machine.reset(),
  };
}
```

### Step 2: Write 3 tests

- `starts in idle state`
- `reactively reflects full api-key happy path`
- `shows oauth challenge then polls to complete` (use very short `pollIntervalMs` + mock fetch)

### Step 3: Update `src/index.ts` exports + bump version to `0.2.0`

### Step 4: Run + commit

```
pnpm --filter @ai-accounts/vue-headless test
git add packages/vue-headless
git commit -m "feat(vue-headless): add useOnboarding composable"
```

---

## Task 13: vue-styled OnboardingFlow component

**Files:**
- Create: `packages/vue-styled/src/components/OnboardingFlow.vue`
- Create: `packages/vue-styled/tests/OnboardingFlow.test.ts`
- Modify: `packages/vue-styled/src/index.ts`

### Design

8-step Vue component with CSS-var theming, built on `useOnboarding`.

Script setup:

```vue
<script setup lang="ts">
import { ref, computed } from 'vue';
import { useOnboarding } from '@ai-accounts/vue-headless';
import type { AiAccountsClient } from '@ai-accounts/ts-core';

const props = defineProps<{
  client: AiAccountsClient;
  kinds?: Array<{ id: string; display: string }>;
  supportedFlowsByKind?: Record<string, string[]>;
}>();

const emit = defineEmits<{
  done: [backendId: string];
  cancel: [];
}>();

const wiz = useOnboarding({ client: props.client });
const apiKey = ref('');
const loginTab = ref<'api_key' | 'oauth_device'>('api_key');

const DEFAULT_KINDS = [
  { id: 'claude', display: 'Claude' },
  { id: 'opencode', display: 'OpenCode' },
  { id: 'gemini', display: 'Gemini' },
  { id: 'codex', display: 'Codex' },
];

const DEFAULT_SUPPORTED_FLOWS: Record<string, string[]> = {
  claude: ['api_key'],
  opencode: ['api_key'],
  gemini: ['api_key', 'oauth_device'],
  codex: ['api_key', 'oauth_device'],
};

const kinds = computed(() => props.kinds ?? DEFAULT_KINDS);
const supportedFlowsByKind = computed(() => props.supportedFlowsByKind ?? DEFAULT_SUPPORTED_FLOWS);

const supportedFlowsForSelected = computed(() => {
  const k = wiz.selectedKind.value;
  if (!k) return ['api_key'];
  return supportedFlowsByKind.value[k] ?? ['api_key'];
});

async function onStart() {
  await wiz.start();
  await wiz.detect();
}

async function onPick(kind: string) {
  await wiz.pickKind(kind);
  // Default tab to the first supported flow for the chosen kind
  loginTab.value = (supportedFlowsForSelected.value[0] ?? 'api_key') as 'api_key' | 'oauth_device';
}

async function onSubmitApiKey() {
  await wiz.submitApiKey(apiKey.value);
  if (wiz.state.value === 'done' && wiz.createdBackendId.value) {
    emit('done', wiz.createdBackendId.value);
  }
}

async function onSubmitOauth() {
  await wiz.submitOauthDevice();
  // Completion is async — emit will fire later via watcher (see below)
}

// Watch for "done" state to emit completion event (covers both paths)
import { watch } from 'vue';
watch(wiz.state, (s) => {
  if (s === 'done' && wiz.createdBackendId.value) {
    emit('done', wiz.createdBackendId.value);
  }
});

function onRetry() {
  wiz.reset();
}

function onCopyCode() {
  const code = wiz.oauthChallenge.value?.user_code;
  if (code && typeof navigator !== 'undefined' && navigator.clipboard) {
    void navigator.clipboard.writeText(code);
  }
}
</script>
```

Template branches (rendered via `v-if`/`v-else-if` on `wiz.state.value`):

1. **`idle`** — welcome card with "Get started" button calling `onStart`
2. **`detecting`** / **`started`** — "Detecting installed CLIs…" status
3. **`picking_kind`** — grid of kind cards showing installed status (use `wiz.kinds.value` — fall back to `kinds.value` if undefined). Clicking a card calls `onPick(k.id)`. Disable cards for CLIs that aren't installed.
4. **`entering_credential`** — tabbed UI. Tabs: "API key" and "Login with browser" (only show each tab if it's in `supportedFlowsForSelected`). Depending on `loginTab.value`:
   - `api_key`: input + submit button → `onSubmitApiKey`
   - `oauth_device`: button "Start browser login" → `onSubmitOauth`
5. **`oauth_challenge`** / **`oauth_polling`** — show the verification URL (as a clickable `<a target="_blank" rel="noopener">`), the user_code with a "Copy" button, and "Waiting for you to sign in in your browser…" spinner. Also a "Cancel" button → `wiz.cancelOAuth`.
6. **`validating`** — spinner "Validating…"
7. **`done`** — success slot
8. **`error`** — `{{ wiz.error.value }}` + "Try again" button → `onRetry`

Scoped `<style>` block uses existing `--aia-*` vars. Classes: `.aia-onboarding`, `.aia-onboarding__kind-grid`, `.aia-kind-card`, `.aia-kind-card--installed`, `.aia-kind-card--missing`, `.aia-onboarding__tabs`, `.aia-tab`, `.aia-tab--active`, `.aia-onboarding__oauth-challenge`, `.aia-code-display`, `.aia-copy-btn`, etc.

### Step 1-2: Write component as above

### Step 3: Write 3 tests

- `test_renders_welcome_initially` — mount, assert "Get started" text
- `test_happy_api_key_path` — mock client, click Get started, wait, click Claude card, fill api key, submit, assert done emit
- `test_oauth_flow_shows_challenge` — mock client returning pending, assert verification_uri + user_code rendered in DOM

### Step 4: Update `src/index.ts`

```typescript
import './styles/tokens.css';

export { default as AccountWizard } from './components/AccountWizard.vue';
export { default as OnboardingFlow } from './components/OnboardingFlow.vue';

export const version = '0.2.0';
```

### Step 5: Run + commit

```
pnpm --filter @ai-accounts/vue-styled test
pnpm --filter @ai-accounts/vue-styled build
git add packages/vue-styled
git commit -m "feat(vue-styled): add OnboardingFlow component with oauth device flow UI"
```

---

## Task 14: AccountWizard compatibility update

**Files:**
- Modify: `packages/vue-styled/src/components/AccountWizard.vue`
- Modify: `packages/vue-styled/tests/AccountWizard.test.ts`

Task 10 already updated the ts-core state machine to surface an error when `loginBackend` returns `kind=pending`. This task makes the error message user-friendly in the component's error branch and adds a test.

Add a conditional hint in the error branch:

```vue
<div v-else-if="wiz.state.value === 'error'" class="aia-wizard__error">
  <p>{{ wiz.error.value }}</p>
  <p v-if="wiz.error.value?.includes('OAuth')" class="aia-wizard__hint">
    Try the full <code>&lt;OnboardingFlow&gt;</code> component instead — it supports browser login.
  </p>
  <button class="aia-btn" type="button" @click="onRetry">Try again</button>
</div>
```

Add one test: mock `loginBackend` to return `{kind: "pending", ...}`, exercise the flow, assert the hint is shown.

```
git add packages/vue-styled/src/components/AccountWizard.vue packages/vue-styled/tests/AccountWizard.test.ts
git commit -m "feat(vue-styled): clarify AccountWizard error when OAuth is attempted"
```

---

# Part E — Playground + release

## Task 15: Playground — use OnboardingFlow

**Files:**
- Modify: `apps/playground/src/App.vue`
- Modify: `apps/playground/server.py`

### Step 1: Update `server.py`

Add `GeminiBackend` and `CodexBackend` imports. Register all four backends. Add `backend_dirs_path=Path("./backend_dirs")`.

```python
from pathlib import Path

from ai_accounts_core.adapters.auth_noauth import NoAuth
from ai_accounts_core.adapters.storage_sqlite import SqliteStorage
from ai_accounts_core.adapters.vault_envkey import EnvKeyVault
from ai_accounts_core.backends import (
    ClaudeBackend,
    CodexBackend,
    GeminiBackend,
    OpenCodeBackend,
)
from ai_accounts_litestar.app import create_app
from ai_accounts_litestar.config import AiAccountsConfig

app = create_app(
    AiAccountsConfig(
        env="development",
        storage=SqliteStorage("./playground.db"),
        vault=EnvKeyVault.from_env(env="development"),
        auth=NoAuth(),
        backends=(
            ClaudeBackend(),
            OpenCodeBackend(),
            GeminiBackend(),
            CodexBackend(),
        ),
        backend_dirs_path=Path("./backend_dirs"),
    )
)


def main() -> None:
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=20000)


if __name__ == "__main__":
    main()
```

### Step 2: Update `App.vue`

Replace `AccountWizard` with `OnboardingFlow`. Same prop shape (`:client` + `@done`).

```vue
<script setup lang="ts">
import { ref } from 'vue';
import { AiAccountsClient } from '@ai-accounts/ts-core';
import { OnboardingFlow } from '@ai-accounts/vue-styled';

const client = new AiAccountsClient({ baseUrl: '' });
const doneId = ref<string | null>(null);

function onDone(id: string) {
  doneId.value = id;
}
</script>

<template>
  <main class="playground">
    <h1>ai-accounts playground</h1>
    <p class="intro">
      Full onboarding flow for AI backends. Tries Claude, OpenCode, Gemini,
      and Codex. Gemini and Codex support both API key and browser login.
    </p>
    <OnboardingFlow :client="client" @done="onDone" />
    <p v-if="doneId" class="created">
      Ready backend: <code>{{ doneId }}</code>
    </p>
  </main>
</template>
```

### Step 3: Smoke test

```
cd ~/Developer/Projects/ai-accounts
rm -f apps/playground/playground.db
rm -rf apps/playground/backend_dirs
pnpm --filter playground build
```

The build must succeed; we don't need to actually boot the server in this task.

### Step 4: Commit

```
git add apps/playground
git commit -m "feat(playground): use OnboardingFlow with all four backends"
```

---

## Task 16: Version bump to 0.2.0 + publish

**Files:**
- Create: `.changeset/ship-0-2-0.md`
- Modify: `packages/core/pyproject.toml`, `packages/litestar/pyproject.toml`
- Modify: `packages/core/src/ai_accounts_core/__init__.py`, `packages/litestar/src/ai_accounts_litestar/__init__.py`
- Create: `CHANGELOG.md` at repo root

### Step 1: Write changeset

`.changeset/ship-0-2-0.md`:

```markdown
---
"@ai-accounts/ts-core": minor
"@ai-accounts/vue-headless": minor
"@ai-accounts/vue-styled": minor
---

Add OnboardingFlow, Gemini + Codex backends with OAuth device flow, and per-account isolation directories.

BREAKING: BackendProtocol.login() now returns LoginResult (tagged union of CredentialLogin, OAuthDeviceLogin, LoginError) and takes isolation_dir: Path. All validate/list_models/chat/pty methods also require isolation_dir. New poll_login() method. AccountService constructor now requires isolation_base_dir. AiAccountsClient.loginBackend() TypeScript return type changes from unknown to LoginResponseDTO.
```

### Step 2: Bump versions

```
cd ~/Developer/Projects/ai-accounts
pnpm changeset version
# Then manually:
# - packages/core/pyproject.toml → version = "0.2.0"
# - packages/core/src/ai_accounts_core/__init__.py → __version__ = "0.2.0"
# - packages/litestar/pyproject.toml → version = "0.2.0"
# - packages/litestar/src/ai_accounts_litestar/__init__.py → __version__ = "0.2.0"
```

### Step 3: Write `CHANGELOG.md`

Include sections for 0.2.0 (Added / Changed BREAKING / Migration guide) and 0.1.0 (Initial release). See the "Migration guide" section below for third-party adapter authors.

```markdown
# Changelog

All notable changes to ai-accounts packages in this monorepo.

## 0.2.0 — 2026-04-11

### Added
- OnboardingService state machine (welcome → detect → pick → login → done), persisted via OnboardingRepository
- GeminiBackend with API key and OAuth device flow (driven via gemini auth login subprocess)
- CodexBackend with API key and OAuth device flow (driven via codex auth login subprocess)
- <OnboardingFlow> Vue component with tabbed API-key vs OAuth login, verification URL + copy-code UI, auto-polling
- useOnboarding Vue composable
- createOnboardingFlow TypeScript state machine in ts-core
- POST /api/v1/onboarding/* HTTP routes
- POST /api/v1/backends/{id}/login/poll HTTP route for OAuth polling
- Per-account isolation directories under AiAccountsConfig.backend_dirs_path (default ./backend_dirs)
- BackendProtocol.supported_login_flows: ClassVar[frozenset[str]]

### Changed (BREAKING)
- BackendProtocol.login() returns LoginResult (tagged union) instead of bytes
- BackendProtocol.login/validate/list_models/chat/pty all take a new isolation_dir: Path kwarg
- BackendProtocol.poll_login(handle, isolation_dir) added
- AccountService.__init__ requires isolation_base_dir: Path
- AccountService.login() returns LoginResponse (kind=complete|pending) instead of Backend
- AccountService.delete() cascades to the isolation directory (shutil.rmtree)
- AiAccountsClient.loginBackend() return type changes from unknown to LoginResponseDTO
- AiAccountsConfig gains backend_dirs_path: Path

### Migration guide
If you are a third-party author of a BackendProtocol implementation:
1. Add supported_login_flows: ClassVar[frozenset[str]] = frozenset({"api_key"}) to your class
2. Change method signatures to accept isolation_dir: Path as a keyword-only argument
3. Change login() to return CredentialLogin(credential=...) for API-key flows instead of returning bytes directly. Return LoginError(code, message) on validation failures — don't raise
4. Implement poll_login(handle, isolation_dir). For backends that only support synchronous flows, return LoginError(code="not_pollable", ...)
5. Use isolation_dir to isolate per-account CLI state. Set the appropriate env var (CLAUDE_CONFIG_DIR, GEMINI_CLI_HOME, CODEX_HOME, etc.) when invoking the CLI.

## 0.1.0 — 2026-04-11

Initial release. See Phase 0+1 plan for feature list.
```

### Step 4: Re-run codegen + full tests

```
just codegen
git diff --exit-code
uv run pytest
pnpm -r test
```

### Step 5: Commit + tag

```
git add -A
git commit -m "release: bump all packages to 0.2.0"
git tag v0.2.0
```

### Step 6: Publish

**STOP and ask the user before publishing.** Publishing is irreversible. Verify the user is ready and has credentials. For a subagent implementing this task, report back with:
- The commit hash
- The tag
- A "ready to publish, awaiting user confirmation" status
- Do NOT run `uv publish`, `pnpm changeset publish`, or `git push` without explicit user go-ahead

The user will handle the publish step.

---

# Part F — Agented migration

All Part F tasks happen inside `~/Developer/Projects/Agented-ai-accounts-migration/` on branch `feat/ai-accounts-phase-1`. The branch was created in Phase 1 and already has 8 commits. Phase 2's Agented work adds more commits to that same branch.

## Task 17: Rebuild + reinstall ai-accounts in Agented

**Files (worktree):**
- Modify: `backend/pyproject.toml`, `backend/uv.lock`
- Modify: `frontend/package.json`, `frontend/package-lock.json`
- Modify: `frontend/src/services/api/backends.ts` (fix type error from ts-core breaking change)

### Step 1: Rebuild JS tarballs

```
cd ~/Developer/Projects/ai-accounts
pnpm -r build
rm -rf /tmp/ai-accounts-pkgs
mkdir -p /tmp/ai-accounts-pkgs
pnpm --filter @ai-accounts/ts-core pack --pack-destination /tmp/ai-accounts-pkgs
pnpm --filter @ai-accounts/vue-headless pack --pack-destination /tmp/ai-accounts-pkgs
pnpm --filter @ai-accounts/vue-styled pack --pack-destination /tmp/ai-accounts-pkgs
ls /tmp/ai-accounts-pkgs
```

Expected: three `.tgz` files at version 0.2.0.

### Step 2: Reinstall Python packages (editable path, auto-upgrades to 0.2.0)

```
cd ~/Developer/Projects/Agented-ai-accounts-migration/backend
uv sync
uv run python -c "
import ai_accounts_core, ai_accounts_litestar
print('core:', ai_accounts_core.__version__)
print('litestar:', ai_accounts_litestar.__version__)
"
```

Expected: both print `0.2.0`. The editable install picks up the new source automatically.

### Step 3: Reinstall JS packages from new tarballs

```
cd ~/Developer/Projects/Agented-ai-accounts-migration/frontend
npm uninstall @ai-accounts/ts-core @ai-accounts/vue-headless @ai-accounts/vue-styled
npm install --save \
  /tmp/ai-accounts-pkgs/ai-accounts-ts-core-0.2.0.tgz \
  /tmp/ai-accounts-pkgs/ai-accounts-vue-headless-0.2.0.tgz \
  /tmp/ai-accounts-pkgs/ai-accounts-vue-styled-0.2.0.tgz
cat node_modules/@ai-accounts/ts-core/package.json | grep version
```

### Step 4: Fix the ts-core breaking change in Agented's shim

`frontend/src/services/api/backends.ts` has a wrapper around `aiAccountsClient.loginBackend(...)`. In v0.1.0, this returned `unknown`. In v0.2.0 it returns `LoginResponseDTO`. Update the shim:

- If the caller expected a `BackendDTO` (old shape), unwrap `response.backend` — but throw if `response.kind === 'pending'` since Agented's legacy UI doesn't handle OAuth.
- Acknowledge that BackendDetailPage's inline save form is still broken from Phase 1 — this task doesn't fix that.

### Step 5: Rebuild + run tests

```
cd ~/Developer/Projects/Agented-ai-accounts-migration
cd frontend && npm run build 2>&1 | tail -10
cd ../backend && uv run pytest tests/integration/test_ai_accounts_proxy.py -v
```

The 5 Phase 1 integration tests need fixture updates: add `backend_dirs_path=tmp_path / "backend_dirs"` to `AiAccountsConfig(...)` in the `client` fixture. After that fix, all 5 should pass.

### Step 6: Commit

```
cd ~/Developer/Projects/Agented-ai-accounts-migration
git status
git add backend/pyproject.toml backend/uv.lock \
         frontend/package.json frontend/package-lock.json \
         frontend/src/services/api/backends.ts \
         backend/tests/integration/test_ai_accounts_proxy.py
git commit -m "chore: upgrade ai-accounts to 0.2.0 in Agented"
```

---

## Task 18: Swap OnboardingAutomationPage.vue for <OnboardingFlow>

**Files:**
- Modify: `frontend/src/views/OnboardingAutomationPage.vue` (maybe)

### Step 1: Inspect the current file

```
cd ~/Developer/Projects/Agented-ai-accounts-migration
wc -l frontend/src/views/OnboardingAutomationPage.vue
head -80 frontend/src/views/OnboardingAutomationPage.vue
grep -n "backend\|setup\|onboard\|AccountWizard\|wizard" frontend/src/views/OnboardingAutomationPage.vue | head -20
```

Decide: is `OnboardingAutomationPage.vue` the **backend setup wizard** (the thing the package's `<OnboardingFlow>` replaces) or is it a **different feature** (trigger automation, bot onboarding, etc.)?

### Step 2: Decision point

- **If it's the backend setup wizard:** replace its template with `<OnboardingFlow :client="client" @done="onDone" />`. Wire a `AiAccountsClient` instance and route on `done` to whatever page the old wizard routed to on completion.
- **If it's something else (trigger automation, not backend setup):** DO NOT TOUCH IT. Document the decision and move to Task 19 with no commit.

### Step 3: If swapping, replace the script and template

```vue
<script setup lang="ts">
import { useRouter } from 'vue-router';
import { AiAccountsClient } from '@ai-accounts/ts-core';
import { OnboardingFlow } from '@ai-accounts/vue-styled';
import '@ai-accounts/vue-styled/styles.css';

const router = useRouter();
const client = new AiAccountsClient({ baseUrl: '' });

function onDone(_backendId: string) {
  // Navigate to wherever the old wizard ended
  router.push({ name: 'backends' });
}
</script>

<template>
  <main class="onboarding-automation">
    <OnboardingFlow :client="client" @done="onDone" />
  </main>
</template>
```

### Step 4: Commit (only if changes were made)

```
git add frontend/src/views/OnboardingAutomationPage.vue
git commit -m "feat(frontend): use OnboardingFlow for backend setup"
```

---

## Task 19: Delete superseded Agented onboarding code

**Files:** varies — scan first, delete only if clearly duplicated by the package.

### Step 1: Find candidates

```
cd ~/Developer/Projects/Agented-ai-accounts-migration
grep -rn "OnboardingAutomation\|onboard" backend/app/routes/ backend/app/services/ 2>/dev/null
grep -rn "setup_wizard\|setup_service" backend/app/services/ 2>/dev/null
ls backend/app/services/setup_* 2>/dev/null
```

### Step 2: Decision point

For each candidate file, decide:
- **Pure backend-onboarding:** delete the whole file and remove its blueprint registration.
- **Mixed (also handles other setup features):** leave alone.
- **Unclear:** leave alone, note in Task 20 report.

### Step 3: Run tests to catch broken imports

```
cd backend && uv run pytest 2>&1 | tail -20
```

Fix any test breakage that is strictly caused by deletion. Pre-existing unrelated failures stay.

### Step 4: Commit (only if changes were made)

```
git add -A backend/
git commit -m "feat: delete superseded Agented onboarding service code"
```

---

## Task 20: Integration smoke test + final verification

**Files:**
- Modify: `backend/tests/integration/test_ai_accounts_proxy.py` — add onboarding test

### Step 1: Add onboarding flow smoke test

```python
@pytest.mark.asyncio
async def test_onboarding_full_flow(client):
    started = await client.post("/api/v1/onboarding/")
    assert started.status_code == 201
    onb_id = started.json()["id"]

    detect = await client.post(f"/api/v1/onboarding/{onb_id}/detect")
    assert detect.status_code == 201

    # Use FakeBackend for deterministic CI (update fixture if needed)
    pick = await client.post(
        f"/api/v1/onboarding/{onb_id}/pick",
        json={"kind": "fake", "display_name": "Integration"},
    )
    assert pick.status_code == 201

    login = await client.post(
        f"/api/v1/onboarding/{onb_id}/login",
        json={"flow_kind": "api_key", "inputs": {}},
    )
    assert login.json()["kind"] == "complete"

    final = await client.post(f"/api/v1/onboarding/{onb_id}/finalize")
    assert final.status_code == 201
    assert final.json()["current_step"] == "done"
```

If the existing `client` fixture registers real backends (Claude, OpenCode, Gemini, Codex), update it to register `FakeBackend` from `ai_accounts_core.testing` for this test to be deterministic. Otherwise add a separate fixture.

### Step 2: Full verification

```
cd ~/Developer/Projects/Agented-ai-accounts-migration
cd backend && uv run pytest 2>&1 | tail -20
cd ../frontend && npm run build 2>&1 | tail -10
cd ../frontend && npm run test:run 2>&1 | tail -10
```

All three must be green (pre-existing unrelated failures notwithstanding).

### Step 3: Commit

```
git add -A backend/tests/integration/
git commit -m "test(integration): add onboarding flow smoke test"
```

### Step 4: Do NOT merge

The `feat/ai-accounts-phase-1` branch now has Phase 1 + Phase 2 work. Known regressions from Phase 1 (BackendDetailPage inline save, DTO adapter gaps, old wizard props lost) are still unresolved. Merging to Agented main is blocked on those — a separate fix pass, NOT part of Phase 2.

### Step 5: Final state check

```
cd ~/Developer/Projects/Agented-ai-accounts-migration
git log --oneline | head -20
git status
```

Expected: clean working tree, branch has ~14 commits (8 from Phase 1 + 6 from Phase 2 Part F).

---

## Success criteria

- ✅ `ai-accounts@0.2.0` tagged; Python packages published to PyPI (JS packages too if `npm login` set up)
- ✅ `BackendProtocol` evolved: `isolation_dir` kwarg, `LoginResult` tagged union, `poll_login`, `supported_login_flows`
- ✅ `GeminiBackend` + `CodexBackend` shipped with api_key + oauth_device flows
- ✅ Per-account isolation directories under `backend_dirs_path`, cleaned up on delete
- ✅ `OnboardingService` + `POST /api/v1/onboarding/*` routes
- ✅ `<OnboardingFlow>` Vue component with OAuth device-flow UI (tabbed login, verification URL, copy-code button, auto-polling)
- ✅ Agented `feat/ai-accounts-phase-1` branch upgrades to ai-accounts 0.2.0 cleanly
- ✅ `OnboardingAutomationPage.vue` uses `<OnboardingFlow>` (if applicable)
- ✅ Integration test for onboarding flow passes
- ✅ Playground demo renders OnboardingFlow with all four backends

## Non-success markers (fine for 0.2.0)

- ❌ No React/Svelte frontend
- ❌ No SSE for OAuth (polling only; SSE lands in Phase 3 for chat)
- ❌ No OIDC / SSO for the ai-accounts admin API (Phase 5)
- ❌ No chat, PTY, sessions (Phases 3-4)
- ❌ No KMS vault or keychain (Phase 6+)
- ❌ Agented main still has Phase 1 regressions (separate fix, not Phase 2)
- ❌ OnboardingFlow does not remember in-progress state across reloads (the state row persists, but the UI doesn't reconnect by id yet — v0.3 feature)
