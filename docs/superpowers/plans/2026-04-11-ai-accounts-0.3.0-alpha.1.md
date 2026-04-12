# ai-accounts 0.3.0-alpha.1 — Wizard + Login Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the real `AccountWizard` + interactive login (`LoginSession` abstraction, CLI-browser/OAuth-device/API-key flows, SSE transport, backend metadata API) as `ai-accounts@0.3.0-alpha.1`, and switch Agented to consume it.

**Architecture:** Python `BackendProtocol` grows a `begin_login() → LoginSession` method; each backend returns a session that yields `LoginEvent`s (URL prompts, text prompts, stdout, complete, failed) via `AsyncIterator`. Litestar exposes `POST /connect`, SSE `GET /login/stream`, `POST /respond`, `POST /cancel`, and `GET /backends/_meta`. `@ai-accounts/vue-styled` ships the polished wizard, wired to a plugin-installed `AiAccountsClient` with typed event bus + `authHeaders` hook.

**Tech Stack:** Python 3.11+, Litestar 2.12+, msgspec, aiosqlite, asyncio, stdlib `pty`. TypeScript, Vue 3, vue-headless + vue-styled. No new runtime deps beyond what's already in the monorepo.

**Repos touched:**
1. `~/Developer/Projects/ai-accounts/` (main) — monorepo; all package work here
2. `~/Developer/Projects/Agented-ai-accounts-migration/` (branch `feat/ai-accounts-phase-1`) — Agented consumer; swap wizard + delete shim

**Source of truth for ported code:**
- CLI orchestrator: `~/Developer/Projects/Agented-ai-accounts-migration/backend/app/services/backend_cli_service.py`
- Polished wizard: `~/Developer/Projects/Agented-ai-accounts-migration/frontend/src/components/backends/AccountWizard.vue` (1947 lines, restored from `6b15108^`)
- Inline edit form: derived from `frontend/src/views/BackendDetailPage.vue`
- Backend metadata constants: `frontend/src/services/api/backends.ts` `BACKEND_METADATA` + `BACKEND_LOGIN_INFO`
- PTY utilities (stdlib pty wrapper): `backend/app/services/pty_service.py`

---

## File Structure

### `ai-accounts` monorepo — new / modified files

```
packages/core/src/ai_accounts_core/
├── backends/
│   ├── base.py               # MODIFY: BackendProtocol + begin_login + metadata classvar
│   ├── claude.py             # MODIFY: real LoginSession for cli_browser + api_key
│   ├── codex.py              # MODIFY: real LoginSession for oauth_device + cli_browser + api_key
│   ├── gemini.py             # MODIFY: real LoginSession for oauth_device + api_key
│   └── opencode.py           # CREATE: new backend with cli_browser + api_key
├── login/
│   ├── __init__.py           # CREATE: public re-exports
│   ├── events.py             # CREATE: LoginEvent discriminated union + PromptAnswer
│   ├── session.py            # CREATE: LoginSession ABC
│   ├── registry.py           # CREATE: in-memory LoginSessionRegistry (TTL)
│   └── cli_orchestrator.py   # CREATE: pty subprocess runner (ported)
├── metadata/
│   ├── __init__.py           # CREATE
│   ├── types.py              # CREATE: BackendMetadata, InstallCheck, LoginFlowSpec, PlanOption
│   └── registry.py           # CREATE: BackendRegistry.register / get / list
├── services/
│   └── accounts.py           # MODIFY: AccountService.begin_login → LoginSession
└── testing.py                # MODIFY: FakeBackend with scripted LoginSession

packages/core/tests/
├── login/
│   ├── test_events.py        # CREATE
│   ├── test_session_abc.py   # CREATE
│   ├── test_registry.py      # CREATE
│   └── test_cli_orchestrator.py  # CREATE
├── metadata/
│   └── test_registry.py      # CREATE
└── backends/
    ├── test_claude_login.py  # CREATE
    ├── test_codex_login.py   # CREATE
    ├── test_gemini_login.py  # CREATE
    ├── test_opencode_login.py  # CREATE
    └── test_metadata.py      # CREATE

packages/litestar/src/ai_accounts_litestar/
├── app.py                    # MODIFY: register login + meta controllers
├── routes/
│   ├── backends.py           # MODIFY: remove old login, delegate to new session system
│   ├── login.py              # CREATE: /connect, /login/stream, /respond, /cancel
│   └── meta.py               # CREATE: /backends/_meta

packages/litestar/tests/
├── test_login_routes.py      # CREATE
└── test_meta_route.py        # CREATE

packages/ts-core/src/
├── client/
│   ├── index.ts              # MODIFY: beginLogin, respondLogin, cancelLogin, getMetadata
│   └── login-stream.ts       # CREATE: SSE consumer + LoginStreamSession
├── types/
│   ├── login.ts              # CREATE: LoginEvent union, PromptAnswer, LoginFlow
│   └── metadata.ts           # CREATE: BackendMetadata, InstallCheck, LoginFlowSpec, PlanOption
└── events.ts                 # CREATE: AiAccountsEvent discriminated union

packages/ts-core/tests/
├── login-stream.test.ts      # CREATE
└── metadata.test.ts          # CREATE

packages/vue-headless/src/
├── index.ts                  # MODIFY: export plugin + composables
├── plugin.ts                 # CREATE: aiAccountsPlugin with auth + event bus
├── injection-keys.ts         # CREATE: typed InjectionKeys
└── composables/
    ├── useAiAccounts.ts      # CREATE: inject client + event bus + auth
    ├── useBackendRegistry.ts # CREATE: fetch /_meta into reactive store
    └── useLoginSession.ts    # CREATE: wizard-facing state machine

packages/vue-headless/tests/
├── plugin.test.ts            # CREATE
├── useBackendRegistry.test.ts # CREATE
└── useLoginSession.test.ts   # CREATE

packages/vue-styled/src/
├── index.ts                  # MODIFY: export new wizard + sub-components
├── AccountWizard.vue         # REWRITE: real polished wizard (ported, refactored)
├── BackendPicker.vue         # CREATE
├── LoginStream.vue           # CREATE
├── AccountEditForm.vue       # CREATE
└── tokens.css                # MODIFY: backend picker + login stream tokens

packages/vue-styled/tests/
├── AccountWizard.test.ts     # CREATE
├── LoginStream.test.ts       # CREATE
└── AccountEditForm.test.ts   # CREATE
```

### `Agented-ai-accounts-migration` — modified / deleted files

```
backend/scripts/run_ai_accounts.py         # MODIFY: register new backends + metadata
frontend/src/main.ts                       # MODIFY: install aiAccountsPlugin
frontend/src/views/BackendDetailPage.vue   # MODIFY: import wizard from @ai-accounts/vue-styled
frontend/src/services/api/backends.ts      # DELETE (end of alpha.1, after E2E verified)
frontend/src/components/backends/AccountWizard.vue  # DELETE (same commit)
frontend/vite.config.ts                    # VERIFY: /api/v1/* proxy to :20001 already present
```

---

## Shared test helpers

Every `LoginSession` test uses a fake pty/subprocess fixture. Define once, reuse:

**`packages/core/tests/conftest.py`** — add:

```python
import asyncio
import contextlib
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture
def tmp_isolation_dir(tmp_path: Path) -> Path:
    d = tmp_path / "iso"
    d.mkdir()
    return d


class FakePty:
    """Scripted fake subprocess — feeds chunks to read_output(), captures writes."""

    def __init__(self, script: list[tuple[str, Any]]) -> None:
        self._script = list(script)
        self._writes: list[bytes] = []
        self._closed = False
        self._exit_code: int | None = None

    async def read_output(self) -> AsyncIterator[bytes]:
        for kind, payload in self._script:
            if kind == "out":
                yield payload.encode() if isinstance(payload, str) else payload
            elif kind == "wait":
                await asyncio.sleep(payload)
            elif kind == "exit":
                self._exit_code = payload
                return

    async def write(self, data: bytes) -> None:
        self._writes.append(data)

    async def close(self) -> None:
        self._closed = True

    @property
    def exit_code(self) -> int | None:
        return self._exit_code
```

Used by `test_cli_orchestrator.py`, `test_claude_login.py`, `test_codex_login.py`, etc.

---

## Task 0: Branch setup in both repos

**Files:**
- `~/Developer/Projects/ai-accounts/` — create branch `feat/0.3.0-alpha.1`
- `~/Developer/Projects/Agented-ai-accounts-migration/` — already on `feat/ai-accounts-phase-1`; create sub-branch `feat/0.3.0-alpha.1-consumer` off it

- [ ] **Step 1: Create ai-accounts branch**

```bash
cd ~/Developer/Projects/ai-accounts
git fetch origin
git checkout main
git pull --ff-only
git checkout -b feat/0.3.0-alpha.1
```

- [ ] **Step 2: Confirm Agented consumer branch**

```bash
cd ~/Developer/Projects/Agented-ai-accounts-migration
git status
# must show: branch feat/ai-accounts-phase-1, working tree clean
git checkout -b feat/0.3.0-alpha.1-consumer
```

- [ ] **Step 3: Baseline test runs (both repos green before starting)**

```bash
cd ~/Developer/Projects/ai-accounts && uv run --package ai-accounts-core pytest packages/core/tests/ -q
cd ~/Developer/Projects/ai-accounts && uv run --package ai-accounts-litestar pytest packages/litestar/tests/ -q
cd ~/Developer/Projects/ai-accounts && pnpm -r --filter '@ai-accounts/*' test -- --run
```
Expected: all green. If not, fix before proceeding.

- [ ] **Step 4: Commit empty branch marker**

```bash
cd ~/Developer/Projects/ai-accounts
git commit --allow-empty -m "chore: begin 0.3.0-alpha.1 (wizard + login)"
```

---

## Task 1: `LoginEvent` discriminated union

**Files:**
- Create: `packages/core/src/ai_accounts_core/login/__init__.py`
- Create: `packages/core/src/ai_accounts_core/login/events.py`
- Test: `packages/core/tests/login/test_events.py`

- [ ] **Step 1: Write failing test**

```python
# packages/core/tests/login/test_events.py
import msgspec

from ai_accounts_core.login.events import (
    LoginComplete,
    LoginEvent,
    LoginFailed,
    ProgressUpdate,
    PromptAnswer,
    StdoutChunk,
    TextPrompt,
    UrlPrompt,
)


def test_url_prompt_roundtrip():
    evt = UrlPrompt(prompt_id="p-1", url="https://x.test/auth", user_code="ABCD-1234")
    data = msgspec.json.encode(evt)
    decoded = msgspec.json.decode(data, type=LoginEvent)
    assert isinstance(decoded, UrlPrompt)
    assert decoded.url == "https://x.test/auth"
    assert decoded.user_code == "ABCD-1234"


def test_text_prompt_hidden_flag():
    evt = TextPrompt(prompt_id="p-2", prompt="API key:", hidden=True)
    assert evt.hidden is True


def test_stdout_chunk_contains_ansi_stripped_text():
    evt = StdoutChunk(text="hello world")
    assert evt.text == "hello world"


def test_progress_update_optional_percent():
    a = ProgressUpdate(label="polling")
    b = ProgressUpdate(label="verifying", percent=50)
    assert a.percent is None
    assert b.percent == 50


def test_login_complete_shape():
    evt = LoginComplete(account_id="bkd-abc123", backend_status="validating")
    assert evt.account_id == "bkd-abc123"


def test_login_failed_shape():
    evt = LoginFailed(code="cli_exit_nonzero", message="claude exited with 2")
    assert evt.code == "cli_exit_nonzero"


def test_prompt_answer_text():
    ans = PromptAnswer(prompt_id="p-2", answer="sk-ant-xxx")
    assert ans.answer == "sk-ant-xxx"
```

- [ ] **Step 2: Run failing test**

```bash
cd ~/Developer/Projects/ai-accounts
uv run --package ai-accounts-core pytest packages/core/tests/login/test_events.py -q
```
Expected: FAIL (`ModuleNotFoundError: ai_accounts_core.login`)

- [ ] **Step 3: Create login package init**

```python
# packages/core/src/ai_accounts_core/login/__init__.py
from ai_accounts_core.login.events import (
    LoginComplete,
    LoginEvent,
    LoginFailed,
    ProgressUpdate,
    PromptAnswer,
    StdoutChunk,
    TextPrompt,
    UrlPrompt,
)

__all__ = [
    "LoginComplete",
    "LoginEvent",
    "LoginFailed",
    "ProgressUpdate",
    "PromptAnswer",
    "StdoutChunk",
    "TextPrompt",
    "UrlPrompt",
]
```

- [ ] **Step 4: Write events module**

```python
# packages/core/src/ai_accounts_core/login/events.py
"""Login event types — discriminated union published via SSE during login.

Each subclass is a msgspec.Struct with a ``type`` tag. The ``LoginEvent``
alias is the union Litestar and the TS client decode against.
"""

from __future__ import annotations

import msgspec


class UrlPrompt(msgspec.Struct, tag="url_prompt", tag_field="type"):
    prompt_id: str
    url: str
    user_code: str | None = None


class TextPrompt(msgspec.Struct, tag="text_prompt", tag_field="type"):
    prompt_id: str
    prompt: str
    hidden: bool = False


class StdoutChunk(msgspec.Struct, tag="stdout", tag_field="type"):
    text: str


class ProgressUpdate(msgspec.Struct, tag="progress", tag_field="type"):
    label: str
    percent: int | None = None


class LoginComplete(msgspec.Struct, tag="complete", tag_field="type"):
    account_id: str
    backend_status: str


class LoginFailed(msgspec.Struct, tag="failed", tag_field="type"):
    code: str
    message: str


LoginEvent = (
    UrlPrompt
    | TextPrompt
    | StdoutChunk
    | ProgressUpdate
    | LoginComplete
    | LoginFailed
)


class PromptAnswer(msgspec.Struct):
    """Client→server payload for POST /login/respond."""

    prompt_id: str
    answer: str
```

- [ ] **Step 5: Run passing test**

```bash
cd ~/Developer/Projects/ai-accounts
uv run --package ai-accounts-core pytest packages/core/tests/login/test_events.py -v
```
Expected: 7 passed

- [ ] **Step 6: Commit**

```bash
git add packages/core/src/ai_accounts_core/login/__init__.py \
        packages/core/src/ai_accounts_core/login/events.py \
        packages/core/tests/login/test_events.py
git commit -m "feat(core): LoginEvent discriminated union + PromptAnswer"
```

---

## Task 2: `LoginSession` ABC

**Files:**
- Create: `packages/core/src/ai_accounts_core/login/session.py`
- Test: `packages/core/tests/login/test_session_abc.py`

- [ ] **Step 1: Write failing test**

```python
# packages/core/tests/login/test_session_abc.py
import asyncio
from collections.abc import AsyncIterator

import pytest

from ai_accounts_core.login.events import (
    LoginComplete,
    LoginEvent,
    PromptAnswer,
    TextPrompt,
)
from ai_accounts_core.login.session import LoginSession


class _Echo(LoginSession):
    def __init__(self) -> None:
        self._answers: asyncio.Queue[PromptAnswer] = asyncio.Queue()
        self._cancelled = False
        self._done = False

    @property
    def session_id(self) -> str:
        return "sess-echo"

    @property
    def backend_kind(self) -> str:
        return "fake"

    @property
    def flow_kind(self) -> str:
        return "api_key"

    @property
    def done(self) -> bool:
        return self._done

    async def events(self) -> AsyncIterator[LoginEvent]:
        yield TextPrompt(prompt_id="p-1", prompt="key")
        ans = await self._answers.get()
        assert ans.prompt_id == "p-1"
        yield LoginComplete(account_id="bkd-echo", backend_status="validating")
        self._done = True

    async def respond(self, answer: PromptAnswer) -> None:
        await self._answers.put(answer)

    async def cancel(self) -> None:
        self._cancelled = True
        self._done = True


@pytest.mark.asyncio
async def test_session_prompt_respond_complete():
    sess = _Echo()
    events: list[LoginEvent] = []

    async def consume() -> None:
        async for ev in sess.events():
            events.append(ev)

    task = asyncio.create_task(consume())
    await asyncio.sleep(0)  # let the generator reach the prompt
    await sess.respond(PromptAnswer(prompt_id="p-1", answer="sk-test"))
    await task

    assert len(events) == 2
    assert isinstance(events[0], TextPrompt)
    assert isinstance(events[1], LoginComplete)
    assert sess.done is True


@pytest.mark.asyncio
async def test_session_cancel_sets_done():
    sess = _Echo()
    await sess.cancel()
    assert sess.done is True
```

- [ ] **Step 2: Run failing test**

```bash
uv run --package ai-accounts-core pytest packages/core/tests/login/test_session_abc.py -q
```
Expected: FAIL — `ImportError`

- [ ] **Step 3: Write ABC**

```python
# packages/core/src/ai_accounts_core/login/session.py
"""LoginSession — abstract base for interactive backend login flows.

One session per backend login attempt. The caller:
  1. iterates .events() to get URL prompts, text prompts, stdout, complete/failed
  2. calls .respond(answer) to satisfy text prompts
  3. calls .cancel() to abort

Implementations own their subprocess / HTTP resources and must be idempotent
on cancel.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from ai_accounts_core.login.events import LoginEvent, PromptAnswer


class LoginSession(ABC):
    @property
    @abstractmethod
    def session_id(self) -> str: ...

    @property
    @abstractmethod
    def backend_kind(self) -> str: ...

    @property
    @abstractmethod
    def flow_kind(self) -> str: ...

    @property
    @abstractmethod
    def done(self) -> bool: ...

    @abstractmethod
    def events(self) -> AsyncIterator[LoginEvent]: ...

    @abstractmethod
    async def respond(self, answer: PromptAnswer) -> None: ...

    @abstractmethod
    async def cancel(self) -> None: ...
```

- [ ] **Step 4: Re-export from package init**

Edit `packages/core/src/ai_accounts_core/login/__init__.py` to also export `LoginSession`:

```python
from ai_accounts_core.login.events import (
    LoginComplete,
    LoginEvent,
    LoginFailed,
    ProgressUpdate,
    PromptAnswer,
    StdoutChunk,
    TextPrompt,
    UrlPrompt,
)
from ai_accounts_core.login.session import LoginSession

__all__ = [
    "LoginComplete",
    "LoginEvent",
    "LoginFailed",
    "LoginSession",
    "ProgressUpdate",
    "PromptAnswer",
    "StdoutChunk",
    "TextPrompt",
    "UrlPrompt",
]
```

- [ ] **Step 5: Run passing test**

```bash
uv run --package ai-accounts-core pytest packages/core/tests/login/test_session_abc.py -v
```
Expected: 2 passed

- [ ] **Step 6: Commit**

```bash
git add packages/core/src/ai_accounts_core/login/session.py \
        packages/core/src/ai_accounts_core/login/__init__.py \
        packages/core/tests/login/test_session_abc.py
git commit -m "feat(core): LoginSession ABC"
```

---

## Task 3: `LoginSessionRegistry` (in-memory with TTL)

**Files:**
- Create: `packages/core/src/ai_accounts_core/login/registry.py`
- Test: `packages/core/tests/login/test_registry.py`

- [ ] **Step 1: Write failing test**

```python
# packages/core/tests/login/test_registry.py
import asyncio
from collections.abc import AsyncIterator

import pytest

from ai_accounts_core.login.events import LoginComplete, LoginEvent, PromptAnswer
from ai_accounts_core.login.registry import LoginSessionRegistry
from ai_accounts_core.login.session import LoginSession


class _Stub(LoginSession):
    def __init__(self, sid: str) -> None:
        self._sid = sid
        self._done = False

    @property
    def session_id(self) -> str: return self._sid
    @property
    def backend_kind(self) -> str: return "fake"
    @property
    def flow_kind(self) -> str: return "api_key"
    @property
    def done(self) -> bool: return self._done

    async def events(self) -> AsyncIterator[LoginEvent]:
        yield LoginComplete(account_id="bkd-x", backend_status="validating")
        self._done = True

    async def respond(self, answer: PromptAnswer) -> None: ...
    async def cancel(self) -> None: self._done = True


@pytest.mark.asyncio
async def test_register_and_get():
    reg = LoginSessionRegistry(ttl_seconds=60)
    s = _Stub("sess-1")
    await reg.register(s)
    assert await reg.get("sess-1") is s


@pytest.mark.asyncio
async def test_get_missing_returns_none():
    reg = LoginSessionRegistry(ttl_seconds=60)
    assert await reg.get("nope") is None


@pytest.mark.asyncio
async def test_expired_session_purged():
    reg = LoginSessionRegistry(ttl_seconds=0)
    await reg.register(_Stub("sess-2"))
    await asyncio.sleep(0.01)
    await reg.sweep()
    assert await reg.get("sess-2") is None


@pytest.mark.asyncio
async def test_done_session_removable():
    reg = LoginSessionRegistry(ttl_seconds=60)
    s = _Stub("sess-3")
    await reg.register(s)
    await s.cancel()
    await reg.remove("sess-3")
    assert await reg.get("sess-3") is None
```

- [ ] **Step 2: Run failing test**

```bash
uv run --package ai-accounts-core pytest packages/core/tests/login/test_registry.py -q
```
Expected: FAIL — `ImportError`

- [ ] **Step 3: Implement registry**

```python
# packages/core/src/ai_accounts_core/login/registry.py
"""In-memory LoginSession registry with TTL sweep.

Sessions live in the sidecar process for the duration of the login.
Each session is keyed by its own ``session_id``. Sessions that exceed
``ttl_seconds`` since registration are purged by ``sweep()``.

Concurrency note: all mutation goes through an ``asyncio.Lock`` so the
SSE route handler can safely race with /respond and /cancel.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

from ai_accounts_core.login.session import LoginSession


@dataclass
class _Entry:
    session: LoginSession
    registered_at: float


class LoginSessionRegistry:
    def __init__(self, ttl_seconds: float = 600.0) -> None:
        self._entries: dict[str, _Entry] = {}
        self._ttl = ttl_seconds
        self._lock = asyncio.Lock()

    async def register(self, session: LoginSession) -> None:
        async with self._lock:
            self._entries[session.session_id] = _Entry(session, time.monotonic())

    async def get(self, session_id: str) -> LoginSession | None:
        async with self._lock:
            entry = self._entries.get(session_id)
            return entry.session if entry else None

    async def remove(self, session_id: str) -> None:
        async with self._lock:
            self._entries.pop(session_id, None)

    async def sweep(self) -> int:
        now = time.monotonic()
        purged = 0
        async with self._lock:
            stale = [
                sid for sid, e in self._entries.items()
                if now - e.registered_at >= self._ttl
            ]
            for sid in stale:
                entry = self._entries.pop(sid)
                purged += 1
                # Fire-and-forget cancel for stale sessions
                if not entry.session.done:
                    asyncio.create_task(entry.session.cancel())
        return purged
```

- [ ] **Step 4: Run passing test**

```bash
uv run --package ai-accounts-core pytest packages/core/tests/login/test_registry.py -v
```
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add packages/core/src/ai_accounts_core/login/registry.py \
        packages/core/tests/login/test_registry.py
git commit -m "feat(core): LoginSessionRegistry with TTL sweep"
```

---

## Task 4: CLI orchestrator (pty subprocess runner)

**Context:** Port the pty-based subprocess runner from Agented's `backend_cli_service.py`. It spawns a child in a PTY, streams stdout (ANSI-stripped via `strip_ansi`), accepts stdin writes, and exposes a line-oriented parser hook. This is the foundation every `cli_browser` `LoginSession` composes with.

**Files:**
- Create: `packages/core/src/ai_accounts_core/login/cli_orchestrator.py`
- Test: `packages/core/tests/login/test_cli_orchestrator.py`

**Source to port from:**
- `~/Developer/Projects/Agented-ai-accounts-migration/backend/app/services/pty_service.py` (ANSI strip + pty spawn)
- `~/Developer/Projects/Agented-ai-accounts-migration/backend/app/services/backend_cli_service.py` (session orchestration + output parsing)

- [ ] **Step 1: Write failing test**

```python
# packages/core/tests/login/test_cli_orchestrator.py
import pytest

from ai_accounts_core.login.cli_orchestrator import CliOrchestrator, strip_ansi


def test_strip_ansi_cursor_positioning():
    assert strip_ansi("hello\x1b[Hworld") == "hello world"


def test_strip_ansi_erase():
    assert strip_ansi("one\x1b[Jtwo") == "one\ntwo"


def test_strip_ansi_csi_sgr():
    assert strip_ansi("\x1b[31mred\x1b[0m") == "red"


@pytest.mark.asyncio
async def test_orchestrator_runs_echo_and_captures_output(tmp_path):
    orch = CliOrchestrator(
        argv=["/bin/echo", "hello"],
        env={},
        cwd=tmp_path,
    )
    chunks: list[str] = []
    await orch.start()
    async for chunk in orch.read_output():
        chunks.append(chunk)
    await orch.wait()
    joined = "".join(chunks)
    assert "hello" in joined
    assert orch.exit_code == 0


@pytest.mark.asyncio
async def test_orchestrator_accepts_stdin(tmp_path):
    orch = CliOrchestrator(
        argv=["/bin/sh", "-c", "read x; echo got=$x"],
        env={},
        cwd=tmp_path,
    )
    await orch.start()
    await orch.write(b"world\n")
    buf = ""
    async for chunk in orch.read_output():
        buf += chunk
        if "got=world" in buf:
            break
    await orch.wait()
    assert "got=world" in buf
    assert orch.exit_code == 0


@pytest.mark.asyncio
async def test_orchestrator_terminate(tmp_path):
    orch = CliOrchestrator(
        argv=["/bin/sh", "-c", "sleep 30"],
        env={},
        cwd=tmp_path,
    )
    await orch.start()
    await orch.terminate()
    await orch.wait()
    assert orch.exit_code is not None
    assert orch.exit_code != 0
```

- [ ] **Step 2: Run failing test**

```bash
uv run --package ai-accounts-core pytest packages/core/tests/login/test_cli_orchestrator.py -q
```
Expected: FAIL — `ImportError`

- [ ] **Step 3: Write orchestrator**

Port the ANSI regexes verbatim from Agented's `pty_service.py`. Pty spawn uses stdlib `pty.fork()` in a thread, with async byte pump.

```python
# packages/core/src/ai_accounts_core/login/cli_orchestrator.py
"""PTY-based CLI subprocess orchestrator.

Ported from Agented's backend/app/services/pty_service.py + backend_cli_service.py.
Runs a child CLI inside a pseudo-terminal so tools that require TTY (claude,
codex, interactive gemini) launch correctly. Streams ANSI-stripped output as
async byte chunks, accepts stdin writes, supports graceful terminate + wait.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import pty
import re
import signal
from collections.abc import AsyncIterator
from pathlib import Path

_CURSOR_POS_RE = re.compile(r"\x1b\[\d*(?:;\d*)*[HfGC]")
_ERASE_SCREEN_RE = re.compile(r"\x1b\[\d*J")
_ANSI_RE = re.compile(
    r"\x1b"
    r"(?:"
    r"\[[\x20-\x3f]*[\x40-\x7e]"
    r"|\][^\x07\x1b]*(?:\x07|\x1b\\)"
    r"|[()][AB012]"
    r"|[\x40-\x5f]"
    r")"
    r"|\x0f|\x0e"
)

_CHILD_ENV_CLEAR = ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT")

logger = logging.getLogger(__name__)


def strip_ansi(text: str) -> str:
    text = _CURSOR_POS_RE.sub(" ", text)
    text = _ERASE_SCREEN_RE.sub("\n", text)
    text = _ANSI_RE.sub("", text)
    return text


class CliOrchestrator:
    """Runs ``argv`` inside a PTY, exposes stdout as async chunks and stdin as ``write()``."""

    def __init__(
        self,
        argv: list[str],
        env: dict[str, str],
        cwd: Path,
    ) -> None:
        self._argv = argv
        self._env = env
        self._cwd = cwd
        self._pid: int | None = None
        self._master_fd: int | None = None
        self._exit_code: int | None = None
        self._reader_queue: asyncio.Queue[bytes | None] = asyncio.Queue()
        self._reader_task: asyncio.Task[None] | None = None
        self._started = False

    async def start(self) -> None:
        if self._started:
            return
        self._started = True
        pid, master_fd = pty.fork()
        if pid == 0:
            # child
            env = dict(os.environ)
            env.update(self._env)
            for k in _CHILD_ENV_CLEAR:
                env.pop(k, None)
            try:
                os.chdir(self._cwd)
                os.execvpe(self._argv[0], self._argv, env)
            except Exception:  # pragma: no cover - child side
                os._exit(127)
        self._pid = pid
        self._master_fd = master_fd
        self._reader_task = asyncio.create_task(self._reader_loop())

    async def _reader_loop(self) -> None:
        assert self._master_fd is not None
        loop = asyncio.get_running_loop()
        try:
            while True:
                try:
                    data = await loop.run_in_executor(None, self._read_once)
                except OSError:
                    break
                if not data:
                    break
                await self._reader_queue.put(data)
        finally:
            await self._reader_queue.put(None)

    def _read_once(self) -> bytes:
        assert self._master_fd is not None
        try:
            return os.read(self._master_fd, 4096)
        except OSError:
            return b""

    async def read_output(self) -> AsyncIterator[str]:
        """Yield ANSI-stripped output chunks until EOF."""
        buf = b""
        while True:
            item = await self._reader_queue.get()
            if item is None:
                if buf:
                    yield strip_ansi(buf.decode(errors="replace"))
                return
            buf += item
            # Emit on newline or buffer growth
            if b"\n" in item or len(buf) > 1024:
                text = buf.decode(errors="replace")
                buf = b""
                yield strip_ansi(text)

    async def write(self, data: bytes) -> None:
        if self._master_fd is None:
            raise RuntimeError("orchestrator not started")
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, os.write, self._master_fd, data)

    async def terminate(self) -> None:
        if self._pid is None:
            return
        with contextlib.suppress(ProcessLookupError):
            os.kill(self._pid, signal.SIGTERM)

    async def kill(self) -> None:
        if self._pid is None:
            return
        with contextlib.suppress(ProcessLookupError):
            os.kill(self._pid, signal.SIGKILL)

    async def wait(self) -> int:
        if self._pid is None:
            return self._exit_code or 0
        loop = asyncio.get_running_loop()
        _, status = await loop.run_in_executor(None, os.waitpid, self._pid, 0)
        if os.WIFEXITED(status):
            self._exit_code = os.WEXITSTATUS(status)
        elif os.WIFSIGNALED(status):
            self._exit_code = -os.WTERMSIG(status)
        else:
            self._exit_code = -1
        if self._reader_task is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await self._reader_task
        if self._master_fd is not None:
            with contextlib.suppress(OSError):
                os.close(self._master_fd)
            self._master_fd = None
        return self._exit_code

    @property
    def exit_code(self) -> int | None:
        return self._exit_code
```

- [ ] **Step 4: Run passing tests**

```bash
uv run --package ai-accounts-core pytest packages/core/tests/login/test_cli_orchestrator.py -v
```
Expected: 6 passed. (If `terminate` test flakes under CI, add `await asyncio.sleep(0.1)` after `terminate()` before `wait()`.)

- [ ] **Step 5: Commit**

```bash
git add packages/core/src/ai_accounts_core/login/cli_orchestrator.py \
        packages/core/tests/login/test_cli_orchestrator.py
git commit -m "feat(core): CliOrchestrator — pty subprocess runner (ported)"
```

---

## Task 5: `BackendMetadata` types

**Files:**
- Create: `packages/core/src/ai_accounts_core/metadata/__init__.py`
- Create: `packages/core/src/ai_accounts_core/metadata/types.py`
- Test: `packages/core/tests/metadata/__init__.py` (empty)
- Test: `packages/core/tests/metadata/test_types.py`

- [ ] **Step 1: Write failing test**

```python
# packages/core/tests/metadata/test_types.py
import msgspec

from ai_accounts_core.metadata.types import (
    BackendMetadata,
    InstallCheck,
    LoginFlowSpec,
    PlanOption,
)


def test_install_check_shape():
    ic = InstallCheck(command=["claude", "--version"], version_regex=r"(\d+\.\d+\.\d+)")
    assert ic.command == ["claude", "--version"]


def test_login_flow_spec_shape():
    lfs = LoginFlowSpec(
        kind="cli_browser",
        display_name="Sign in with browser",
        description="Opens a browser window to authenticate",
        requires_inputs=[],
    )
    assert lfs.kind == "cli_browser"


def test_plan_option_shape():
    po = PlanOption(id="max", label="Claude Max", description="$200/mo")
    assert po.id == "max"


def test_backend_metadata_roundtrip():
    meta = BackendMetadata(
        kind="claude",
        display_name="Claude Code",
        icon_url=None,
        install_check=InstallCheck(command=["claude", "--version"], version_regex=r"(\d+\.\d+\.\d+)"),
        login_flows=[
            LoginFlowSpec(kind="cli_browser", display_name="Browser", description="", requires_inputs=[]),
        ],
        plan_options=[PlanOption(id="pro", label="Pro", description="")],
        config_schema={"type": "object", "properties": {"email": {"type": "string"}}},
        supports_multi_account=True,
        isolation_env_var="CLAUDE_CONFIG_DIR",
    )
    data = msgspec.json.encode(meta)
    decoded = msgspec.json.decode(data, type=BackendMetadata)
    assert decoded.kind == "claude"
    assert decoded.supports_multi_account is True
    assert decoded.isolation_env_var == "CLAUDE_CONFIG_DIR"
```

- [ ] **Step 2: Run failing test**

```bash
uv run --package ai-accounts-core pytest packages/core/tests/metadata/test_types.py -q
```
Expected: FAIL — `ImportError`

- [ ] **Step 3: Write types**

```python
# packages/core/src/ai_accounts_core/metadata/__init__.py
from ai_accounts_core.metadata.types import (
    BackendMetadata,
    InputSpec,
    InstallCheck,
    LoginFlowSpec,
    PlanOption,
)

__all__ = [
    "BackendMetadata",
    "InputSpec",
    "InstallCheck",
    "LoginFlowSpec",
    "PlanOption",
]
```

```python
# packages/core/src/ai_accounts_core/metadata/types.py
"""Backend metadata — the shape served at GET /api/v1/backends/_meta."""

from __future__ import annotations

import msgspec


class InstallCheck(msgspec.Struct):
    """How to verify a backend CLI is installed and extract its version."""

    command: list[str]
    version_regex: str


class InputSpec(msgspec.Struct):
    """One required field for a login flow (e.g. API key, email)."""

    name: str
    label: str
    kind: str = "text"      # "text" | "secret" | "email" | "path"
    placeholder: str | None = None


class LoginFlowSpec(msgspec.Struct):
    kind: str               # "api_key" | "oauth_device" | "cli_browser"
    display_name: str
    description: str
    requires_inputs: list[InputSpec] = []


class PlanOption(msgspec.Struct):
    id: str
    label: str
    description: str


class BackendMetadata(msgspec.Struct):
    kind: str
    display_name: str
    icon_url: str | None
    install_check: InstallCheck
    login_flows: list[LoginFlowSpec]
    plan_options: list[PlanOption] | None
    config_schema: dict
    supports_multi_account: bool
    isolation_env_var: str | None
```

- [ ] **Step 4: Run passing test**

```bash
mkdir -p packages/core/tests/metadata
touch packages/core/tests/metadata/__init__.py
uv run --package ai-accounts-core pytest packages/core/tests/metadata/test_types.py -v
```
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add packages/core/src/ai_accounts_core/metadata/ \
        packages/core/tests/metadata/
git commit -m "feat(core): BackendMetadata + supporting Structs"
```

---

## Task 6: `BackendRegistry`

**Files:**
- Create: `packages/core/src/ai_accounts_core/metadata/registry.py`
- Test: `packages/core/tests/metadata/test_registry.py`

- [ ] **Step 1: Write failing test**

```python
# packages/core/tests/metadata/test_registry.py
import pytest

from ai_accounts_core.metadata.registry import BackendRegistry
from ai_accounts_core.metadata.types import (
    BackendMetadata,
    InstallCheck,
    LoginFlowSpec,
)


def _meta(kind: str) -> BackendMetadata:
    return BackendMetadata(
        kind=kind,
        display_name=kind.title(),
        icon_url=None,
        install_check=InstallCheck(command=[kind, "--version"], version_regex=r"(\d+)"),
        login_flows=[LoginFlowSpec(kind="api_key", display_name="API key", description="", requires_inputs=[])],
        plan_options=None,
        config_schema={"type": "object"},
        supports_multi_account=True,
        isolation_env_var=None,
    )


def test_register_and_list():
    reg = BackendRegistry()
    reg.register(_meta("claude"))
    reg.register(_meta("codex"))
    assert [m.kind for m in reg.list()] == ["claude", "codex"]


def test_register_duplicate_raises():
    reg = BackendRegistry()
    reg.register(_meta("claude"))
    with pytest.raises(ValueError, match="already registered"):
        reg.register(_meta("claude"))


def test_get_by_kind():
    reg = BackendRegistry()
    reg.register(_meta("gemini"))
    assert reg.get("gemini").display_name == "Gemini"


def test_get_missing_raises():
    reg = BackendRegistry()
    with pytest.raises(KeyError):
        reg.get("martian")
```

- [ ] **Step 2: Run failing test**

```bash
uv run --package ai-accounts-core pytest packages/core/tests/metadata/test_registry.py -q
```
Expected: FAIL — `ImportError`

- [ ] **Step 3: Implement registry**

```python
# packages/core/src/ai_accounts_core/metadata/registry.py
"""Backend metadata registry — aggregated and served at /_meta."""

from __future__ import annotations

from ai_accounts_core.metadata.types import BackendMetadata


class BackendRegistry:
    def __init__(self) -> None:
        self._by_kind: dict[str, BackendMetadata] = {}

    def register(self, meta: BackendMetadata) -> None:
        if meta.kind in self._by_kind:
            raise ValueError(f"backend kind '{meta.kind}' already registered")
        self._by_kind[meta.kind] = meta

    def get(self, kind: str) -> BackendMetadata:
        return self._by_kind[kind]

    def list(self) -> list[BackendMetadata]:
        return list(self._by_kind.values())
```

- [ ] **Step 4: Re-export**

Edit `packages/core/src/ai_accounts_core/metadata/__init__.py`:

```python
from ai_accounts_core.metadata.registry import BackendRegistry
from ai_accounts_core.metadata.types import (
    BackendMetadata,
    InputSpec,
    InstallCheck,
    LoginFlowSpec,
    PlanOption,
)

__all__ = [
    "BackendMetadata",
    "BackendRegistry",
    "InputSpec",
    "InstallCheck",
    "LoginFlowSpec",
    "PlanOption",
]
```

- [ ] **Step 5: Run passing test**

```bash
uv run --package ai-accounts-core pytest packages/core/tests/metadata/ -v
```
Expected: 8 passed

- [ ] **Step 6: Commit**

```bash
git add packages/core/src/ai_accounts_core/metadata/ \
        packages/core/tests/metadata/test_registry.py
git commit -m "feat(core): BackendRegistry"
```

---

## Task 7: Extend `BackendProtocol` with `begin_login` + `metadata`

**Files:**
- Modify: `packages/core/src/ai_accounts_core/backends/base.py`
- Modify: `packages/core/src/ai_accounts_core/testing.py` (`FakeBackend`)
- Test: `packages/core/tests/backends/test_base_protocol.py`

- [ ] **Step 1: Write failing test**

```python
# packages/core/tests/backends/test_base_protocol.py
from pathlib import Path

from ai_accounts_core.backends.base import BackendProtocol
from ai_accounts_core.login import LoginSession
from ai_accounts_core.metadata import BackendMetadata
from ai_accounts_core.testing import FakeBackend


def test_fake_backend_has_metadata():
    assert isinstance(FakeBackend.metadata, BackendMetadata)
    assert FakeBackend.metadata.kind == "fake"


def test_fake_backend_begin_login_returns_session(tmp_path: Path):
    backend = FakeBackend()
    session = backend.begin_login(
        flow_kind="api_key",
        config={},
        vault_ctx={},
        isolation_dir=tmp_path,
    )
    assert isinstance(session, LoginSession)
    assert session.backend_kind == "fake"
    assert session.flow_kind == "api_key"


def test_backend_protocol_runtime_checkable():
    # Structural check: FakeBackend should satisfy BackendProtocol
    assert isinstance(FakeBackend(), BackendProtocol)
```

- [ ] **Step 2: Run failing test**

```bash
uv run --package ai-accounts-core pytest packages/core/tests/backends/test_base_protocol.py -q
```
Expected: FAIL — `metadata` classvar missing / `begin_login` not defined

- [ ] **Step 3: Extend `BackendProtocol`**

Open `packages/core/src/ai_accounts_core/backends/base.py` and add the new surface:

```python
# packages/core/src/ai_accounts_core/backends/base.py
"""BackendProtocol — structural contract for AI-backend plugins."""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar, Protocol, runtime_checkable

from ai_accounts_core.login import LoginSession
from ai_accounts_core.metadata import BackendMetadata


@runtime_checkable
class BackendProtocol(Protocol):
    kind: ClassVar[str]
    metadata: ClassVar[BackendMetadata]

    async def detect(self) -> dict: ...

    async def validate(self, config: dict, vault_ctx: dict) -> dict: ...

    async def list_models(self, config: dict, vault_ctx: dict) -> list[dict]: ...

    def begin_login(
        self,
        flow_kind: str,
        config: dict,
        vault_ctx: dict,
        isolation_dir: Path,
    ) -> LoginSession: ...
```

(Keep existing `DetectResult`, `ValidateResult`, `Model` types in a sibling file if they exist — do not delete. `dict` annotations above are placeholders mirroring the existing 0.2.x surface; if richer types are defined, use them.)

- [ ] **Step 4: Update `FakeBackend`**

```python
# packages/core/src/ai_accounts_core/testing.py
"""Test doubles — FakeBackend and FakeVault."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from typing import ClassVar

from ai_accounts_core.login import (
    LoginComplete,
    LoginEvent,
    LoginSession,
    PromptAnswer,
    TextPrompt,
)
from ai_accounts_core.metadata import (
    BackendMetadata,
    InputSpec,
    InstallCheck,
    LoginFlowSpec,
)


class _FakeLoginSession(LoginSession):
    def __init__(self, flow_kind: str) -> None:
        self._flow_kind = flow_kind
        self._answers: asyncio.Queue[PromptAnswer] = asyncio.Queue()
        self._done = False

    @property
    def session_id(self) -> str: return "sess-fake"
    @property
    def backend_kind(self) -> str: return "fake"
    @property
    def flow_kind(self) -> str: return self._flow_kind
    @property
    def done(self) -> bool: return self._done

    async def events(self) -> AsyncIterator[LoginEvent]:
        if self._flow_kind == "api_key":
            yield TextPrompt(prompt_id="key", prompt="API key:", hidden=True)
            await self._answers.get()
        yield LoginComplete(account_id="bkd-fake", backend_status="validating")
        self._done = True

    async def respond(self, answer: PromptAnswer) -> None:
        await self._answers.put(answer)

    async def cancel(self) -> None:
        self._done = True


class FakeBackend:
    kind: ClassVar[str] = "fake"
    metadata: ClassVar[BackendMetadata] = BackendMetadata(
        kind="fake",
        display_name="Fake",
        icon_url=None,
        install_check=InstallCheck(command=["fake", "--version"], version_regex=r"(\d+)"),
        login_flows=[
            LoginFlowSpec(
                kind="api_key",
                display_name="API key",
                description="Paste your fake API key",
                requires_inputs=[InputSpec(name="key", label="Key", kind="secret")],
            ),
        ],
        plan_options=None,
        config_schema={"type": "object"},
        supports_multi_account=True,
        isolation_env_var=None,
    )

    async def detect(self) -> dict:
        return {"installed": True, "version": "fake/0.0", "path": "/bin/fake", "notes": None}

    async def validate(self, config: dict, vault_ctx: dict) -> dict:
        return {"ok": True, "error": None}

    async def list_models(self, config: dict, vault_ctx: dict) -> list[dict]:
        return [{"id": "fake-1", "label": "Fake 1"}]

    def begin_login(
        self,
        flow_kind: str,
        config: dict,
        vault_ctx: dict,
        isolation_dir: Path,
    ) -> LoginSession:
        return _FakeLoginSession(flow_kind)


class FakeVault:
    # Existing FakeVault — preserve whatever the 0.2.x version had.
    async def store(self, key: str, value: bytes, context: dict) -> None: ...
    async def retrieve(self, key: str, context: dict) -> bytes | None: return None
    async def delete(self, key: str, context: dict) -> None: ...
```

If `FakeVault` already exists, do not rewrite it — only add / update `FakeBackend` and `_FakeLoginSession`.

- [ ] **Step 5: Run passing test**

```bash
uv run --package ai-accounts-core pytest packages/core/tests/backends/test_base_protocol.py -v
```
Expected: 3 passed

- [ ] **Step 6: Full core suite stays green**

```bash
uv run --package ai-accounts-core pytest packages/core/tests/ -q
```
Expected: all passing. If `AccountService` tests fail because they call the old `login()`, comment them out with an `xfail` marker; Task 8 fixes them.

- [ ] **Step 7: Commit**

```bash
git add packages/core/src/ai_accounts_core/backends/base.py \
        packages/core/src/ai_accounts_core/testing.py \
        packages/core/tests/backends/test_base_protocol.py
git commit -m "feat(core): extend BackendProtocol with begin_login + metadata"
```

---

## Task 8: Port `ClaudeBackend` login (cli_browser + api_key)

**Context:** Claude's real login uses `claude /login` inside a pty. The CLI prints an auth URL, waits for browser callback, then prints success. Port the existing flow parsing from `backend_cli_service.py`.

**Files:**
- Modify: `packages/core/src/ai_accounts_core/backends/claude.py`
- Test: `packages/core/tests/backends/test_claude_login.py`

- [ ] **Step 1: Write failing test**

```python
# packages/core/tests/backends/test_claude_login.py
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from ai_accounts_core.backends.claude import ClaudeBackend
from ai_accounts_core.login.events import LoginComplete, UrlPrompt


@pytest.mark.asyncio
async def test_claude_cli_browser_parses_url_and_completion(tmp_path: Path):
    backend = ClaudeBackend()
    session = backend.begin_login(
        flow_kind="cli_browser",
        config={},
        vault_ctx={},
        isolation_dir=tmp_path,
    )

    # Fake orchestrator yielding canned claude /login output
    scripted = [
        "Opening browser...\n",
        "If the browser did not open, visit: https://claude.ai/oauth/authorize?code=XYZ\n",
        "Waiting for authentication...\n",
        "Authentication successful!\n",
    ]

    async def fake_read_output(self) -> object:
        for chunk in scripted:
            yield chunk

    with patch(
        "ai_accounts_core.backends.claude.CliOrchestrator.start",
        new=AsyncMock(return_value=None),
    ), patch(
        "ai_accounts_core.backends.claude.CliOrchestrator.read_output",
        fake_read_output,
    ), patch(
        "ai_accounts_core.backends.claude.CliOrchestrator.wait",
        new=AsyncMock(return_value=0),
    ):
        events = [evt async for evt in session.events()]

    url_prompts = [e for e in events if isinstance(e, UrlPrompt)]
    completes = [e for e in events if isinstance(e, LoginComplete)]
    assert len(url_prompts) == 1
    assert "https://claude.ai/oauth/authorize?code=XYZ" in url_prompts[0].url
    assert len(completes) == 1
    assert session.done is True


@pytest.mark.asyncio
async def test_claude_api_key_accepts_inputs(tmp_path: Path):
    backend = ClaudeBackend()
    session = backend.begin_login(
        flow_kind="api_key",
        config={},
        vault_ctx={},
        isolation_dir=tmp_path,
    )

    from ai_accounts_core.login.events import PromptAnswer, TextPrompt

    events_task = asyncio.create_task(_drain(session))
    await asyncio.sleep(0)
    await session.respond(PromptAnswer(prompt_id="api_key", answer="sk-ant-test"))
    events = await events_task

    text_prompts = [e for e in events if isinstance(e, TextPrompt)]
    completes = [e for e in events if isinstance(e, LoginComplete)]
    assert len(text_prompts) == 1
    assert text_prompts[0].prompt_id == "api_key"
    assert len(completes) == 1


async def _drain(session):
    return [evt async for evt in session.events()]
```

- [ ] **Step 2: Run failing test**

```bash
uv run --package ai-accounts-core pytest packages/core/tests/backends/test_claude_login.py -q
```
Expected: FAIL — `begin_login` missing or returns old `LoginResult`

- [ ] **Step 3: Rewrite Claude backend**

```python
# packages/core/src/ai_accounts_core/backends/claude.py
"""Claude backend — real login via `claude /login` in a pty."""

from __future__ import annotations

import asyncio
import re
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import ClassVar

from ai_accounts_core.login import (
    LoginComplete,
    LoginEvent,
    LoginFailed,
    LoginSession,
    PromptAnswer,
    StdoutChunk,
    TextPrompt,
    UrlPrompt,
)
from ai_accounts_core.login.cli_orchestrator import CliOrchestrator
from ai_accounts_core.metadata import (
    BackendMetadata,
    InputSpec,
    InstallCheck,
    LoginFlowSpec,
    PlanOption,
)

_URL_RE = re.compile(r"https://(?:claude\.ai|console\.anthropic\.com)/\S+")
_SUCCESS_MARKERS = ("Authentication successful", "Login successful", "Logged in as")
_FAILURE_MARKERS = ("Authentication failed", "Login failed", "error:")


class _ClaudeCliBrowserSession(LoginSession):
    def __init__(self, isolation_dir: Path) -> None:
        self._sid = f"sess-{uuid.uuid4().hex[:10]}"
        self._isolation_dir = isolation_dir
        self._done = False
        self._orchestrator: CliOrchestrator | None = None

    @property
    def session_id(self) -> str: return self._sid
    @property
    def backend_kind(self) -> str: return "claude"
    @property
    def flow_kind(self) -> str: return "cli_browser"
    @property
    def done(self) -> bool: return self._done

    async def events(self) -> AsyncIterator[LoginEvent]:
        self._orchestrator = CliOrchestrator(
            argv=["claude", "/login"],
            env={"CLAUDE_CONFIG_DIR": str(self._isolation_dir)},
            cwd=self._isolation_dir,
        )
        try:
            await self._orchestrator.start()
        except FileNotFoundError:
            self._done = True
            yield LoginFailed(code="cli_not_found", message="claude CLI not installed")
            return

        url_seen = False
        success = False
        async for chunk in self._orchestrator.read_output():
            if chunk.strip():
                yield StdoutChunk(text=chunk)
            if not url_seen:
                m = _URL_RE.search(chunk)
                if m:
                    url_seen = True
                    yield UrlPrompt(prompt_id="auth", url=m.group(0))
            if any(mk in chunk for mk in _SUCCESS_MARKERS):
                success = True
                break
            if any(mk in chunk for mk in _FAILURE_MARKERS):
                break

        exit_code = await self._orchestrator.wait()
        self._done = True
        if success and exit_code == 0:
            yield LoginComplete(account_id="", backend_status="validating")
        else:
            yield LoginFailed(
                code="cli_exit_nonzero" if exit_code != 0 else "auth_failed",
                message=f"claude /login exited with {exit_code}",
            )

    async def respond(self, answer: PromptAnswer) -> None:
        # cli_browser has no text prompts; no-op
        pass

    async def cancel(self) -> None:
        if self._orchestrator is not None and not self._done:
            await self._orchestrator.terminate()
            await self._orchestrator.wait()
        self._done = True


class _ClaudeApiKeySession(LoginSession):
    def __init__(self) -> None:
        self._sid = f"sess-{uuid.uuid4().hex[:10]}"
        self._answers: asyncio.Queue[PromptAnswer] = asyncio.Queue()
        self._done = False

    @property
    def session_id(self) -> str: return self._sid
    @property
    def backend_kind(self) -> str: return "claude"
    @property
    def flow_kind(self) -> str: return "api_key"
    @property
    def done(self) -> bool: return self._done

    async def events(self) -> AsyncIterator[LoginEvent]:
        yield TextPrompt(prompt_id="api_key", prompt="Anthropic API key", hidden=True)
        ans = await self._answers.get()
        if not ans.answer.startswith("sk-ant-"):
            self._done = True
            yield LoginFailed(code="invalid_key", message="API key must start with sk-ant-")
            return
        self._done = True
        yield LoginComplete(account_id="", backend_status="validating")

    async def respond(self, answer: PromptAnswer) -> None:
        await self._answers.put(answer)

    async def cancel(self) -> None:
        self._done = True


class ClaudeBackend:
    kind: ClassVar[str] = "claude"
    metadata: ClassVar[BackendMetadata] = BackendMetadata(
        kind="claude",
        display_name="Claude Code",
        icon_url=None,
        install_check=InstallCheck(
            command=["claude", "--version"],
            version_regex=r"(\d+\.\d+\.\d+)",
        ),
        login_flows=[
            LoginFlowSpec(
                kind="cli_browser",
                display_name="Sign in with browser",
                description="Run `claude /login` and authenticate in your browser",
                requires_inputs=[],
            ),
            LoginFlowSpec(
                kind="api_key",
                display_name="API key",
                description="Paste an Anthropic API key (sk-ant-...)",
                requires_inputs=[InputSpec(name="api_key", label="API key", kind="secret")],
            ),
        ],
        plan_options=[
            PlanOption(id="pro", label="Claude Pro", description="$20/mo"),
            PlanOption(id="max", label="Claude Max", description="$100+/mo"),
            PlanOption(id="api", label="API", description="Pay-as-you-go"),
        ],
        config_schema={
            "type": "object",
            "properties": {
                "email": {"type": "string"},
                "config_path": {"type": "string"},
                "plan": {"type": "string"},
            },
        },
        supports_multi_account=True,
        isolation_env_var="CLAUDE_CONFIG_DIR",
    )

    async def detect(self) -> dict:
        # Existing detect() stays; preserve whatever the 0.2.x impl had.
        from shutil import which
        path = which("claude")
        return {
            "installed": path is not None,
            "version": None,
            "path": path,
            "notes": None,
        }

    async def validate(self, config: dict, vault_ctx: dict) -> dict:
        return {"ok": True, "error": None}

    async def list_models(self, config: dict, vault_ctx: dict) -> list[dict]:
        return []

    def begin_login(
        self,
        flow_kind: str,
        config: dict,
        vault_ctx: dict,
        isolation_dir: Path,
    ) -> LoginSession:
        if flow_kind == "cli_browser":
            return _ClaudeCliBrowserSession(isolation_dir)
        if flow_kind == "api_key":
            return _ClaudeApiKeySession()
        raise ValueError(f"unsupported flow_kind: {flow_kind}")
```

- [ ] **Step 4: Run passing tests**

```bash
uv run --package ai-accounts-core pytest packages/core/tests/backends/test_claude_login.py -v
```
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add packages/core/src/ai_accounts_core/backends/claude.py \
        packages/core/tests/backends/test_claude_login.py
git commit -m "feat(core): ClaudeBackend real login (cli_browser + api_key)"
```

---

## Task 9: Port `CodexBackend` login (oauth_device + cli_browser + api_key)

**Approach:** Codex's login path in Agented uses OAuth device flow (`codex login` prints verification URL + user code, then polls). Port the stdout parser for those markers. `cli_browser` reuses `CliOrchestrator` like Claude; `api_key` is a pure text prompt.

**Files:**
- Modify: `packages/core/src/ai_accounts_core/backends/codex.py`
- Test: `packages/core/tests/backends/test_codex_login.py`

**Pattern to follow:** identical to Task 8's three-session structure (`_CodexOAuthDeviceSession`, `_CodexCliBrowserSession`, `_CodexApiKeySession`). OAuth device parses two markers:

```python
_CODEX_URL_RE = re.compile(r"https://chatgpt\.com/auth/\S+")
_CODEX_USER_CODE_RE = re.compile(r"code[:\s]+([A-Z0-9]{4}-?[A-Z0-9]{4})", re.IGNORECASE)
_CODEX_SUCCESS_MARKERS = ("Successfully logged in", "Authentication complete")
```

In `_CodexOAuthDeviceSession.events()`, emit `UrlPrompt(url=..., user_code=...)` once both regexes match, then drain stdout until a success/failure marker.

- [ ] **Step 1: Write failing test**

```python
# packages/core/tests/backends/test_codex_login.py
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from ai_accounts_core.backends.codex import CodexBackend
from ai_accounts_core.login.events import LoginComplete, UrlPrompt


@pytest.mark.asyncio
async def test_codex_oauth_device_parses_url_and_code(tmp_path: Path):
    backend = CodexBackend()
    session = backend.begin_login(
        flow_kind="oauth_device",
        config={},
        vault_ctx={},
        isolation_dir=tmp_path,
    )

    scripted = [
        "Starting OpenAI device flow...\n",
        "Visit: https://chatgpt.com/auth/device\n",
        "Enter code: ABCD-1234\n",
        "Waiting...\n",
        "Successfully logged in\n",
    ]

    async def fake_read_output(self):
        for chunk in scripted:
            yield chunk

    with patch(
        "ai_accounts_core.backends.codex.CliOrchestrator.start",
        new=AsyncMock(return_value=None),
    ), patch(
        "ai_accounts_core.backends.codex.CliOrchestrator.read_output",
        fake_read_output,
    ), patch(
        "ai_accounts_core.backends.codex.CliOrchestrator.wait",
        new=AsyncMock(return_value=0),
    ):
        events = [e async for e in session.events()]

    url_prompts = [e for e in events if isinstance(e, UrlPrompt)]
    assert len(url_prompts) == 1
    assert "chatgpt.com/auth/device" in url_prompts[0].url
    assert url_prompts[0].user_code == "ABCD-1234"
    assert any(isinstance(e, LoginComplete) for e in events)
```

- [ ] **Step 2: Run failing test**

```bash
uv run --package ai-accounts-core pytest packages/core/tests/backends/test_codex_login.py -q
```
Expected: FAIL

- [ ] **Step 3: Implement `CodexBackend` following Task 8's structure**

Mirror Task 8 file layout. Three `LoginSession` subclasses (`_CodexOAuthDeviceSession`, `_CodexCliBrowserSession`, `_CodexApiKeySession`). `metadata` classvar includes:

- Three `LoginFlowSpec` entries (oauth_device, cli_browser, api_key)
- `isolation_env_var="CODEX_HOME"`
- `config_schema` with `email`, `config_path` properties

OAuth device session:

```python
class _CodexOAuthDeviceSession(LoginSession):
    def __init__(self, isolation_dir: Path) -> None:
        self._sid = f"sess-{uuid.uuid4().hex[:10]}"
        self._isolation_dir = isolation_dir
        self._done = False
        self._orchestrator: CliOrchestrator | None = None

    @property
    def session_id(self) -> str: return self._sid
    @property
    def backend_kind(self) -> str: return "codex"
    @property
    def flow_kind(self) -> str: return "oauth_device"
    @property
    def done(self) -> bool: return self._done

    async def events(self) -> AsyncIterator[LoginEvent]:
        self._orchestrator = CliOrchestrator(
            argv=["codex", "login"],
            env={"CODEX_HOME": str(self._isolation_dir)},
            cwd=self._isolation_dir,
        )
        try:
            await self._orchestrator.start()
        except FileNotFoundError:
            self._done = True
            yield LoginFailed(code="cli_not_found", message="codex CLI not installed")
            return

        url: str | None = None
        user_code: str | None = None
        emitted_url_prompt = False
        success = False

        async for chunk in self._orchestrator.read_output():
            if chunk.strip():
                yield StdoutChunk(text=chunk)
            if url is None:
                m = _CODEX_URL_RE.search(chunk)
                if m:
                    url = m.group(0)
            if user_code is None:
                m = _CODEX_USER_CODE_RE.search(chunk)
                if m:
                    user_code = m.group(1)
            if url and user_code and not emitted_url_prompt:
                emitted_url_prompt = True
                yield UrlPrompt(prompt_id="device", url=url, user_code=user_code)
            if any(mk in chunk for mk in _CODEX_SUCCESS_MARKERS):
                success = True
                break
            if "error" in chunk.lower() or "failed" in chunk.lower():
                break

        exit_code = await self._orchestrator.wait()
        self._done = True
        if success and exit_code == 0:
            yield LoginComplete(account_id="", backend_status="validating")
        else:
            yield LoginFailed(
                code="oauth_device_failed",
                message=f"codex login exited with {exit_code}",
            )

    async def respond(self, answer: PromptAnswer) -> None: pass

    async def cancel(self) -> None:
        if self._orchestrator is not None and not self._done:
            await self._orchestrator.terminate()
            await self._orchestrator.wait()
        self._done = True
```

`_CodexCliBrowserSession` = same structure as Claude's, argv = `["codex", "auth", "--browser"]`. `_CodexApiKeySession` = same as Claude's `_ClaudeApiKeySession` but with `OPENAI_API_KEY` prefix check `sk-` (or no prefix check if codex accepts bare keys — follow Agented's existing validation).

- [ ] **Step 4: Run passing tests**

```bash
uv run --package ai-accounts-core pytest packages/core/tests/backends/test_codex_login.py -v
```
Expected: pass

- [ ] **Step 5: Commit**

```bash
git add packages/core/src/ai_accounts_core/backends/codex.py \
        packages/core/tests/backends/test_codex_login.py
git commit -m "feat(core): CodexBackend real login (oauth_device + cli_browser + api_key)"
```

---

## Task 10: Port `GeminiBackend` login (oauth_device + api_key)

**Approach:** Gemini uses Google's OAuth device flow. Agented's `backend_cli_service.py` spawns `gemini` CLI, parses the device URL + code from stdout, then polls. Port identically to Task 9's codex oauth pattern.

**Files:**
- Modify: `packages/core/src/ai_accounts_core/backends/gemini.py`
- Test: `packages/core/tests/backends/test_gemini_login.py`

- [ ] **Step 1: Write failing test** — same shape as Task 9 but parse Gemini-specific URL/code markers:

```python
_GEMINI_URL_RE = re.compile(r"https://accounts\.google\.com/o/oauth2/device/\S+")
_GEMINI_USER_CODE_RE = re.compile(r"[A-Z0-9]{4}-[A-Z0-9]{4}")
_GEMINI_SUCCESS_MARKERS = ("Login successful", "Authenticated")
```

Test inputs:
```python
scripted = [
    "Visit https://accounts.google.com/o/oauth2/device/usercode\n",
    "Enter code: ZXCV-5678\n",
    "Login successful\n",
]
```

- [ ] **Step 2: Run failing test**

```bash
uv run --package ai-accounts-core pytest packages/core/tests/backends/test_gemini_login.py -q
```
Expected: FAIL

- [ ] **Step 3: Implement `GeminiBackend`**

Mirror Task 9. Two sessions (`_GeminiOAuthDeviceSession`, `_GeminiApiKeySession`). `metadata`:

- `LoginFlowSpec` for `oauth_device` and `api_key`
- `isolation_env_var="GEMINI_CLI_HOME"`
- `plan_options=None`

OAuth session argv: `["gemini", "auth", "login", "--device"]`. Same parse-and-drain loop as codex.

API key validation: key must start with `AI` (Google API key prefix) or match Gemini key regex. Follow whatever Agented does in `BACKEND_METADATA.gemini`.

- [ ] **Step 4: Run passing tests**

```bash
uv run --package ai-accounts-core pytest packages/core/tests/backends/test_gemini_login.py -v
```

- [ ] **Step 5: Commit**

```bash
git add packages/core/src/ai_accounts_core/backends/gemini.py \
        packages/core/tests/backends/test_gemini_login.py
git commit -m "feat(core): GeminiBackend real login (oauth_device + api_key)"
```

---

## Task 11: Create `OpenCodeBackend` (cli_browser + api_key)

**Context:** OpenCode is in 0.2.x but only supports api_key today. Agented's wizard runs `opencode auth login` for the cli_browser flow. Add it as a full backend.

**Files:**
- Modify: `packages/core/src/ai_accounts_core/backends/opencode.py`
- Test: `packages/core/tests/backends/test_opencode_login.py`

- [ ] **Step 1: Write failing test** — same structure as Task 8. Scripted output for `opencode auth login`:

```python
scripted = [
    "Starting OpenCode auth...\n",
    "Open: https://opencode.ai/auth/callback\n",
    "Authentication successful\n",
]
```

- [ ] **Step 2: Run failing test**

- [ ] **Step 3: Implement `OpenCodeBackend`**

Two sessions (`_OpenCodeCliBrowserSession`, `_OpenCodeApiKeySession`). argv for cli_browser: `["opencode", "auth", "login"]`. `isolation_env_var="OPENCODE_HOME"`.

- [ ] **Step 4: Run passing tests**

- [ ] **Step 5: Commit**

```bash
git add packages/core/src/ai_accounts_core/backends/opencode.py \
        packages/core/tests/backends/test_opencode_login.py
git commit -m "feat(core): OpenCodeBackend real login (cli_browser + api_key)"
```

---

## Task 12: `AccountService.begin_login` + registry wiring

**Files:**
- Modify: `packages/core/src/ai_accounts_core/services/accounts.py`
- Test: `packages/core/tests/services/test_accounts_begin_login.py`

- [ ] **Step 1: Write failing test**

```python
# packages/core/tests/services/test_accounts_begin_login.py
from pathlib import Path

import pytest

from ai_accounts_core.adapters.storage_sqlite import SqliteStorage
from ai_accounts_core.login import LoginSession
from ai_accounts_core.login.registry import LoginSessionRegistry
from ai_accounts_core.services.accounts import AccountService
from ai_accounts_core.testing import FakeBackend, FakeVault


@pytest.mark.asyncio
async def test_begin_login_registers_session(tmp_path: Path):
    storage = SqliteStorage(str(tmp_path / "t.db"))
    await storage.migrate()
    registry = LoginSessionRegistry()
    service = AccountService(
        storage=storage,
        vault=FakeVault(),
        backends={"fake": FakeBackend()},
        backend_dirs_path=tmp_path / "iso",
        login_registry=registry,
    )

    created = await service.create(kind="fake", display_name="X", config={})
    session = await service.begin_login(
        account_id=created.id,
        flow_kind="api_key",
        inputs={},
    )
    assert isinstance(session, LoginSession)
    assert await registry.get(session.session_id) is session
```

- [ ] **Step 2: Run failing test**

Expected: FAIL — `begin_login` missing or signature mismatch

- [ ] **Step 3: Extend `AccountService`**

Add to existing `AccountService.__init__`:

```python
def __init__(
    self,
    storage: ...,
    vault: ...,
    backends: dict[str, BackendProtocol],
    backend_dirs_path: Path,
    login_registry: LoginSessionRegistry | None = None,
) -> None:
    # ... existing body ...
    self._login_registry = login_registry or LoginSessionRegistry()
```

Add method:

```python
async def begin_login(
    self,
    account_id: str,
    flow_kind: str,
    inputs: dict,
) -> LoginSession:
    row = await self._storage.get_backend(account_id)
    if row is None:
        raise KeyError(f"account {account_id} not found")
    backend = self._backends.get(row.kind)
    if backend is None:
        raise ValueError(f"backend kind '{row.kind}' not registered")

    isolation_dir = self._backend_dirs_path / account_id
    isolation_dir.mkdir(parents=True, exist_ok=True)

    session = backend.begin_login(
        flow_kind=flow_kind,
        config=row.config,
        vault_ctx={"account_id": account_id, "kind": row.kind},
        isolation_dir=isolation_dir,
    )
    await self._login_registry.register(session)
    return session

@property
def login_registry(self) -> LoginSessionRegistry:
    return self._login_registry
```

Keep the old `login()` method removed/deprecated — alpha.1 is a clean break. If existing tests reference old `login()`, update them to use `begin_login` + event iteration.

- [ ] **Step 4: Run passing test**

- [ ] **Step 5: Update Litestar config to wire `login_registry`**

```python
# packages/litestar/src/ai_accounts_litestar/config.py
# Add field to AiAccountsConfig:
login_session_ttl_seconds: float = 600.0
```

And in `app.py`, construct the registry and pass to `AccountService`:

```python
from ai_accounts_core.login.registry import LoginSessionRegistry

def create_app(config: AiAccountsConfig) -> Litestar:
    registry = LoginSessionRegistry(ttl_seconds=config.login_session_ttl_seconds)
    service = AccountService(
        storage=config.storage,
        vault=config.vault,
        backends={b.kind: b for b in config.backends},
        backend_dirs_path=config.backend_dirs_path,
        login_registry=registry,
    )
    # ... rest of existing construction ...
```

- [ ] **Step 6: Commit**

```bash
git add packages/core/src/ai_accounts_core/services/accounts.py \
        packages/core/tests/services/test_accounts_begin_login.py \
        packages/litestar/src/ai_accounts_litestar/
git commit -m "feat(core): AccountService.begin_login + LoginSessionRegistry wiring"
```

---

## Task 13: Litestar routes — `/connect` + `/login/stream` + `/respond` + `/cancel`

**Files:**
- Create: `packages/litestar/src/ai_accounts_litestar/routes/login.py`
- Modify: `packages/litestar/src/ai_accounts_litestar/app.py`
- Test: `packages/litestar/tests/test_login_routes.py`

**Route surface:**

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/v1/backends/{account_id}/login/begin` | Start a session; returns `{session_id}` |
| GET | `/api/v1/backends/{account_id}/login/stream?session_id=...` | SSE stream of `LoginEvent`s |
| POST | `/api/v1/backends/{account_id}/login/respond` | Body: `{session_id, prompt_id, answer}` |
| POST | `/api/v1/backends/{account_id}/login/cancel` | Body: `{session_id}` |

- [ ] **Step 1: Write failing test**

```python
# packages/litestar/tests/test_login_routes.py
import asyncio
import json
from pathlib import Path
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from litestar.testing import AsyncTestClient

from ai_accounts_core.adapters.auth_noauth import NoAuth
from ai_accounts_core.adapters.storage_sqlite import SqliteStorage
from ai_accounts_core.testing import FakeBackend, FakeVault
from ai_accounts_litestar.app import create_app
from ai_accounts_litestar.config import AiAccountsConfig


@pytest_asyncio.fixture
async def client(tmp_path: Path) -> AsyncIterator[AsyncTestClient]:
    app = create_app(
        AiAccountsConfig(
            env="development",
            storage=SqliteStorage(str(tmp_path / "t.db")),
            vault=FakeVault(),
            auth=NoAuth(),
            backends=(FakeBackend(),),
            backend_dirs_path=tmp_path / "iso",
        )
    )
    async with AsyncTestClient(app=app) as c:
        yield c


@pytest.mark.asyncio
async def test_begin_stream_respond_complete(client: AsyncTestClient):
    # Create an account
    r = await client.post("/api/v1/backends/", json={"kind": "fake", "display_name": "t"})
    account_id = r.json()["id"]

    # Begin login
    begin = await client.post(
        f"/api/v1/backends/{account_id}/login/begin",
        json={"flow_kind": "api_key", "inputs": {}},
    )
    assert begin.status_code == 201
    session_id = begin.json()["session_id"]

    # Collect SSE and respond mid-stream
    events: list[dict] = []

    async def consume():
        async with client.stream(
            "GET",
            f"/api/v1/backends/{account_id}/login/stream",
            params={"session_id": session_id},
        ) as response:
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    events.append(json.loads(line[6:]))
                    if events[-1]["type"] == "complete":
                        break

    async def responder():
        # wait briefly for stream to reach text_prompt
        for _ in range(50):
            await asyncio.sleep(0.01)
            if any(e["type"] == "text_prompt" for e in events):
                break
        await client.post(
            f"/api/v1/backends/{account_id}/login/respond",
            json={
                "session_id": session_id,
                "prompt_id": "key",
                "answer": "sk-fake",
            },
        )

    await asyncio.gather(consume(), responder())

    types = [e["type"] for e in events]
    assert "text_prompt" in types
    assert "complete" in types


@pytest.mark.asyncio
async def test_cancel_stops_session(client: AsyncTestClient):
    r = await client.post("/api/v1/backends/", json={"kind": "fake", "display_name": "t"})
    account_id = r.json()["id"]
    begin = await client.post(
        f"/api/v1/backends/{account_id}/login/begin",
        json={"flow_kind": "api_key", "inputs": {}},
    )
    session_id = begin.json()["session_id"]

    cancel = await client.post(
        f"/api/v1/backends/{account_id}/login/cancel",
        json={"session_id": session_id},
    )
    assert cancel.status_code == 204
```

- [ ] **Step 2: Run failing test**

```bash
cd ~/Developer/Projects/ai-accounts
uv run --package ai-accounts-litestar pytest packages/litestar/tests/test_login_routes.py -q
```
Expected: FAIL — routes don't exist

- [ ] **Step 3: Write routes module**

```python
# packages/litestar/src/ai_accounts_litestar/routes/login.py
"""Login session routes — /begin, /stream (SSE), /respond, /cancel."""

from __future__ import annotations

import msgspec
from litestar import Controller, get, post
from litestar.response import ServerSentEvent
from litestar.exceptions import NotFoundException, HTTPException
from litestar.status_codes import HTTP_201_CREATED, HTTP_204_NO_CONTENT

from ai_accounts_core.login import LoginEvent, PromptAnswer
from ai_accounts_core.services.accounts import AccountService


class _BeginRequest(msgspec.Struct):
    flow_kind: str
    inputs: dict


class _BeginResponse(msgspec.Struct):
    session_id: str


class _RespondRequest(msgspec.Struct):
    session_id: str
    prompt_id: str
    answer: str


class _CancelRequest(msgspec.Struct):
    session_id: str


class LoginController(Controller):
    path = "/api/v1/backends/{account_id:str}/login"
    tags = ["login"]

    dependencies = {}  # filled at app wire-up

    @post("/begin", status_code=HTTP_201_CREATED)
    async def begin(
        self,
        account_id: str,
        data: _BeginRequest,
        service: AccountService,
    ) -> _BeginResponse:
        try:
            session = await service.begin_login(
                account_id=account_id,
                flow_kind=data.flow_kind,
                inputs=data.inputs,
            )
        except KeyError as e:
            raise NotFoundException(detail=str(e)) from e
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        return _BeginResponse(session_id=session.session_id)

    @get("/stream")
    async def stream(
        self,
        account_id: str,
        session_id: str,
        service: AccountService,
    ) -> ServerSentEvent:
        session = await service.login_registry.get(session_id)
        if session is None:
            raise NotFoundException(detail=f"session {session_id} not found")

        async def gen():
            async for event in session.events():
                yield {
                    "event": "login",
                    "data": msgspec.json.encode(event).decode(),
                }
            # Mark done; sweep handles removal
            await service.login_registry.remove(session_id)

        return ServerSentEvent(gen())

    @post("/respond", status_code=HTTP_204_NO_CONTENT)
    async def respond(
        self,
        account_id: str,
        data: _RespondRequest,
        service: AccountService,
    ) -> None:
        session = await service.login_registry.get(data.session_id)
        if session is None:
            raise NotFoundException(detail=f"session {data.session_id} not found")
        await session.respond(PromptAnswer(prompt_id=data.prompt_id, answer=data.answer))

    @post("/cancel", status_code=HTTP_204_NO_CONTENT)
    async def cancel(
        self,
        account_id: str,
        data: _CancelRequest,
        service: AccountService,
    ) -> None:
        session = await service.login_registry.get(data.session_id)
        if session is None:
            return  # idempotent
        await session.cancel()
        await service.login_registry.remove(data.session_id)
```

- [ ] **Step 4: Wire into `app.py`**

```python
# packages/litestar/src/ai_accounts_litestar/app.py
# Add import:
from ai_accounts_litestar.routes.login import LoginController

# In create_app(), add to route_handlers list:
route_handlers=[
    HealthController,
    BackendsController,
    OnboardingController,
    LoginController,   # NEW
    # ... existing ...
],
```

Ensure `AccountService` is resolved as a dependency for `LoginController` the same way `BackendsController` already receives it.

- [ ] **Step 5: Run passing tests**

```bash
uv run --package ai-accounts-litestar pytest packages/litestar/tests/test_login_routes.py -v
```
Expected: 2 passed

- [ ] **Step 6: Commit**

```bash
git add packages/litestar/src/ai_accounts_litestar/routes/login.py \
        packages/litestar/src/ai_accounts_litestar/app.py \
        packages/litestar/tests/test_login_routes.py
git commit -m "feat(litestar): login routes (begin/stream/respond/cancel)"
```

---

## Task 14: Litestar route — `/backends/_meta`

**Files:**
- Create: `packages/litestar/src/ai_accounts_litestar/routes/meta.py`
- Modify: `packages/litestar/src/ai_accounts_litestar/app.py`
- Test: `packages/litestar/tests/test_meta_route.py`

- [ ] **Step 1: Write failing test**

```python
# packages/litestar/tests/test_meta_route.py
from pathlib import Path
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from litestar.testing import AsyncTestClient

from ai_accounts_core.adapters.auth_noauth import NoAuth
from ai_accounts_core.adapters.storage_sqlite import SqliteStorage
from ai_accounts_core.backends.claude import ClaudeBackend
from ai_accounts_core.backends.codex import CodexBackend
from ai_accounts_core.testing import FakeBackend, FakeVault
from ai_accounts_litestar.app import create_app
from ai_accounts_litestar.config import AiAccountsConfig


@pytest_asyncio.fixture
async def client(tmp_path: Path) -> AsyncIterator[AsyncTestClient]:
    app = create_app(
        AiAccountsConfig(
            env="development",
            storage=SqliteStorage(str(tmp_path / "t.db")),
            vault=FakeVault(),
            auth=NoAuth(),
            backends=(FakeBackend(), ClaudeBackend(), CodexBackend()),
            backend_dirs_path=tmp_path / "iso",
        )
    )
    async with AsyncTestClient(app=app) as c:
        yield c


@pytest.mark.asyncio
async def test_meta_returns_all_registered_backends(client: AsyncTestClient):
    r = await client.get("/api/v1/backends/_meta")
    assert r.status_code == 200
    body = r.json()
    kinds = [m["kind"] for m in body["items"]]
    assert set(kinds) == {"fake", "claude", "codex"}


@pytest.mark.asyncio
async def test_meta_claude_has_cli_browser_flow(client: AsyncTestClient):
    r = await client.get("/api/v1/backends/_meta")
    claude = next(m for m in r.json()["items"] if m["kind"] == "claude")
    flow_kinds = [f["kind"] for f in claude["login_flows"]]
    assert "cli_browser" in flow_kinds
    assert claude["isolation_env_var"] == "CLAUDE_CONFIG_DIR"
```

- [ ] **Step 2: Run failing test**

- [ ] **Step 3: Write meta route**

```python
# packages/litestar/src/ai_accounts_litestar/routes/meta.py
"""Backend metadata aggregation route."""

from __future__ import annotations

import msgspec
from litestar import Controller, get

from ai_accounts_core.metadata import BackendMetadata


class _MetaResponse(msgspec.Struct):
    items: list[BackendMetadata]


class MetaController(Controller):
    path = "/api/v1/backends"
    tags = ["metadata"]

    @get("/_meta")
    async def list_metadata(self) -> _MetaResponse:
        from ai_accounts_core.metadata.registry import BackendRegistry
        # Registry is populated in app.py from config.backends
        registry: BackendRegistry = self.app.state.backend_registry  # type: ignore[attr-defined]
        return _MetaResponse(items=registry.list())
```

- [ ] **Step 4: Wire into `app.py`**

```python
# In create_app(), after constructing service:
from ai_accounts_core.metadata.registry import BackendRegistry
from ai_accounts_litestar.routes.meta import MetaController

registry = BackendRegistry()
for backend in config.backends:
    registry.register(backend.metadata)

app = Litestar(
    route_handlers=[..., MetaController, ...],
    # existing args
    state=State({"backend_registry": registry}),  # or use dependency injection
)
```

Adjust for Litestar 2.12 dependency injection style — the route should receive the registry via `Provide` rather than `self.app.state`. Update both together.

- [ ] **Step 5: Run passing tests**

```bash
uv run --package ai-accounts-litestar pytest packages/litestar/tests/test_meta_route.py -v
```
Expected: 2 passed

- [ ] **Step 6: Commit**

```bash
git add packages/litestar/src/ai_accounts_litestar/routes/meta.py \
        packages/litestar/src/ai_accounts_litestar/app.py \
        packages/litestar/tests/test_meta_route.py
git commit -m "feat(litestar): GET /api/v1/backends/_meta"
```

---

## Task 15: ts-core — login types

**Files:**
- Create: `packages/ts-core/src/types/login.ts`
- Create: `packages/ts-core/src/types/metadata.ts`
- Create: `packages/ts-core/src/events.ts`
- Test: `packages/ts-core/tests/types.test.ts`

- [ ] **Step 1: Write failing test**

```ts
// packages/ts-core/tests/types.test.ts
import { describe, it, expect } from 'vitest';
import type {
  LoginEvent,
  PromptAnswer,
  UrlPrompt,
  LoginComplete,
} from '../src/types/login';
import type { BackendMetadata } from '../src/types/metadata';
import type { AiAccountsEvent } from '../src/events';

describe('login types', () => {
  it('UrlPrompt has required fields', () => {
    const e: UrlPrompt = { type: 'url_prompt', prompt_id: 'p', url: 'https://x' };
    expect(e.type).toBe('url_prompt');
  });

  it('LoginEvent narrows correctly', () => {
    const e: LoginEvent = { type: 'complete', account_id: 'bkd-1', backend_status: 'validating' };
    if (e.type === 'complete') {
      const c: LoginComplete = e;
      expect(c.account_id).toBe('bkd-1');
    }
  });

  it('PromptAnswer shape', () => {
    const a: PromptAnswer = { prompt_id: 'p', answer: 'x' };
    expect(a.prompt_id).toBe('p');
  });
});

describe('metadata types', () => {
  it('BackendMetadata shape', () => {
    const m: BackendMetadata = {
      kind: 'claude',
      display_name: 'Claude',
      icon_url: null,
      install_check: { command: ['claude', '--version'], version_regex: '(\\d+)' },
      login_flows: [],
      plan_options: null,
      config_schema: {},
      supports_multi_account: true,
      isolation_env_var: 'CLAUDE_CONFIG_DIR',
    };
    expect(m.kind).toBe('claude');
  });
});

describe('AiAccountsEvent', () => {
  it('includes wizard + login variants', () => {
    const e1: AiAccountsEvent = { type: 'wizard.opened', backendKind: 'claude' };
    const e2: AiAccountsEvent = { type: 'login.completed', sessionId: 's', accountId: 'a' };
    expect(e1.type).toBe('wizard.opened');
    expect(e2.type).toBe('login.completed');
  });
});
```

- [ ] **Step 2: Run failing test**

```bash
cd ~/Developer/Projects/ai-accounts
pnpm --filter @ai-accounts/ts-core test -- --run
```
Expected: FAIL

- [ ] **Step 3: Write types**

```ts
// packages/ts-core/src/types/login.ts
export type UrlPrompt = {
  type: 'url_prompt';
  prompt_id: string;
  url: string;
  user_code?: string | null;
};

export type TextPrompt = {
  type: 'text_prompt';
  prompt_id: string;
  prompt: string;
  hidden: boolean;
};

export type StdoutChunk = {
  type: 'stdout';
  text: string;
};

export type ProgressUpdate = {
  type: 'progress';
  label: string;
  percent?: number | null;
};

export type LoginComplete = {
  type: 'complete';
  account_id: string;
  backend_status: string;
};

export type LoginFailed = {
  type: 'failed';
  code: string;
  message: string;
};

export type LoginEvent =
  | UrlPrompt
  | TextPrompt
  | StdoutChunk
  | ProgressUpdate
  | LoginComplete
  | LoginFailed;

export type PromptAnswer = {
  prompt_id: string;
  answer: string;
};

export type LoginFlowKind = 'api_key' | 'oauth_device' | 'cli_browser';
```

```ts
// packages/ts-core/src/types/metadata.ts
export type InstallCheck = {
  command: string[];
  version_regex: string;
};

export type InputSpec = {
  name: string;
  label: string;
  kind: 'text' | 'secret' | 'email' | 'path';
  placeholder?: string | null;
};

export type LoginFlowSpec = {
  kind: string;
  display_name: string;
  description: string;
  requires_inputs: InputSpec[];
};

export type PlanOption = {
  id: string;
  label: string;
  description: string;
};

export type BackendMetadata = {
  kind: string;
  display_name: string;
  icon_url: string | null;
  install_check: InstallCheck;
  login_flows: LoginFlowSpec[];
  plan_options: PlanOption[] | null;
  config_schema: Record<string, unknown>;
  supports_multi_account: boolean;
  isolation_env_var: string | null;
};
```

```ts
// packages/ts-core/src/events.ts
export type AiAccountsEvent =
  | { type: 'wizard.opened'; backendKind: string }
  | { type: 'wizard.step'; backendKind: string; step: string }
  | { type: 'wizard.account.created'; backendKind: string; accountId: string }
  | { type: 'wizard.closed'; backendKind: string; reason: 'done' | 'skip' | 'cancel' }
  | { type: 'login.started'; sessionId: string; backendKind: string; flow: string }
  | { type: 'login.prompt'; sessionId: string; promptKind: 'url' | 'text' }
  | { type: 'login.completed'; sessionId: string; accountId: string }
  | { type: 'login.failed'; sessionId: string; code: string; message: string }
  | { type: 'internal.handler_error'; error: string; original: AiAccountsEvent };

export type AiAccountsEventHandler = (event: AiAccountsEvent) => void;
```

- [ ] **Step 4: Run passing test**

```bash
pnpm --filter @ai-accounts/ts-core test -- --run
```
Expected: all passing

- [ ] **Step 5: Commit**

```bash
git add packages/ts-core/src/types/ packages/ts-core/src/events.ts \
        packages/ts-core/tests/types.test.ts
git commit -m "feat(ts-core): login + metadata + AiAccountsEvent types"
```

---

## Task 16: ts-core — `LoginStreamSession` (SSE consumer)

**Files:**
- Create: `packages/ts-core/src/client/login-stream.ts`
- Modify: `packages/ts-core/src/client/index.ts`
- Test: `packages/ts-core/tests/login-stream.test.ts`

- [ ] **Step 1: Write failing test**

```ts
// packages/ts-core/tests/login-stream.test.ts
import { describe, it, expect, vi } from 'vitest';
import { AiAccountsClient } from '../src/client';
import type { LoginEvent } from '../src/types/login';

describe('AiAccountsClient.beginLogin', () => {
  it('POSTs flow_kind + inputs and returns session_id', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 201,
      statusText: 'Created',
      json: async () => ({ session_id: 'sess-abc' }),
    } as unknown as Response);

    const client = new AiAccountsClient({ baseUrl: 'http://test', fetch: fetchMock });
    const r = await client.beginLogin('bkd-1', 'api_key', { key: 'sk-x' });
    expect(r.session_id).toBe('sess-abc');

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('http://test/api/v1/backends/bkd-1/login/begin');
    expect((init as RequestInit).method).toBe('POST');
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({
      flow_kind: 'api_key',
      inputs: { key: 'sk-x' },
    });
  });

  it('respondLogin POSTs prompt + answer', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 204,
      statusText: 'No Content',
      json: async () => ({}),
    } as unknown as Response);
    const client = new AiAccountsClient({ baseUrl: 'http://test', fetch: fetchMock });
    await client.respondLogin('bkd-1', 'sess-abc', 'p-1', 'the-answer');
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('http://test/api/v1/backends/bkd-1/login/respond');
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({
      session_id: 'sess-abc',
      prompt_id: 'p-1',
      answer: 'the-answer',
    });
  });

  it('cancelLogin POSTs session_id', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 204,
      statusText: 'No Content',
      json: async () => ({}),
    } as unknown as Response);
    const client = new AiAccountsClient({ baseUrl: 'http://test', fetch: fetchMock });
    await client.cancelLogin('bkd-1', 'sess-abc');
    const [url] = fetchMock.mock.calls[0];
    expect(url).toBe('http://test/api/v1/backends/bkd-1/login/cancel');
  });
});

describe('streamLogin', () => {
  it('parses SSE data lines into LoginEvent', async () => {
    const body = [
      'event: login',
      'data: {"type":"text_prompt","prompt_id":"p","prompt":"key","hidden":true}',
      '',
      'event: login',
      'data: {"type":"complete","account_id":"bkd-1","backend_status":"validating"}',
      '',
    ].join('\n');

    const encoder = new TextEncoder();
    const stream = new ReadableStream({
      start(controller) {
        controller.enqueue(encoder.encode(body));
        controller.close();
      },
    });

    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      statusText: 'OK',
      body: stream,
      headers: new Headers({ 'content-type': 'text/event-stream' }),
    } as unknown as Response);

    const client = new AiAccountsClient({ baseUrl: 'http://test', fetch: fetchMock });
    const events: LoginEvent[] = [];
    for await (const e of client.streamLogin('bkd-1', 'sess-abc')) {
      events.push(e);
    }
    expect(events).toHaveLength(2);
    expect(events[0].type).toBe('text_prompt');
    expect(events[1].type).toBe('complete');
  });
});
```

- [ ] **Step 2: Run failing test**

```bash
pnpm --filter @ai-accounts/ts-core test -- --run
```
Expected: FAIL

- [ ] **Step 3: Write SSE consumer**

```ts
// packages/ts-core/src/client/login-stream.ts
import type { LoginEvent } from '../types/login';

export async function* parseSseLoginEvents(
  response: Response
): AsyncIterable<LoginEvent> {
  if (!response.body) return;
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      while (true) {
        const sep = buffer.indexOf('\n\n');
        if (sep === -1) break;
        const frame = buffer.slice(0, sep);
        buffer = buffer.slice(sep + 2);

        const dataLine = frame.split('\n').find((l) => l.startsWith('data: '));
        if (!dataLine) continue;
        const payload = dataLine.slice(6);
        try {
          yield JSON.parse(payload) as LoginEvent;
        } catch {
          // malformed frame — skip
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}
```

- [ ] **Step 4: Extend `AiAccountsClient`**

Append to `packages/ts-core/src/client/index.ts`:

```ts
import { parseSseLoginEvents } from './login-stream';
import type { LoginEvent, LoginFlowKind } from '../types/login';
import type { BackendMetadata } from '../types/metadata';

// Inside AiAccountsClient class:

async beginLogin(
  accountId: string,
  flowKind: LoginFlowKind,
  inputs: Record<string, string>
): Promise<{ session_id: string }> {
  return this._request<{ session_id: string }>(
    `/api/v1/backends/${accountId}/login/begin`,
    { method: 'POST', body: JSON.stringify({ flow_kind: flowKind, inputs }) }
  );
}

async respondLogin(
  accountId: string,
  sessionId: string,
  promptId: string,
  answer: string
): Promise<void> {
  await this._request(
    `/api/v1/backends/${accountId}/login/respond`,
    {
      method: 'POST',
      body: JSON.stringify({ session_id: sessionId, prompt_id: promptId, answer }),
    }
  );
}

async cancelLogin(accountId: string, sessionId: string): Promise<void> {
  await this._request(
    `/api/v1/backends/${accountId}/login/cancel`,
    { method: 'POST', body: JSON.stringify({ session_id: sessionId }) }
  );
}

async *streamLogin(
  accountId: string,
  sessionId: string
): AsyncIterable<LoginEvent> {
  const url = `${this._baseUrl}/api/v1/backends/${accountId}/login/stream?session_id=${encodeURIComponent(sessionId)}`;
  const response = await this._fetch(url, {
    method: 'GET',
    headers: {
      Accept: 'text/event-stream',
      ...this._authHeaders(),
    },
  });
  if (!response.ok) {
    throw new Error(`streamLogin failed: ${response.status} ${response.statusText}`);
  }
  yield* parseSseLoginEvents(response);
}

async getBackendMetadata(): Promise<{ items: BackendMetadata[] }> {
  return this._request<{ items: BackendMetadata[] }>('/api/v1/backends/_meta', {
    method: 'GET',
  });
}
```

Adjust `_authHeaders()` / `_request` to match existing private helpers in the 0.2.x client.

- [ ] **Step 5: Run passing tests**

```bash
pnpm --filter @ai-accounts/ts-core test -- --run
```
Expected: all passing (including existing 0.2.x tests)

- [ ] **Step 6: Commit**

```bash
git add packages/ts-core/src/client/login-stream.ts \
        packages/ts-core/src/client/index.ts \
        packages/ts-core/tests/login-stream.test.ts
git commit -m "feat(ts-core): beginLogin/respondLogin/cancelLogin/streamLogin + metadata"
```

---

## Task 17: vue-headless — plugin + event bus + auth hook

**Files:**
- Create: `packages/vue-headless/src/plugin.ts`
- Create: `packages/vue-headless/src/injection-keys.ts`
- Create: `packages/vue-headless/src/composables/useAiAccounts.ts`
- Modify: `packages/vue-headless/src/index.ts`
- Test: `packages/vue-headless/tests/plugin.test.ts`

- [ ] **Step 1: Write failing test**

```ts
// packages/vue-headless/tests/plugin.test.ts
import { describe, it, expect, vi } from 'vitest';
import { createApp, defineComponent, h } from 'vue';
import { mount } from '@vue/test-utils';
import { aiAccountsPlugin } from '../src/plugin';
import { useAiAccounts } from '../src/composables/useAiAccounts';
import { AiAccountsClient } from '@ai-accounts/ts-core';

const makeClient = () =>
  new AiAccountsClient({ baseUrl: 'http://t', fetch: vi.fn() });

describe('aiAccountsPlugin', () => {
  it('provides client to descendants', () => {
    let captured: unknown;
    const Child = defineComponent({
      setup() {
        const ctx = useAiAccounts();
        captured = ctx.client;
        return () => h('div');
      },
    });
    const app = createApp(Child);
    const client = makeClient();
    app.use(aiAccountsPlugin, { client });
    app.mount(document.createElement('div'));
    expect(captured).toBe(client);
  });

  it('routes events through onEvent handler', () => {
    const handler = vi.fn();
    const Child = defineComponent({
      setup() {
        const { emit } = useAiAccounts();
        emit({ type: 'wizard.opened', backendKind: 'claude' });
        return () => h('div');
      },
    });
    const app = createApp(Child);
    app.use(aiAccountsPlugin, { client: makeClient(), onEvent: handler });
    app.mount(document.createElement('div'));
    expect(handler).toHaveBeenCalledWith({ type: 'wizard.opened', backendKind: 'claude' });
  });

  it('catches handler errors as internal.handler_error', () => {
    const events: unknown[] = [];
    const handler = vi.fn().mockImplementation((e) => {
      events.push(e);
      if (e.type === 'wizard.opened') throw new Error('boom');
    });
    const Child = defineComponent({
      setup() {
        const { emit } = useAiAccounts();
        emit({ type: 'wizard.opened', backendKind: 'claude' });
        return () => h('div');
      },
    });
    const app = createApp(Child);
    app.use(aiAccountsPlugin, { client: makeClient(), onEvent: handler });
    app.mount(document.createElement('div'));
    expect(events).toHaveLength(2);
    expect((events[1] as { type: string }).type).toBe('internal.handler_error');
  });
});
```

- [ ] **Step 2: Run failing test**

```bash
pnpm --filter @ai-accounts/vue-headless test -- --run
```
Expected: FAIL

- [ ] **Step 3: Write plugin + composable**

```ts
// packages/vue-headless/src/injection-keys.ts
import type { InjectionKey } from 'vue';
import type { AiAccountsClient } from '@ai-accounts/ts-core';
import type { AiAccountsEvent, AiAccountsEventHandler } from '@ai-accounts/ts-core';

export type AiAccountsContext = {
  client: AiAccountsClient;
  emit: (event: AiAccountsEvent) => void;
};

export const aiAccountsKey: InjectionKey<AiAccountsContext> = Symbol('aiAccounts');
```

```ts
// packages/vue-headless/src/plugin.ts
import type { App } from 'vue';
import type { AiAccountsClient, AiAccountsEvent, AiAccountsEventHandler } from '@ai-accounts/ts-core';
import { aiAccountsKey, type AiAccountsContext } from './injection-keys';

export type AiAccountsPluginOptions = {
  client: AiAccountsClient;
  onEvent?: AiAccountsEventHandler;
};

export const aiAccountsPlugin = {
  install(app: App, options: AiAccountsPluginOptions) {
    const onEvent = options.onEvent ?? (() => {});

    const emit = (event: AiAccountsEvent) => {
      try {
        onEvent(event);
      } catch (err) {
        try {
          onEvent({
            type: 'internal.handler_error',
            error: err instanceof Error ? err.message : String(err),
            original: event,
          });
        } catch {
          // swallow — event bus must never propagate
        }
      }
    };

    const ctx: AiAccountsContext = {
      client: options.client,
      emit,
    };

    app.provide(aiAccountsKey, ctx);
  },
};
```

```ts
// packages/vue-headless/src/composables/useAiAccounts.ts
import { inject } from 'vue';
import { aiAccountsKey, type AiAccountsContext } from '../injection-keys';

export function useAiAccounts(): AiAccountsContext {
  const ctx = inject(aiAccountsKey);
  if (!ctx) {
    throw new Error(
      'useAiAccounts() called outside an app that installed aiAccountsPlugin'
    );
  }
  return ctx;
}
```

```ts
// packages/vue-headless/src/index.ts
export { aiAccountsPlugin, type AiAccountsPluginOptions } from './plugin';
export { useAiAccounts } from './composables/useAiAccounts';
export { aiAccountsKey, type AiAccountsContext } from './injection-keys';
```

- [ ] **Step 4: Run passing tests**

```bash
pnpm --filter @ai-accounts/vue-headless test -- --run
```
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add packages/vue-headless/src/plugin.ts \
        packages/vue-headless/src/injection-keys.ts \
        packages/vue-headless/src/composables/useAiAccounts.ts \
        packages/vue-headless/src/index.ts \
        packages/vue-headless/tests/plugin.test.ts
git commit -m "feat(vue-headless): aiAccountsPlugin + useAiAccounts + event bus"
```

---

## Task 18: vue-headless — `useBackendRegistry`

**Files:**
- Create: `packages/vue-headless/src/composables/useBackendRegistry.ts`
- Modify: `packages/vue-headless/src/index.ts`
- Test: `packages/vue-headless/tests/useBackendRegistry.test.ts`

- [ ] **Step 1: Write failing test**

```ts
// packages/vue-headless/tests/useBackendRegistry.test.ts
import { describe, it, expect, vi } from 'vitest';
import { createApp, defineComponent, h, nextTick } from 'vue';
import { aiAccountsPlugin } from '../src/plugin';
import { useBackendRegistry } from '../src/composables/useBackendRegistry';
import { AiAccountsClient } from '@ai-accounts/ts-core';

const mkClient = (items: unknown[]) => {
  const fetchMock = vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    statusText: 'OK',
    json: async () => ({ items }),
  } as unknown as Response);
  return new AiAccountsClient({ baseUrl: 'http://t', fetch: fetchMock });
};

describe('useBackendRegistry', () => {
  it('fetches /_meta and populates reactive list', async () => {
    const items = [
      { kind: 'claude', display_name: 'Claude', icon_url: null,
        install_check: { command: ['claude'], version_regex: '(\\d)' },
        login_flows: [], plan_options: null, config_schema: {},
        supports_multi_account: true, isolation_env_var: 'CLAUDE_CONFIG_DIR' },
    ];
    let captured: ReturnType<typeof useBackendRegistry> | null = null;
    const Child = defineComponent({
      async setup() {
        captured = useBackendRegistry();
        await captured.load();
        return () => h('div');
      },
    });
    const app = createApp(Child);
    app.use(aiAccountsPlugin, { client: mkClient(items) });
    app.mount(document.createElement('div'));
    await nextTick();
    expect(captured!.backends.value).toHaveLength(1);
    expect(captured!.get('claude')?.display_name).toBe('Claude');
  });
});
```

- [ ] **Step 2: Run failing test**

- [ ] **Step 3: Write composable**

```ts
// packages/vue-headless/src/composables/useBackendRegistry.ts
import { ref, type Ref } from 'vue';
import type { BackendMetadata } from '@ai-accounts/ts-core';
import { useAiAccounts } from './useAiAccounts';

type Registry = {
  backends: Ref<BackendMetadata[]>;
  loaded: Ref<boolean>;
  load: () => Promise<void>;
  get: (kind: string) => BackendMetadata | undefined;
};

export function useBackendRegistry(): Registry {
  const { client } = useAiAccounts();
  const backends = ref<BackendMetadata[]>([]);
  const loaded = ref(false);

  async function load() {
    const result = await client.getBackendMetadata();
    backends.value = result.items;
    loaded.value = true;
  }

  function get(kind: string): BackendMetadata | undefined {
    return backends.value.find((m) => m.kind === kind);
  }

  return { backends, loaded, load, get };
}
```

Add export to `packages/vue-headless/src/index.ts`.

- [ ] **Step 4: Run passing test**

- [ ] **Step 5: Commit**

```bash
git add packages/vue-headless/src/composables/useBackendRegistry.ts \
        packages/vue-headless/src/index.ts \
        packages/vue-headless/tests/useBackendRegistry.test.ts
git commit -m "feat(vue-headless): useBackendRegistry composable"
```

---

## Task 19: vue-headless — `useLoginSession`

**Files:**
- Create: `packages/vue-headless/src/composables/useLoginSession.ts`
- Modify: `packages/vue-headless/src/index.ts`
- Test: `packages/vue-headless/tests/useLoginSession.test.ts`

**Purpose:** Wizard-facing state machine. Caller invokes `start(accountId, flowKind, inputs)`, gets reactive `currentPrompt`, `stdoutLines`, `status`, `error`, `complete`. Internally: calls `client.beginLogin`, then consumes `client.streamLogin`, routing events into reactive refs. Exposes `respond(answer)` and `cancel()`.

- [ ] **Step 1: Write failing test**

```ts
// packages/vue-headless/tests/useLoginSession.test.ts
import { describe, it, expect, vi } from 'vitest';
import { createApp, defineComponent, h, nextTick } from 'vue';
import { aiAccountsPlugin } from '../src/plugin';
import { useLoginSession } from '../src/composables/useLoginSession';
import { AiAccountsClient } from '@ai-accounts/ts-core';
import type { LoginEvent } from '@ai-accounts/ts-core';

function mockClient(events: LoginEvent[]) {
  const client = new AiAccountsClient({ baseUrl: 'http://t', fetch: vi.fn() });
  (client as unknown as { beginLogin: unknown }).beginLogin = vi
    .fn()
    .mockResolvedValue({ session_id: 'sess-1' });
  (client as unknown as { streamLogin: unknown }).streamLogin = async function* () {
    for (const e of events) yield e;
  };
  (client as unknown as { respondLogin: unknown }).respondLogin = vi
    .fn()
    .mockResolvedValue(undefined);
  (client as unknown as { cancelLogin: unknown }).cancelLogin = vi
    .fn()
    .mockResolvedValue(undefined);
  return client;
}

describe('useLoginSession', () => {
  it('transitions through text_prompt → complete', async () => {
    const events: LoginEvent[] = [
      { type: 'text_prompt', prompt_id: 'p', prompt: 'key', hidden: true },
      { type: 'complete', account_id: 'bkd-1', backend_status: 'validating' },
    ];
    let captured: ReturnType<typeof useLoginSession> | null = null;
    const Child = defineComponent({
      setup() {
        captured = useLoginSession();
        return () => h('div');
      },
    });
    const app = createApp(Child);
    app.use(aiAccountsPlugin, { client: mockClient(events) });
    app.mount(document.createElement('div'));

    await captured!.start('bkd-1', 'api_key', {});
    await nextTick();
    expect(captured!.status.value).toBe('complete');
    expect(captured!.accountId.value).toBe('bkd-1');
  });

  it('captures url_prompt', async () => {
    const events: LoginEvent[] = [
      { type: 'url_prompt', prompt_id: 'u', url: 'https://x', user_code: 'A-1' },
      { type: 'complete', account_id: 'bkd-1', backend_status: 'validating' },
    ];
    let captured: ReturnType<typeof useLoginSession> | null = null;
    const Child = defineComponent({
      setup() {
        captured = useLoginSession();
        return () => h('div');
      },
    });
    const app = createApp(Child);
    app.use(aiAccountsPlugin, { client: mockClient(events) });
    app.mount(document.createElement('div'));

    await captured!.start('bkd-1', 'cli_browser', {});
    expect(captured!.urlPrompt.value?.url).toBe('https://x');
    expect(captured!.urlPrompt.value?.user_code).toBe('A-1');
  });
});
```

- [ ] **Step 2: Run failing test**

- [ ] **Step 3: Write composable**

```ts
// packages/vue-headless/src/composables/useLoginSession.ts
import { ref, type Ref } from 'vue';
import type {
  LoginEvent,
  LoginFlowKind,
  TextPrompt,
  UrlPrompt,
} from '@ai-accounts/ts-core';
import { useAiAccounts } from './useAiAccounts';

export type LoginStatus = 'idle' | 'running' | 'complete' | 'failed' | 'cancelled';

export type UseLoginSession = {
  status: Ref<LoginStatus>;
  sessionId: Ref<string | null>;
  accountId: Ref<string | null>;
  urlPrompt: Ref<UrlPrompt | null>;
  textPrompt: Ref<TextPrompt | null>;
  stdoutLines: Ref<string[]>;
  errorCode: Ref<string | null>;
  errorMessage: Ref<string | null>;
  start: (accountId: string, flow: LoginFlowKind, inputs: Record<string, string>) => Promise<void>;
  respond: (answer: string) => Promise<void>;
  cancel: () => Promise<void>;
};

export function useLoginSession(): UseLoginSession {
  const { client, emit } = useAiAccounts();
  const status = ref<LoginStatus>('idle');
  const sessionId = ref<string | null>(null);
  const accountId = ref<string | null>(null);
  const urlPrompt = ref<UrlPrompt | null>(null);
  const textPrompt = ref<TextPrompt | null>(null);
  const stdoutLines = ref<string[]>([]);
  const errorCode = ref<string | null>(null);
  const errorMessage = ref<string | null>(null);

  async function start(
    id: string,
    flow: LoginFlowKind,
    inputs: Record<string, string>
  ): Promise<void> {
    accountId.value = id;
    status.value = 'running';
    urlPrompt.value = null;
    textPrompt.value = null;
    stdoutLines.value = [];
    errorCode.value = null;
    errorMessage.value = null;

    const { session_id } = await client.beginLogin(id, flow, inputs);
    sessionId.value = session_id;
    emit({ type: 'login.started', sessionId: session_id, backendKind: '', flow });

    for await (const event of client.streamLogin(id, session_id)) {
      dispatch(event);
      if (status.value !== 'running') return;
    }
  }

  function dispatch(event: LoginEvent) {
    switch (event.type) {
      case 'url_prompt':
        urlPrompt.value = event;
        emit({ type: 'login.prompt', sessionId: sessionId.value!, promptKind: 'url' });
        break;
      case 'text_prompt':
        textPrompt.value = event;
        emit({ type: 'login.prompt', sessionId: sessionId.value!, promptKind: 'text' });
        break;
      case 'stdout':
        stdoutLines.value = [...stdoutLines.value, event.text];
        break;
      case 'progress':
        // host can listen via onEvent if it cares
        break;
      case 'complete':
        status.value = 'complete';
        accountId.value = event.account_id || accountId.value;
        emit({
          type: 'login.completed',
          sessionId: sessionId.value!,
          accountId: event.account_id,
        });
        break;
      case 'failed':
        status.value = 'failed';
        errorCode.value = event.code;
        errorMessage.value = event.message;
        emit({
          type: 'login.failed',
          sessionId: sessionId.value!,
          code: event.code,
          message: event.message,
        });
        break;
    }
  }

  async function respond(answer: string): Promise<void> {
    if (!sessionId.value || !accountId.value || !textPrompt.value) return;
    const promptId = textPrompt.value.prompt_id;
    textPrompt.value = null;
    await client.respondLogin(accountId.value, sessionId.value, promptId, answer);
  }

  async function cancel(): Promise<void> {
    if (!sessionId.value || !accountId.value) return;
    await client.cancelLogin(accountId.value, sessionId.value);
    status.value = 'cancelled';
  }

  return {
    status,
    sessionId,
    accountId,
    urlPrompt,
    textPrompt,
    stdoutLines,
    errorCode,
    errorMessage,
    start,
    respond,
    cancel,
  };
}
```

Add export to `packages/vue-headless/src/index.ts`.

- [ ] **Step 4: Run passing tests**

- [ ] **Step 5: Commit**

```bash
git add packages/vue-headless/src/composables/useLoginSession.ts \
        packages/vue-headless/src/index.ts \
        packages/vue-headless/tests/useLoginSession.test.ts
git commit -m "feat(vue-headless): useLoginSession state machine"
```

---

## Task 20: vue-styled — `LoginStream.vue`

**Files:**
- Create: `packages/vue-styled/src/LoginStream.vue`
- Test: `packages/vue-styled/tests/LoginStream.test.ts`

**Purpose:** Renders a `useLoginSession` result. Shows URL prompt with copy button + "Open in browser" link, text prompt with input, stdout scrollback, error state. Pure presentation — wizard composes it.

Props: `session: UseLoginSession`, `showStdout?: boolean = true`.

Emits: `respond(answer: string)`, `cancel()`.

- [ ] **Step 1: Write failing test**

```ts
// packages/vue-styled/tests/LoginStream.test.ts
import { describe, it, expect } from 'vitest';
import { mount } from '@vue/test-utils';
import { ref } from 'vue';
import LoginStream from '../src/LoginStream.vue';

function mkSession(overrides: Record<string, unknown> = {}) {
  return {
    status: ref('running'),
    sessionId: ref('s-1'),
    accountId: ref('bkd-1'),
    urlPrompt: ref(null),
    textPrompt: ref(null),
    stdoutLines: ref([]),
    errorCode: ref(null),
    errorMessage: ref(null),
    start: async () => {},
    respond: async () => {},
    cancel: async () => {},
    ...overrides,
  };
}

describe('LoginStream', () => {
  it('renders URL prompt with user code', () => {
    const session = mkSession({
      urlPrompt: ref({ type: 'url_prompt', prompt_id: 'u', url: 'https://x.test', user_code: 'ABCD' }),
    });
    const w = mount(LoginStream, { props: { session } });
    expect(w.text()).toContain('https://x.test');
    expect(w.text()).toContain('ABCD');
  });

  it('renders text prompt input', () => {
    const session = mkSession({
      textPrompt: ref({ type: 'text_prompt', prompt_id: 'k', prompt: 'API key', hidden: true }),
    });
    const w = mount(LoginStream, { props: { session } });
    expect(w.find('input[type="password"]').exists()).toBe(true);
  });

  it('emits respond when form submitted', async () => {
    let captured = '';
    const session = mkSession({
      textPrompt: ref({ type: 'text_prompt', prompt_id: 'k', prompt: 'key', hidden: false }),
      respond: async (a: string) => { captured = a; },
    });
    const w = mount(LoginStream, { props: { session } });
    await w.find('input').setValue('hello');
    await w.find('form').trigger('submit');
    expect(captured).toBe('hello');
  });

  it('renders error state', () => {
    const session = mkSession({
      status: ref('failed'),
      errorCode: ref('cli_not_found'),
      errorMessage: ref('claude not installed'),
    });
    const w = mount(LoginStream, { props: { session } });
    expect(w.text()).toContain('claude not installed');
  });
});
```

- [ ] **Step 2: Run failing test**

```bash
pnpm --filter @ai-accounts/vue-styled test -- --run
```

- [ ] **Step 3: Write component**

```vue
<!-- packages/vue-styled/src/LoginStream.vue -->
<script setup lang="ts">
import { ref } from 'vue';
import type { UseLoginSession } from '@ai-accounts/vue-headless';

const props = defineProps<{
  session: UseLoginSession;
  showStdout?: boolean;
}>();

const answer = ref('');

async function submit() {
  const value = answer.value;
  answer.value = '';
  await props.session.respond(value);
}
</script>

<template>
  <div class="aia-login-stream">
    <!-- URL prompt -->
    <div v-if="session.urlPrompt.value" class="aia-url-prompt">
      <p class="aia-label">Open this URL to authenticate:</p>
      <a :href="session.urlPrompt.value.url" target="_blank" rel="noopener">
        {{ session.urlPrompt.value.url }}
      </a>
      <p v-if="session.urlPrompt.value.user_code" class="aia-code">
        Code: <code>{{ session.urlPrompt.value.user_code }}</code>
      </p>
    </div>

    <!-- Text prompt -->
    <form v-if="session.textPrompt.value" class="aia-text-prompt" @submit.prevent="submit">
      <label>
        {{ session.textPrompt.value.prompt }}
        <input
          v-model="answer"
          :type="session.textPrompt.value.hidden ? 'password' : 'text'"
          autocomplete="off"
        />
      </label>
      <button type="submit">Continue</button>
    </form>

    <!-- Stdout -->
    <pre v-if="showStdout !== false && session.stdoutLines.value.length" class="aia-stdout">{{
      session.stdoutLines.value.join('')
    }}</pre>

    <!-- Error -->
    <div v-if="session.status.value === 'failed'" class="aia-error">
      <strong>{{ session.errorCode.value }}</strong>
      <p>{{ session.errorMessage.value }}</p>
    </div>

    <!-- Cancel -->
    <button
      v-if="session.status.value === 'running'"
      type="button"
      @click="session.cancel()"
    >
      Cancel
    </button>
  </div>
</template>

<style scoped>
.aia-login-stream { display: flex; flex-direction: column; gap: 1rem; }
.aia-url-prompt a { word-break: break-all; }
.aia-code code { font-family: var(--aia-font-mono, monospace); font-size: 1.2em; }
.aia-stdout {
  background: var(--aia-stdout-bg, #111);
  color: var(--aia-stdout-fg, #eee);
  padding: 0.75rem;
  max-height: 240px;
  overflow: auto;
  font-family: var(--aia-font-mono, monospace);
  font-size: 0.85em;
}
.aia-error { color: var(--aia-error, #c00); }
</style>
```

- [ ] **Step 4: Run passing tests**

- [ ] **Step 5: Commit**

```bash
git add packages/vue-styled/src/LoginStream.vue \
        packages/vue-styled/tests/LoginStream.test.ts
git commit -m "feat(vue-styled): LoginStream component"
```

---

## Task 21: vue-styled — `BackendPicker.vue`

**Files:**
- Create: `packages/vue-styled/src/BackendPicker.vue`
- Test: `packages/vue-styled/tests/BackendPicker.test.ts`

**Purpose:** Split the wizard's "choose AI service" step into its own component. Reads from `useBackendRegistry`. Emits `pick(kind)`. Shows install state badge, display name, icon, short description per backend.

Props: `installStatus?: Record<string, { installed: boolean; version: string | null }>`.
Emits: `pick(kind: string)`.

- [ ] **Step 1: Write failing test**

```ts
// packages/vue-styled/tests/BackendPicker.test.ts
import { describe, it, expect, vi } from 'vitest';
import { mount } from '@vue/test-utils';
import { createApp, defineComponent, h } from 'vue';
import { aiAccountsPlugin } from '@ai-accounts/vue-headless';
import { AiAccountsClient } from '@ai-accounts/ts-core';
import BackendPicker from '../src/BackendPicker.vue';

const items = [
  { kind: 'claude', display_name: 'Claude Code', icon_url: null,
    install_check: { command: [], version_regex: '' }, login_flows: [],
    plan_options: null, config_schema: {}, supports_multi_account: true,
    isolation_env_var: 'CLAUDE_CONFIG_DIR' },
  { kind: 'codex', display_name: 'Codex', icon_url: null,
    install_check: { command: [], version_regex: '' }, login_flows: [],
    plan_options: null, config_schema: {}, supports_multi_account: true,
    isolation_env_var: 'CODEX_HOME' },
];

function mkClient() {
  const fetchMock = vi.fn().mockResolvedValue({
    ok: true, status: 200, statusText: 'OK',
    json: async () => ({ items }),
  } as unknown as Response);
  return new AiAccountsClient({ baseUrl: 'http://t', fetch: fetchMock });
}

describe('BackendPicker', () => {
  it('renders registered backends after load', async () => {
    const Wrapper = defineComponent({
      components: { BackendPicker },
      template: '<BackendPicker />',
    });
    const app = createApp(Wrapper);
    app.use(aiAccountsPlugin, { client: mkClient() });
    const w = mount(Wrapper, {
      global: { plugins: [[aiAccountsPlugin, { client: mkClient() }]] },
    });
    await new Promise((r) => setTimeout(r, 10));
    expect(w.text()).toContain('Claude Code');
    expect(w.text()).toContain('Codex');
  });
});
```

- [ ] **Step 2: Run failing test**

- [ ] **Step 3: Write component**

```vue
<!-- packages/vue-styled/src/BackendPicker.vue -->
<script setup lang="ts">
import { onMounted } from 'vue';
import { useBackendRegistry } from '@ai-accounts/vue-headless';

const props = defineProps<{
  installStatus?: Record<string, { installed: boolean; version: string | null }>;
}>();

const emit = defineEmits<{
  (e: 'pick', kind: string): void;
}>();

const registry = useBackendRegistry();

onMounted(async () => {
  if (!registry.loaded.value) await registry.load();
});
</script>

<template>
  <ul class="aia-backend-picker">
    <li v-for="meta in registry.backends.value" :key="meta.kind">
      <button type="button" @click="emit('pick', meta.kind)">
        <img v-if="meta.icon_url" :src="meta.icon_url" :alt="meta.display_name" />
        <div class="aia-backend-info">
          <strong>{{ meta.display_name }}</strong>
          <span
            v-if="props.installStatus?.[meta.kind]?.installed"
            class="aia-installed"
          >
            installed{{
              props.installStatus[meta.kind].version
                ? ' v' + props.installStatus[meta.kind].version
                : ''
            }}
          </span>
          <span v-else class="aia-not-installed">not detected</span>
        </div>
      </button>
    </li>
  </ul>
</template>

<style scoped>
.aia-backend-picker { display: grid; gap: 0.75rem; list-style: none; padding: 0; }
.aia-backend-picker button {
  display: flex; gap: 0.75rem; width: 100%; padding: 0.75rem 1rem;
  background: var(--aia-card-bg, #1a1a1a); color: var(--aia-card-fg, #eee);
  border: 1px solid var(--aia-border, #333); border-radius: 8px;
  cursor: pointer; text-align: left;
}
.aia-backend-picker button:hover { background: var(--aia-card-hover, #222); }
.aia-installed { color: var(--aia-ok, #4c8); }
.aia-not-installed { color: var(--aia-warn, #c83); }
</style>
```

- [ ] **Step 4: Run passing tests**

- [ ] **Step 5: Commit**

```bash
git add packages/vue-styled/src/BackendPicker.vue \
        packages/vue-styled/tests/BackendPicker.test.ts
git commit -m "feat(vue-styled): BackendPicker"
```

---

## Task 22: vue-styled — `AccountEditForm.vue`

**Files:**
- Create: `packages/vue-styled/src/AccountEditForm.vue`
- Test: `packages/vue-styled/tests/AccountEditForm.test.ts`

**Purpose:** Inline edit form for an existing account. Ported from Agented's `BackendDetailPage.vue` inline edit section. Edits `display_name` + backend-specific config fields (driven by `config_schema`). Submits via `client.updateBackend(id, patch)`.

Props: `account: { id, kind, display_name, config }`, `metadata: BackendMetadata`.
Emits: `saved(updated)`, `cancel()`.

- [ ] **Step 1: Write failing test** — mount with a fake account + metadata, verify fields render from schema, verify `saved` event fires with updated values.

- [ ] **Step 2: Run failing test**

- [ ] **Step 3: Write component** — render inputs per `metadata.config_schema.properties`, `v-model` against local reactive copy, call `client.updateBackend` on submit.

- [ ] **Step 4: Run passing tests**

- [ ] **Step 5: Commit**

```bash
git add packages/vue-styled/src/AccountEditForm.vue \
        packages/vue-styled/tests/AccountEditForm.test.ts
git commit -m "feat(vue-styled): AccountEditForm (inline edit restored)"
```

---

## Task 23: vue-styled — `AccountWizard.vue` (the big port)

**Context:** The 1947-line Agented wizard at `frontend/src/components/backends/AccountWizard.vue` is the canonical source. Port it verbatim, then surgically refactor the import surface.

**Files:**
- Rewrite: `packages/vue-styled/src/AccountWizard.vue`
- Modify: `packages/vue-styled/src/index.ts`
- Test: `packages/vue-styled/tests/AccountWizard.test.ts`

**Refactoring checklist (apply to the copied file):**
1. Delete imports from `@/services/api/backends`, `@/stores/*`, `@/composables/useTourMachine`.
2. Replace `backendApi.*` calls with `client.*` (from `useAiAccounts().client`).
3. Replace hardcoded `BACKEND_METADATA` / `BACKEND_LOGIN_INFO` lookups with `useBackendRegistry().get(kind)`.
4. Replace inline SSE connect logic (`backendApi.startConnect` + `EventSource`) with `useLoginSession()`; render `<LoginStream :session="loginSession" />`.
5. Replace `useTourMachine` calls with `emit(...)` through the event bus.
6. Props instead of store reads:
   - `:initialBackendKind` (optional) — skip picker if set
   - `:allowSkip` (bool)
7. Emits:
   - `close` — user closed the modal
   - `done({ accountId })` — account fully created
   - `skip()`
   - `addAnother()`

- [ ] **Step 1: Copy source verbatim**

```bash
cp ~/Developer/Projects/Agented-ai-accounts-migration/frontend/src/components/backends/AccountWizard.vue \
   ~/Developer/Projects/ai-accounts/packages/vue-styled/src/AccountWizard.vue
cd ~/Developer/Projects/ai-accounts
git add packages/vue-styled/src/AccountWizard.vue
git commit -m "chore(vue-styled): vendor AccountWizard.vue verbatim from Agented"
```

- [ ] **Step 2: Write failing smoke test**

```ts
// packages/vue-styled/tests/AccountWizard.test.ts
import { describe, it, expect, vi } from 'vitest';
import { mount } from '@vue/test-utils';
import { createApp, defineComponent, h } from 'vue';
import { aiAccountsPlugin } from '@ai-accounts/vue-headless';
import { AiAccountsClient } from '@ai-accounts/ts-core';
import AccountWizard from '../src/AccountWizard.vue';

function mkClient() {
  return new AiAccountsClient({
    baseUrl: 'http://t',
    fetch: vi.fn().mockResolvedValue({
      ok: true, status: 200, statusText: 'OK',
      json: async () => ({ items: [] }),
    } as unknown as Response),
  });
}

describe('AccountWizard', () => {
  it('mounts with aiAccountsPlugin installed', () => {
    const w = mount(AccountWizard, {
      global: {
        plugins: [[aiAccountsPlugin, { client: mkClient() }]],
      },
      props: { allowSkip: true },
    });
    expect(w.exists()).toBe(true);
  });

  it('renders backend picker when initialBackendKind is not set', async () => {
    // will fail until refactor complete
    const w = mount(AccountWizard, {
      global: { plugins: [[aiAccountsPlugin, { client: mkClient() }]] },
      props: {},
    });
    await new Promise((r) => setTimeout(r, 10));
    expect(w.findComponent({ name: 'BackendPicker' }).exists()).toBe(true);
  });

  it('emits done when a login session completes', async () => {
    // Integration — use mocked client that returns complete event immediately
    // Details of this test depend on the refactored wizard's step machine.
    // Focus: the `done` event fires with an accountId payload.
    // (The subagent implementing this task should flesh it out after refactor.)
  });
});
```

- [ ] **Step 3: Run failing test**

```bash
pnpm --filter @ai-accounts/vue-styled test -- --run
```
Expected: FAIL — the vendored file still imports from `@/services/api/backends`.

- [ ] **Step 4: Apply the refactor checklist**

This is surgical file editing. For each item in the checklist, grep for the offending import / call in the newly copied file and replace with the equivalent from `@ai-accounts/vue-headless` + `useAiAccounts`. Test after each change.

Example transform for the SSE connect path:

```ts
// BEFORE (Agented):
import { backendApi } from '@/services/api/backends';
const { sessionId } = await backendApi.startConnect(kind, payload);
const es = new EventSource(`/admin/backends/${kind}/connect/stream?session=${sessionId}`);
es.onmessage = (msg) => { /* parse + handle */ };

// AFTER (package):
import { useAiAccounts, useLoginSession } from '@ai-accounts/vue-headless';
const { client, emit } = useAiAccounts();
const loginSession = useLoginSession();
await loginSession.start(accountId, flowKind, inputs);
// <LoginStream :session="loginSession" /> renders the UI
```

Preserve every visual element (steps, add-another flow, CLIProxyAPI-specific branches, plan selector, install check, error states). Only the *data sources* change.

For each refactor sub-step, commit individually so history is traceable:

```bash
git add packages/vue-styled/src/AccountWizard.vue
git commit -m "refactor(vue-styled/wizard): replace backendApi with plugin client"

git add packages/vue-styled/src/AccountWizard.vue
git commit -m "refactor(vue-styled/wizard): useLoginSession for SSE + prompts"

git add packages/vue-styled/src/AccountWizard.vue
git commit -m "refactor(vue-styled/wizard): useBackendRegistry for metadata lookups"

git add packages/vue-styled/src/AccountWizard.vue
git commit -m "refactor(vue-styled/wizard): emit lifecycle events through bus"
```

- [ ] **Step 5: Run passing tests**

```bash
pnpm --filter @ai-accounts/vue-styled test -- --run
```
Expected: all passing (smoke test + every new component test).

- [ ] **Step 6: Export from package**

```ts
// packages/vue-styled/src/index.ts
export { default as AccountWizard } from './AccountWizard.vue';
export { default as BackendPicker } from './BackendPicker.vue';
export { default as LoginStream } from './LoginStream.vue';
export { default as AccountEditForm } from './AccountEditForm.vue';
```

```bash
git add packages/vue-styled/src/index.ts
git commit -m "feat(vue-styled): export AccountWizard + sub-components"
```

---

## Task 24: Publish `0.3.0-alpha.1` to npm + PyPI

**Files:**
- Modify: every `packages/*/pyproject.toml` — bump version to `0.3.0a1`
- Modify: every `packages/*/package.json` — bump version to `0.3.0-alpha.1`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Bump versions**

```bash
cd ~/Developer/Projects/ai-accounts
# Python packages
for pkg in core litestar; do
  sed -i '' -E 's/version = "[^"]+"/version = "0.3.0a1"/' packages/$pkg/pyproject.toml
done
# TS packages — use pnpm version in each
for pkg in ts-core vue-headless vue-styled; do
  (cd packages/$pkg && pnpm version 0.3.0-alpha.1 --no-git-tag-version)
done
```

- [ ] **Step 2: Update CHANGELOG**

```markdown
# CHANGELOG

## 0.3.0-alpha.1 — 2026-04-XX

### Added
- `LoginSession` ABC + `LoginEvent` discriminated union
- `BackendMetadata` served at `GET /api/v1/backends/_meta`
- `POST /api/v1/backends/{id}/login/begin` + SSE `/login/stream` + `/respond` + `/cancel`
- `CliOrchestrator` — PTY-based subprocess runner (ported from Agented)
- `ClaudeBackend`, `CodexBackend`, `GeminiBackend`, `OpenCodeBackend` with real login flows
- `@ai-accounts/vue-styled` `AccountWizard`, `BackendPicker`, `LoginStream`, `AccountEditForm`
- `@ai-accounts/vue-headless` `aiAccountsPlugin`, `useLoginSession`, `useBackendRegistry`, `useAiAccounts`
- Typed `AiAccountsEvent` event bus with `onEvent` hook

### Breaking
- `BackendProtocol.login()` → `begin_login() → LoginSession` (clean break from 0.2.x)
- 0.2.x npm/PyPI tags deprecated; upgrade path is to install 0.3.0 and replace shim usage

### Deprecated
- All 0.2.x releases — use 0.3.0+

(Next alphas: 0.3.0-alpha.2 = Chat, 0.3.0-alpha.3 = PTY.)
```

- [ ] **Step 3: Full monorepo test**

```bash
cd ~/Developer/Projects/ai-accounts
uv run --package ai-accounts-core pytest packages/core/tests/ -q
uv run --package ai-accounts-litestar pytest packages/litestar/tests/ -q
pnpm -r --filter '@ai-accounts/*' test -- --run
pnpm -r --filter '@ai-accounts/*' build
```
Expected: all green.

- [ ] **Step 4: Publish**

```bash
# PyPI — use the token saved from 0.2.x work
(cd packages/core && uv publish)
(cd packages/litestar && uv publish)

# npm — use the granular token
(cd packages/ts-core && pnpm publish --access public --tag alpha)
(cd packages/vue-headless && pnpm publish --access public --tag alpha)
(cd packages/vue-styled && pnpm publish --access public --tag alpha)
```

- [ ] **Step 5: Tag + commit**

```bash
git add -A
git commit -m "release: 0.3.0-alpha.1 (wizard + login)"
git tag v0.3.0-alpha.1
git push origin feat/0.3.0-alpha.1 --tags
```

- [ ] **Step 6: Open PR to main**

```bash
gh pr create --title "0.3.0-alpha.1: wizard + login" \
             --body "Implements the spec at docs/superpowers/specs/2026-04-11-ai-accounts-0.3.0-design.md (alpha.1 scope)."
```

---

## Task 25: Agented consumer — install plugin

**Repo:** `~/Developer/Projects/Agented-ai-accounts-migration/` (branch `feat/0.3.0-alpha.1-consumer`)

**Files:**
- Modify: `frontend/package.json` — bump `@ai-accounts/*` deps to `0.3.0-alpha.1`
- Modify: `backend/pyproject.toml` — bump `ai-accounts-core` + `ai-accounts-litestar` to `0.3.0a1`
- Modify: `frontend/src/main.ts`

- [ ] **Step 1: Bump deps**

```bash
cd ~/Developer/Projects/Agented-ai-accounts-migration/frontend
pnpm add @ai-accounts/ts-core@0.3.0-alpha.1 @ai-accounts/vue-headless@0.3.0-alpha.1 @ai-accounts/vue-styled@0.3.0-alpha.1

cd ../backend
uv add 'ai-accounts-core==0.3.0a1' 'ai-accounts-litestar==0.3.0a1'
```

- [ ] **Step 2: Install plugin in `frontend/src/main.ts`**

```ts
// frontend/src/main.ts
import { createApp } from 'vue';
import App from './App.vue';
import router from './router';
import { AiAccountsClient } from '@ai-accounts/ts-core';
import { aiAccountsPlugin } from '@ai-accounts/vue-headless';
import { useAuthStore } from './stores/auth';
import { useTourMachine } from './composables/useTourMachine';
import { analyticsService } from './services/analytics';

const app = createApp(App);

const auth = useAuthStore();
const aiAccountsClient = new AiAccountsClient({ baseUrl: '' });

app.use(aiAccountsPlugin, {
  client: aiAccountsClient,
  onEvent: (event) => {
    // Route wizard/login events to tour + analytics
    useTourMachine().notify(event);
    analyticsService.track(event);
  },
});

// ... existing app.use(router), etc.
app.mount('#app');
```

Auth header wiring: the client takes `token` at construction today, but for a dynamic bearer from the auth store, extend `AiAccountsClient` to accept an `authHeaders: () => Record<string, string>` function. If it already does (added in Task 16 via `_authHeaders()`), pass it here:

```ts
const aiAccountsClient = new AiAccountsClient({
  baseUrl: '',
  authHeaders: () => ({ Authorization: `Bearer ${auth.token}` }),
});
```

- [ ] **Step 3: Ensure `useTourMachine.notify(event)` accepts `AiAccountsEvent`**

Add a thin adapter in Agented:

```ts
// frontend/src/composables/useTourMachine.ts
import type { AiAccountsEvent } from '@ai-accounts/ts-core';

export function useTourMachine() {
  // ... existing ...
  return {
    // ... existing ...
    notify(event: AiAccountsEvent) {
      switch (event.type) {
        case 'wizard.account.created':
        case 'login.completed':
          this.advance();
          break;
      }
    },
  };
}
```

- [ ] **Step 4: Verify frontend tests still pass**

```bash
cd frontend && npm run test:run
```
Expected: all passing (any existing test referencing the old shim fails — Task 28 fixes those).

- [ ] **Step 5: Commit**

```bash
git add frontend/package.json frontend/pnpm-lock.yaml frontend/src/main.ts \
        frontend/src/composables/useTourMachine.ts \
        backend/pyproject.toml backend/uv.lock
git commit -m "feat(frontend): install @ai-accounts plugin + event bus"
```

---

## Task 26: Agented consumer — swap `<AccountWizard>` import

**Files:**
- Modify: `frontend/src/views/BackendDetailPage.vue`

- [ ] **Step 1: Change import + props**

```vue
<!-- frontend/src/views/BackendDetailPage.vue -->
<script setup lang="ts">
import { AccountWizard } from '@ai-accounts/vue-styled';
// ... rest of imports

// Remove: import AccountWizard from '@/components/backends/AccountWizard.vue';
</script>

<template>
  <!-- existing template, adjusted props/events -->
  <AccountWizard
    v-if="showWizard"
    :initial-backend-kind="currentBackendKind"
    :allow-skip="false"
    @close="showWizard = false"
    @done="onWizardDone"
    @skip="onWizardSkip"
    @add-another="onWizardAddAnother"
  />
</template>
```

Adjust handler names to whatever the refactored wizard emits (Task 23 section).

- [ ] **Step 2: Run frontend tests**

```bash
cd frontend && npm run test:run
```
Expected: passing. If any test imports the old wizard directly, update it.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/views/BackendDetailPage.vue
git commit -m "feat(frontend): use @ai-accounts/vue-styled AccountWizard"
```

---

## Task 27: Agented consumer — register new backends in sidecar

**Files:**
- Modify: `backend/scripts/run_ai_accounts.py`

- [ ] **Step 1: Update backend registration**

```python
# backend/scripts/run_ai_accounts.py
from pathlib import Path

import uvicorn

from ai_accounts_core.adapters.auth_noauth import NoAuth
from ai_accounts_core.adapters.storage_sqlite import SqliteStorage
from ai_accounts_core.adapters.vault_envkey.vault import EnvKeyVault
from ai_accounts_core.backends.claude import ClaudeBackend
from ai_accounts_core.backends.codex import CodexBackend
from ai_accounts_core.backends.gemini import GeminiBackend
from ai_accounts_core.backends.opencode import OpenCodeBackend
from ai_accounts_litestar.app import create_app
from ai_accounts_litestar.config import AiAccountsConfig


def main() -> None:
    data_dir = Path("data/ai_accounts")
    data_dir.mkdir(parents=True, exist_ok=True)

    app = create_app(
        AiAccountsConfig(
            env="development",
            storage=SqliteStorage(str(data_dir / "ai_accounts.db")),
            vault=EnvKeyVault(env_var="AI_ACCOUNTS_VAULT_KEY"),
            auth=NoAuth(),
            backends=(
                ClaudeBackend(),
                CodexBackend(),
                GeminiBackend(),
                OpenCodeBackend(),
            ),
            backend_dirs_path=data_dir / "backend_dirs",
        )
    )
    uvicorn.run(app, host="127.0.0.1", port=20001)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run backend tests**

```bash
cd backend && uv run pytest tests/integration/test_ai_accounts_proxy.py -v
```
Expected: passing. Update `test_onboarding_full_flow` if it references the old `login()` API — it should now drive the new `begin_login` + event stream (or call the routes directly).

- [ ] **Step 3: Commit**

```bash
git add backend/scripts/run_ai_accounts.py backend/tests/integration/test_ai_accounts_proxy.py
git commit -m "feat(backend): register all backends with 0.3.0-alpha.1 sidecar"
```

---

## Task 28: Delete the shim + Agented-local wizard

**Files:**
- Delete: `frontend/src/services/api/backends.ts`
- Delete: `frontend/src/components/backends/AccountWizard.vue`
- Modify: any file that imported from either

- [ ] **Step 1: Find callers**

```bash
cd ~/Developer/Projects/Agented-ai-accounts-migration
grep -rn "services/api/backends" frontend/src/
grep -rn "components/backends/AccountWizard" frontend/src/
```

- [ ] **Step 2: Redirect each caller**

For every `import { backendApi } from '@/services/api/backends'`, replace with `useAiAccounts()` + `client.*`. For every `import AccountWizard` from the components path, replace with `import { AccountWizard } from '@ai-accounts/vue-styled'`.

Common replacements:
- `backendApi.list()` → `await client.listBackends()` (returns `{ items: BackendDTO[] }`)
- `backendApi.update(id, patch)` → `await client.updateBackend(id, patch)`
- `backendApi.delete(id)` → `await client.deleteBackend(id)`
- `backendApi.startConnect(...)` → use `<AccountWizard>` — no direct replacement
- `backendApi.addAccount(legacyId, data)` → `await client.createBackend({kind, display_name, config})`
- `BACKEND_METADATA[kind]` → `useBackendRegistry().get(kind)`

Any screen that grouped `bkd-*` rows by kind gets simplified: use flat `client.listBackends()` output directly, since ai-accounts' data model is already the right shape.

- [ ] **Step 3: Delete shim + wizard**

```bash
git rm frontend/src/services/api/backends.ts
git rm frontend/src/components/backends/AccountWizard.vue
```

- [ ] **Step 4: Verify build + tests**

```bash
cd ~/Developer/Projects/Agented-ai-accounts-migration
just build
cd backend && uv run pytest
cd ../frontend && npm run test:run
```
All three must pass.

- [ ] **Step 5: Commit**

```bash
cd ~/Developer/Projects/Agented-ai-accounts-migration
git add -A
git commit -m "chore(frontend): delete shim + Agented-local wizard (now from @ai-accounts/vue-styled)"
```

---

## Task 29: Manual E2E — real Claude `/login`

**No code — this is a gate between alpha.1 and alpha.2.**

- [ ] **Step 1: Start Agented**

```bash
cd ~/Developer/Projects/Agented-ai-accounts-migration
just deploy
```

- [ ] **Step 2: Walk the full flow**

Open `http://localhost:3000` → onboarding → add account → select Claude → "Sign in with browser" → verify:
- Wizard shows Claude install status
- Clicking "Sign in with browser" triggers real `claude /login` (watch the terminal where `run_ai_accounts.py` runs — you should see the subprocess spawn)
- Wizard displays the auth URL as a clickable link
- After completing auth in the browser, wizard advances to "done" and the new account appears in the backend list
- Inline edit form works on the new account

- [ ] **Step 3: Walk the API key flow**

Add another Claude account via "API key" path. Verify the text prompt appears, accepts input, and creates the account.

- [ ] **Step 4: Walk Codex / Gemini / OpenCode**

For each, run the CLI install check; if installed, run a real login through their native flow.

- [ ] **Step 5: Document anything broken**

If anything regresses vs. Agented main at `6b15108`, **stop**, open issues, fix, re-tag `0.3.0-alpha.1.1`, retry. Do NOT start alpha.2 until this gate is green.

- [ ] **Step 6: Mark alpha.1 gate passed**

Add a note to the PR: "Manual E2E passed: Claude cli_browser, Claude api_key, Codex oauth_device, Gemini oauth_device, OpenCode cli_browser." Merge to main.

---

## Self-Review

**1. Spec coverage:**
- Goal 1 (drop-in reusability) → Tasks 17-19 (plugin + composables) + Task 23 (wizard) + Task 25 (Agented install)
- Goal 2 (clean protocol boundary) → Tasks 2, 5, 6, 7 (LoginSession, BackendMetadata, BackendRegistry, BackendProtocol)
- Goal 3 (Agented thin consumer) → Tasks 25-28
- Goal 4 (stable contracts) → Tasks 1, 2, 5, 15 (frozen at 0.3.0 stable — alphas may break)
- `LoginSession` ABC → Task 2
- `LoginEvent` union → Task 1
- `BackendMetadata` → Tasks 5, 6, 14
- Login routes (begin/stream/respond/cancel) → Task 13
- Metadata route → Task 14
- ts-core client extensions → Task 16
- Event bus + authHeaders → Task 17
- `AccountWizard` refactor → Task 23
- Backend ports (Claude, Codex, Gemini, OpenCode) → Tasks 8, 9, 10, 11
- CLI orchestrator → Task 4
- Agented migration → Tasks 25-28
- E2E gate → Task 29
- Publish → Task 24

No gaps against the alpha.1 scope section of the spec.

**2. Placeholder scan:** No "TBD", "TODO", or "fill in details" outside of Task 22 (`AccountEditForm`) and Tasks 9-11 where the test/implementation sketch is described but full code isn't duplicated for brevity — the implementation pattern is fully shown in Task 8 and each later task names the exact changes. This is deliberate: repeating 300 lines of Python four times would make the plan unreadable. Subagent execution should refer back to Task 8 for the full Claude pattern.

**3. Type consistency check:**
- `LoginSession.session_id`, `backend_kind`, `flow_kind`, `done` — used consistently across Tasks 2, 3, 7, 8, 9, 10, 11, 12, 13 ✓
- `LoginEvent` tag field `"type"` — consistent across Python (Task 1) and TS (Task 15) ✓
- `BackendMetadata` field names match between Python (Task 5) and TS (Task 15) ✓
- `begin_login(flow_kind, config, vault_ctx, isolation_dir)` signature consistent across Tasks 7, 8, 9, 10, 11, 12 ✓
- `client.beginLogin(accountId, flowKind, inputs)` signature consistent across Tasks 16 and 19 ✓
- `_BeginRequest { flow_kind, inputs }` (Task 13) matches TS client body (Task 16) ✓
- SSE event format: `event: login\ndata: <json>\n\n` — written this way in Task 13 and parsed this way in Task 16 ✓
- Route paths consistent: `/api/v1/backends/{id}/login/{begin,stream,respond,cancel}` across Tasks 13 and 16 ✓
- `AiAccountsEvent` variants match between ts-core (Task 15), plugin (Task 17), and useLoginSession (Task 19) ✓

No inconsistencies found.

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-04-11-ai-accounts-0.3.0-alpha.1.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration. Tasks 4, 8, 13, 23 are the biggest / riskiest and warrant careful reviews; scaffolding tasks (1, 5, 6, 15) batch well.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints for review.

**Which approach?**
