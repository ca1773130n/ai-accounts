# 0.3.0-alpha.4: PTY Session System Implementation Plan

> **STATUS: Implemented (shipped in 0.3.0-alpha.2).** This plan's scope landed in commits `1b0da66`, `820a41f`, `53e54e3`, followed by reliability fixes (`a1d4885`, `12d2ef9`, `7269510`, etc.). Retroactively documented in the 0.3.0-alpha.2 CHANGELOG entry. Tests: `packages/core/tests/pty/`, `packages/core/tests/services/test_pty_service.py`, `packages/litestar/tests/test_pty_routes.py` (7 passing).

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add real-time PTY (pseudo-terminal) sessions to ai-accounts — spawn interactive CLI sessions via backend credentials, stream binary frames over WebSocket, persist frame history for detach/reattach, and provide a Vue xterm.js terminal component.

**Architecture:** PtyService manages session lifecycle via the existing `SessionRepository` (live_sessions table). Each backend implements `pty()` returning a `PtyHandle` that wraps a PTY subprocess. Litestar serves a WebSocket handler at `/ws/pty/{session_id}` that bridges PtyHandle read/write to binary frames. The ts-core `PtySocket` provides reconnect-capable WebSocket client with backpressure. The vue-headless `usePtySession` composable wraps the client. TerminalView.vue integrates xterm.js.

**Tech Stack:** Python (pty module, asyncio, litestar WebSocket), TypeScript (WebSocket, xterm.js), Vue 3

**Reference:** Agented's `pty_service.py`, `LiveExecutionTerminal`

---

## File Map

| Action | Path | Responsibility |
|--------|------|---------------|
| Create | `packages/core/src/ai_accounts_core/services/pty.py` | PtyService — session lifecycle (spawn/attach/kill) |
| Modify | `packages/core/src/ai_accounts_core/backends/claude.py` | Implement `pty()` returning PtyHandle |
| Modify | `packages/core/src/ai_accounts_core/backends/codex.py` | Implement `pty()` |
| Modify | `packages/core/src/ai_accounts_core/backends/gemini.py` | Implement `pty()` |
| Modify | `packages/core/src/ai_accounts_core/backends/opencode.py` | Implement `pty()` |
| Create | `packages/core/src/ai_accounts_core/pty/__init__.py` | PTY handle implementation |
| Create | `packages/core/src/ai_accounts_core/pty/handle.py` | AsyncPtyHandle — PTY subprocess wrapper |
| Modify | `packages/core/src/ai_accounts_core/testing/fakes.py` | FakeBackend.pty() + FakePtyHandle |
| Create | `packages/litestar/src/ai_accounts_litestar/routes/pty_ws.py` | WebSocket handler |
| Modify | `packages/litestar/src/ai_accounts_litestar/app.py` | Register PtyWebSocket + PtyService DI |
| Create | `packages/ts-core/src/client/pty-socket.ts` | PtySocket — reconnect-capable WS client |
| Create | `packages/ts-core/src/types/pty.ts` | PtySession, PtyFrame TS types |
| Modify | `packages/ts-core/src/client/index.ts` | Add PTY client methods |
| Modify | `packages/ts-core/src/index.ts` | Re-export PTY types |
| Create | `packages/vue-headless/src/composables/usePtySession.ts` | Reactive PTY state |
| Modify | `packages/vue-headless/src/index.ts` | Re-export usePtySession |
| Create | `packages/vue-styled/src/components/TerminalView.vue` | xterm.js integration |
| Modify | `packages/vue-styled/src/index.ts` | Re-export TerminalView |
| Modify | `packages/vue-styled/package.json` | Add xterm.js + @xterm/addon-fit deps |

---

## Task 1: AsyncPtyHandle — PTY Subprocess Wrapper

**Files:**
- Create: `packages/core/src/ai_accounts_core/pty/__init__.py`
- Create: `packages/core/src/ai_accounts_core/pty/handle.py`
- Test: `packages/core/tests/pty/test_handle.py`

- [ ] **Step 1: Write failing test for AsyncPtyHandle**

Create `packages/core/tests/pty/__init__.py` (empty) and:

```python
# packages/core/tests/pty/test_handle.py
import asyncio
import pytest

from ai_accounts_core.pty.handle import AsyncPtyHandle


@pytest.mark.asyncio
async def test_echo_command():
    """Spawn 'echo hello' and read the output."""
    handle = await AsyncPtyHandle.spawn(
        command=("/bin/echo", "hello"), cols=80, rows=24,
    )
    chunks: list[bytes] = []
    async for chunk in handle.read():
        chunks.append(chunk)
        if b"hello" in b"".join(chunks):
            break
    output = b"".join(chunks)
    assert b"hello" in output
    await handle.close()


@pytest.mark.asyncio
async def test_write_to_interactive_shell():
    """Spawn sh, write a command, read output."""
    handle = await AsyncPtyHandle.spawn(
        command=("/bin/sh",), cols=80, rows=24,
    )
    await handle.write(b"echo test123\n")
    chunks: list[bytes] = []
    deadline = asyncio.get_event_loop().time() + 3.0
    async for chunk in handle.read():
        chunks.append(chunk)
        if b"test123" in b"".join(chunks):
            break
        if asyncio.get_event_loop().time() > deadline:
            break
    output = b"".join(chunks)
    assert b"test123" in output
    await handle.close()


@pytest.mark.asyncio
async def test_resize():
    """Resize should not raise."""
    handle = await AsyncPtyHandle.spawn(
        command=("/bin/sh",), cols=80, rows=24,
    )
    await handle.resize(120, 40)
    await handle.close()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd packages/core && python -m pytest tests/pty/test_handle.py -v
```

Expected: ImportError — `AsyncPtyHandle` not defined.

- [ ] **Step 3: Implement AsyncPtyHandle**

```python
# packages/core/src/ai_accounts_core/pty/__init__.py
from .handle import AsyncPtyHandle

__all__ = ["AsyncPtyHandle"]
```

```python
# packages/core/src/ai_accounts_core/pty/handle.py
from __future__ import annotations

import asyncio
import fcntl
import os
import pty
import signal
import struct
import termios
from collections.abc import AsyncIterator


class AsyncPtyHandle:
    """Async wrapper around a PTY subprocess.

    Implements the PtyHandle protocol from protocols/backend.py.
    """

    def __init__(self, master_fd: int, pid: int) -> None:
        self._master_fd = master_fd
        self._pid = pid
        self._closed = False

    @classmethod
    async def spawn(
        cls,
        *,
        command: tuple[str, ...],
        cols: int = 80,
        rows: int = 24,
        env: dict[str, str] | None = None,
    ) -> AsyncPtyHandle:
        merged_env = {**os.environ, **(env or {})}
        merged_env["TERM"] = merged_env.get("TERM", "xterm-256color")
        pid, master_fd = pty.openpty()
        # Actually fork
        child_pid = os.fork()
        if child_pid == 0:
            # Child process
            os.close(master_fd)
            os.setsid()
            # Open slave
            slave_fd = os.open(os.ttyname(pid), os.O_RDWR)
            os.close(pid)
            os.dup2(slave_fd, 0)
            os.dup2(slave_fd, 1)
            os.dup2(slave_fd, 2)
            if slave_fd > 2:
                os.close(slave_fd)
            os.execvpe(command[0], list(command), merged_env)
        else:
            os.close(pid)  # close slave in parent
            handle = cls(master_fd, child_pid)
            await handle.resize(cols, rows)
            return handle

    async def write(self, data: bytes) -> None:
        if self._closed:
            raise RuntimeError("handle is closed")
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, os.write, self._master_fd, data)

    async def resize(self, cols: int, rows: int) -> None:
        if self._closed:
            return
        winsize = struct.pack("HHHH", rows, cols, 0, 0)
        fcntl.ioctl(self._master_fd, termios.TIOCSWINSZ, winsize)

    async def read(self) -> AsyncIterator[bytes]:
        loop = asyncio.get_event_loop()
        while not self._closed:
            try:
                data = await loop.run_in_executor(
                    None, self._read_once,
                )
                if not data:
                    break
                yield data
            except OSError:
                break

    def _read_once(self) -> bytes:
        try:
            return os.read(self._master_fd, 4096)
        except OSError:
            return b""

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            os.kill(self._pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            os.close(self._master_fd)
        except OSError:
            pass
        try:
            os.waitpid(self._pid, os.WNOHANG)
        except ChildProcessError:
            pass
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd packages/core && python -m pytest tests/pty/test_handle.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add packages/core/src/ai_accounts_core/pty/ packages/core/tests/pty/
git commit -m "feat(core): AsyncPtyHandle — PTY subprocess wrapper with read/write/resize"
```

---

## Task 2: PtyService — Session Lifecycle

**Files:**
- Create: `packages/core/src/ai_accounts_core/services/pty.py`
- Test: `packages/core/tests/services/test_pty_service.py`

- [ ] **Step 1: Write failing test**

```python
# packages/core/tests/services/test_pty_service.py
import pytest

from ai_accounts_core.services.pty import PtyService
from ai_accounts_core.testing.fakes import FakeStorage, FakeVault, FakeBackend
from ai_accounts_core.services.accounts import AccountService


@pytest.fixture
async def pty_service(tmp_path):
    storage = FakeStorage()
    vault = FakeVault()
    fake = FakeBackend()
    accounts = AccountService(
        storage=storage, vault=vault, backends={"fake": fake},
        isolation_base_dir=tmp_path,
    )
    backend = await accounts.create(kind="fake", display_name="Test")
    await accounts.store_credential(backend.id, b"sk-fake-test")
    await accounts.validate(backend.id)
    return PtyService(account_service=accounts, storage=storage), backend.id


@pytest.mark.asyncio
async def test_spawn_session(pty_service):
    svc, backend_id = await pty_service
    session_id, handle = await svc.spawn(
        backend_id=backend_id,
        command=("/bin/echo", "hi"),
        cols=80, rows=24,
    )
    assert session_id.startswith("pty-")
    assert handle is not None
    await handle.close()


@pytest.mark.asyncio
async def test_attach_and_kill(pty_service):
    svc, backend_id = await pty_service
    session_id, handle = await svc.spawn(
        backend_id=backend_id,
        command=("/bin/sh",),
        cols=80, rows=24,
    )
    # Attach returns the same handle
    attached = svc.attach(session_id)
    assert attached is handle
    # Kill cleans up
    await svc.kill(session_id)
    assert svc.attach(session_id) is None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd packages/core && python -m pytest tests/services/test_pty_service.py -v
```

Expected: ImportError — `PtyService` not defined.

- [ ] **Step 3: Implement PtyService**

```python
# packages/core/src/ai_accounts_core/services/pty.py
from __future__ import annotations

from datetime import UTC, datetime

from ai_accounts_core.domain.session import LiveSession, SessionKind, SessionState
from ai_accounts_core.ids import new_id
from ai_accounts_core.protocols.backend import PtyHandle
from ai_accounts_core.protocols.storage import StorageProtocol
from ai_accounts_core.services.accounts import AccountService


class PtyService:
    def __init__(
        self,
        *,
        account_service: AccountService,
        storage: StorageProtocol,
    ) -> None:
        self._account_service = account_service
        self._storage = storage
        self._handles: dict[str, PtyHandle] = {}

    async def spawn(
        self,
        *,
        backend_id: str,
        command: tuple[str, ...],
        cols: int = 80,
        rows: int = 24,
        env: dict[str, str] | None = None,
    ) -> tuple[str, PtyHandle]:
        from ai_accounts_core.protocols.backend import PtyRequest
        from ai_accounts_core.services.errors import CredentialMissing

        backend = await self._account_service.get(backend_id)
        impl = self._account_service._impl_for(backend.kind)

        # Get credential
        repo = await self._storage.backends()
        stored = await repo.get_credential(backend.id)
        if stored is None:
            raise CredentialMissing(backend.id)
        plaintext = await self._account_service._vault.decrypt(
            stored.ciphertext, context={"backend_id": backend.id}
        )

        request = PtyRequest(command=command, cols=cols, rows=rows, env=env or {})
        isolation_dir = self._account_service._isolation_dir(backend.id)
        handle = await impl.pty(request, plaintext, isolation_dir=isolation_dir)

        session_id = new_id("pty")
        now = datetime.now(UTC)
        live = LiveSession(
            id=session_id,
            kind=SessionKind.PTY,
            backend_id=backend_id,
            state=SessionState.ACTIVE,
            started_at=now,
            last_seen_at=now,
        )
        session_repo = await self._storage.sessions()
        await session_repo.upsert(live)
        self._handles[session_id] = handle
        return session_id, handle

    def attach(self, session_id: str) -> PtyHandle | None:
        return self._handles.get(session_id)

    async def kill(self, session_id: str) -> None:
        handle = self._handles.pop(session_id, None)
        if handle:
            await handle.close()
        session_repo = await self._storage.sessions()
        await session_repo.end(session_id)
```

- [ ] **Step 4: Update FakeBackend.pty()**

In `packages/core/src/ai_accounts_core/testing/fakes.py`, replace the `pty` stub:

```python
    async def pty(  # type: ignore[override]
        self,
        request: Any,
        credential: bytes,
        *,
        isolation_dir: Path,
    ) -> Any:
        from ai_accounts_core.pty.handle import AsyncPtyHandle

        self.calls.append(("pty", request))
        cmd = request.command if hasattr(request, 'command') else ("/bin/sh",)
        cols = request.cols if hasattr(request, 'cols') else 80
        rows = request.rows if hasattr(request, 'rows') else 24
        return await AsyncPtyHandle.spawn(command=cmd, cols=cols, rows=rows)
```

- [ ] **Step 5: Run test to verify it passes**

```bash
cd packages/core && python -m pytest tests/services/test_pty_service.py -v
```

Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add packages/core/src/ai_accounts_core/services/pty.py packages/core/tests/services/test_pty_service.py packages/core/src/ai_accounts_core/testing/fakes.py
git commit -m "feat(core): PtyService — spawn/attach/kill session lifecycle"
```

---

## Task 3: Backend pty() Implementations

**Files:**
- Modify: `packages/core/src/ai_accounts_core/backends/claude.py`
- Modify: `packages/core/src/ai_accounts_core/backends/codex.py`
- Modify: `packages/core/src/ai_accounts_core/backends/gemini.py`
- Modify: `packages/core/src/ai_accounts_core/backends/opencode.py`
- Test: `packages/core/tests/backends/test_pty_spawn.py`

All backends follow the same pattern: spawn their CLI tool via AsyncPtyHandle with the credential injected into the environment.

- [ ] **Step 1: Write failing test**

```python
# packages/core/tests/backends/test_pty_spawn.py
import pytest

from ai_accounts_core.backends.claude import ClaudeBackend
from ai_accounts_core.protocols.backend import PtyRequest


@pytest.mark.asyncio
async def test_claude_pty_spawns(tmp_path):
    """Claude pty() should return a PtyHandle from AsyncPtyHandle.spawn."""
    backend = ClaudeBackend()
    request = PtyRequest(command=("/bin/echo", "pty-test"), cols=80, rows=24)
    handle = await backend.pty(request, b"sk-ant-test", isolation_dir=tmp_path)
    chunks = []
    async for chunk in handle.read():
        chunks.append(chunk)
        if b"pty-test" in b"".join(chunks):
            break
    assert b"pty-test" in b"".join(chunks)
    await handle.close()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd packages/core && python -m pytest tests/backends/test_pty_spawn.py -v
```

Expected: NotImplementedError or AttributeError.

- [ ] **Step 3: Implement pty() for all four backends**

Each backend implements `pty()` by spawning AsyncPtyHandle with the command from PtyRequest and backend-specific env vars:

**Claude** (`backends/claude.py`):
```python
    async def pty(
        self,
        request: PtyRequest,
        credential: bytes,
        *,
        isolation_dir: Path,
    ) -> PtyHandle:
        from ai_accounts_core.pty.handle import AsyncPtyHandle
        env = dict(request.env)
        env["ANTHROPIC_API_KEY"] = credential.decode("utf-8").strip()
        env["CLAUDE_CONFIG_DIR"] = str(isolation_dir)
        return await AsyncPtyHandle.spawn(
            command=request.command, cols=request.cols, rows=request.rows, env=env,
        )
```

**Codex** (`backends/codex.py`):
```python
    async def pty(
        self,
        request: PtyRequest,
        credential: bytes,
        *,
        isolation_dir: Path,
    ) -> PtyHandle:
        from ai_accounts_core.pty.handle import AsyncPtyHandle
        env = dict(request.env)
        env["OPENAI_API_KEY"] = credential.decode("utf-8").strip()
        env["CODEX_HOME"] = str(isolation_dir)
        return await AsyncPtyHandle.spawn(
            command=request.command, cols=request.cols, rows=request.rows, env=env,
        )
```

**Gemini** (`backends/gemini.py`):
```python
    async def pty(
        self,
        request: PtyRequest,
        credential: bytes,
        *,
        isolation_dir: Path,
    ) -> PtyHandle:
        from ai_accounts_core.pty.handle import AsyncPtyHandle
        env = dict(request.env)
        env["GEMINI_API_KEY"] = credential.decode("utf-8").strip()
        return await AsyncPtyHandle.spawn(
            command=request.command, cols=request.cols, rows=request.rows, env=env,
        )
```

**OpenCode** (`backends/opencode.py`):
```python
    async def pty(
        self,
        request: PtyRequest,
        credential: bytes,
        *,
        isolation_dir: Path,
    ) -> PtyHandle:
        from ai_accounts_core.pty.handle import AsyncPtyHandle
        env = dict(request.env)
        env["OPENROUTER_API_KEY"] = credential.decode("utf-8").strip()
        return await AsyncPtyHandle.spawn(
            command=request.command, cols=request.cols, rows=request.rows, env=env,
        )
```

Add import to each file:
```python
from ai_accounts_core.protocols.backend import PtyRequest, PtyHandle
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd packages/core && python -m pytest tests/backends/test_pty_spawn.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/core/src/ai_accounts_core/backends/ packages/core/tests/backends/test_pty_spawn.py
git commit -m "feat(core): pty() implementations for all four backends"
```

---

## Task 4: Litestar WebSocket PTY Handler

**Files:**
- Create: `packages/litestar/src/ai_accounts_litestar/routes/pty_ws.py`
- Modify: `packages/litestar/src/ai_accounts_litestar/app.py`
- Test: `packages/litestar/tests/test_pty_ws.py`

- [ ] **Step 1: Write failing test**

```python
# packages/litestar/tests/test_pty_ws.py
import pytest
from litestar.testing import AsyncTestClient

from ai_accounts_core.testing.fakes import FakeBackend, FakeStorage, FakeVault
from ai_accounts_litestar.app import create_app
from ai_accounts_litestar.config import AiAccountsConfig


@pytest.fixture
async def client(tmp_path):
    config = AiAccountsConfig(
        storage=FakeStorage(),
        vault=FakeVault(),
        backends=(FakeBackend(),),
        backend_dirs_path=tmp_path,
    )
    app = create_app(config)
    async with AsyncTestClient(app) as tc:
        yield tc


@pytest.mark.asyncio
async def test_pty_spawn_via_rest(client):
    """POST /api/v1/pty/spawn creates a PTY session."""
    r = await client.post("/api/v1/backends/", json={
        "kind": "fake", "display_name": "T", "config": {}
    })
    backend_id = r.json()["id"]
    # Store credential + validate
    await client.post(f"/api/v1/backends/{backend_id}/login", json={
        "flow_kind": "api_key", "inputs": {"key": "sk-fake"}
    })
    await client.post(f"/api/v1/backends/{backend_id}/validate")

    r = await client.post("/api/v1/pty/spawn", json={
        "backend_id": backend_id,
        "command": ["/bin/echo", "pty-test"],
        "cols": 80, "rows": 24,
    })
    assert r.status_code == 201
    data = r.json()
    assert "session_id" in data


@pytest.mark.asyncio
async def test_pty_kill(client):
    """POST /api/v1/pty/{id}/kill ends the session."""
    r = await client.post("/api/v1/backends/", json={
        "kind": "fake", "display_name": "T", "config": {}
    })
    backend_id = r.json()["id"]
    await client.post(f"/api/v1/backends/{backend_id}/login", json={
        "flow_kind": "api_key", "inputs": {"key": "sk-fake"}
    })
    await client.post(f"/api/v1/backends/{backend_id}/validate")
    r = await client.post("/api/v1/pty/spawn", json={
        "backend_id": backend_id,
        "command": ["/bin/sh"],
        "cols": 80, "rows": 24,
    })
    session_id = r.json()["session_id"]
    r = await client.post(f"/api/v1/pty/{session_id}/kill")
    assert r.status_code == 200
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd packages/litestar && python -m pytest tests/test_pty_ws.py -v
```

- [ ] **Step 3: Create PTY controller with REST spawn/kill + WebSocket handler**

```python
# packages/litestar/src/ai_accounts_litestar/routes/pty_ws.py
from __future__ import annotations

import asyncio

from litestar import Controller, post, websocket
from litestar.connection import WebSocket

from ai_accounts_core.services.pty import PtyService


class PtyController(Controller):
    path = "/api/v1/pty"

    @post("/spawn", status_code=201)
    async def spawn(self, pty_service: PtyService, data: dict) -> dict:
        session_id, _ = await pty_service.spawn(
            backend_id=data["backend_id"],
            command=tuple(data["command"]),
            cols=data.get("cols", 80),
            rows=data.get("rows", 24),
        )
        return {"session_id": session_id}

    @post("/{session_id:str}/kill")
    async def kill(self, pty_service: PtyService, session_id: str) -> dict:
        await pty_service.kill(session_id)
        return {"status": "killed"}

    @post("/{session_id:str}/resize")
    async def resize(self, pty_service: PtyService, session_id: str, data: dict) -> dict:
        handle = pty_service.attach(session_id)
        if handle is None:
            return {"status": "error", "message": "session not found"}
        await handle.resize(data.get("cols", 80), data.get("rows", 24))
        return {"status": "ok"}


@websocket("/ws/pty/{session_id:str}")
async def pty_websocket(socket: WebSocket, pty_service: PtyService, session_id: str) -> None:
    await socket.accept()
    handle = pty_service.attach(session_id)
    if handle is None:
        await socket.send_data(b"session not found", mode="binary")
        await socket.close()
        return

    async def reader():
        """Read from PTY and send to WebSocket."""
        try:
            async for chunk in handle.read():
                await socket.send_data(chunk, mode="binary")
        except Exception:
            pass

    async def writer():
        """Read from WebSocket and write to PTY."""
        try:
            while True:
                data = await socket.receive_data(mode="binary")
                if isinstance(data, bytes):
                    await handle.write(data)
        except Exception:
            pass

    read_task = asyncio.create_task(reader())
    write_task = asyncio.create_task(writer())
    try:
        await asyncio.gather(read_task, write_task, return_exceptions=True)
    finally:
        read_task.cancel()
        write_task.cancel()
        await socket.close()
```

- [ ] **Step 4: Wire into app.py**

Add imports:
```python
from ai_accounts_core.services.pty import PtyService
from .routes.pty_ws import PtyController, pty_websocket
```

After `chat_service = ...`, add:
```python
    pty_service = PtyService(
        account_service=account_service,
        storage=config.storage,
    )
```

Add provider:
```python
    def _provide_pty_service() -> PtyService:
        return pty_service
```

Add to dependencies:
```python
        "pty_service": Provide(_provide_pty_service, sync_to_thread=False),
```

Add `PtyController` and `pty_websocket` to `route_handlers`.

- [ ] **Step 5: Run test**

```bash
cd packages/litestar && python -m pytest tests/test_pty_ws.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add packages/litestar/src/ai_accounts_litestar/routes/pty_ws.py packages/litestar/src/ai_accounts_litestar/app.py packages/litestar/tests/test_pty_ws.py
git commit -m "feat(litestar): PTY routes — spawn/kill/resize REST + WebSocket handler"
```

---

## Task 5: TypeScript PTY Types and PtySocket Client

**Files:**
- Create: `packages/ts-core/src/types/pty.ts`
- Create: `packages/ts-core/src/client/pty-socket.ts`
- Modify: `packages/ts-core/src/client/index.ts`
- Modify: `packages/ts-core/src/index.ts`
- Test: `packages/ts-core/tests/pty.test.ts`

- [ ] **Step 1: Create PTY types**

```typescript
// packages/ts-core/src/types/pty.ts

export interface PtySessionDTO {
  session_id: string;
}

export interface PtySpawnRequest {
  backend_id: string;
  command: string[];
  cols?: number;
  rows?: number;
}
```

- [ ] **Step 2: Create PtySocket**

```typescript
// packages/ts-core/src/client/pty-socket.ts

export interface PtySocketOptions {
  url: string;
  onData: (data: Uint8Array) => void;
  onClose?: () => void;
  onError?: (error: Event) => void;
  reconnectMs?: number;
}

export class PtySocket {
  private ws: WebSocket | null = null;
  private readonly opts: PtySocketOptions;
  private closed = false;

  constructor(opts: PtySocketOptions) {
    this.opts = opts;
    this.connect();
  }

  private connect() {
    if (this.closed) return;
    this.ws = new WebSocket(this.opts.url);
    this.ws.binaryType = 'arraybuffer';

    this.ws.onmessage = (event) => {
      if (event.data instanceof ArrayBuffer) {
        this.opts.onData(new Uint8Array(event.data));
      }
    };

    this.ws.onclose = () => {
      if (!this.closed && this.opts.reconnectMs) {
        setTimeout(() => this.connect(), this.opts.reconnectMs);
      }
      this.opts.onClose?.();
    };

    this.ws.onerror = (e) => {
      this.opts.onError?.(e);
    };
  }

  send(data: Uint8Array): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(data);
    }
  }

  close(): void {
    this.closed = true;
    this.ws?.close();
    this.ws = null;
  }
}
```

- [ ] **Step 3: Add PTY client methods to AiAccountsClient**

Append to `packages/ts-core/src/client/index.ts`:

```typescript
  // --- PTY Sessions ---

  async spawnPty(input: PtySpawnRequest): Promise<PtySessionDTO> {
    const r = await this._fetch(`${this.baseUrl}/api/v1/pty/spawn`, {
      method: 'POST',
      headers: this.headers(),
      body: JSON.stringify(input),
    });
    if (!r.ok) throw await toError(r);
    return (await r.json()) as PtySessionDTO;
  }

  async killPty(sessionId: string): Promise<void> {
    const r = await this._fetch(
      `${this.baseUrl}/api/v1/pty/${encodeURIComponent(sessionId)}/kill`,
      { method: 'POST', headers: this.headers() },
    );
    if (!r.ok) throw await toError(r);
  }

  async resizePty(sessionId: string, cols: number, rows: number): Promise<void> {
    const r = await this._fetch(
      `${this.baseUrl}/api/v1/pty/${encodeURIComponent(sessionId)}/resize`,
      {
        method: 'POST',
        headers: this.headers(),
        body: JSON.stringify({ cols, rows }),
      },
    );
    if (!r.ok) throw await toError(r);
  }

  ptyWebSocketUrl(sessionId: string): string {
    const wsBase = this.baseUrl.replace(/^http/, 'ws');
    return `${wsBase}/ws/pty/${encodeURIComponent(sessionId)}`;
  }
```

Add imports:
```typescript
import type { PtySessionDTO, PtySpawnRequest } from '../types/pty';
```

- [ ] **Step 4: Update ts-core index.ts exports**

Add to `packages/ts-core/src/index.ts`:
```typescript
export type { PtySessionDTO, PtySpawnRequest } from './types/pty';
export { PtySocket } from './client/pty-socket';
export type { PtySocketOptions } from './client/pty-socket';
```

- [ ] **Step 5: Write test**

```typescript
// packages/ts-core/tests/pty.test.ts
import { describe, it, expect } from 'vitest';
import type { PtySessionDTO, PtySpawnRequest } from '../src/types/pty';

describe('PTY types', () => {
  it('PtySpawnRequest has expected shape', () => {
    const req: PtySpawnRequest = {
      backend_id: 'bkd-1',
      command: ['/bin/sh'],
      cols: 80,
      rows: 24,
    };
    expect(req.command[0]).toBe('/bin/sh');
  });

  it('PtySessionDTO has session_id', () => {
    const dto: PtySessionDTO = { session_id: 'pty-abc' };
    expect(dto.session_id).toBe('pty-abc');
  });
});
```

- [ ] **Step 6: Run tests**

```bash
cd packages/ts-core && pnpm test
```

- [ ] **Step 7: Commit**

```bash
git add packages/ts-core/src/types/pty.ts packages/ts-core/src/client/pty-socket.ts packages/ts-core/src/client/index.ts packages/ts-core/src/index.ts packages/ts-core/tests/pty.test.ts
git commit -m "feat(ts-core): PTY types, PtySocket WebSocket client, and PTY client methods"
```

---

## Task 6: Vue Headless usePtySession Composable

**Files:**
- Create: `packages/vue-headless/src/composables/usePtySession.ts`
- Modify: `packages/vue-headless/src/index.ts`
- Test: `packages/vue-headless/tests/usePtySession.test.ts`

- [ ] **Step 1: Create composable**

```typescript
// packages/vue-headless/src/composables/usePtySession.ts
import { ref, type Ref } from 'vue';
import type { AiAccountsClient } from '@ai-accounts/ts-core';
import { PtySocket } from '@ai-accounts/ts-core';

export interface UsePtySessionReturn {
  sessionId: Ref<string | null>;
  isConnected: Ref<boolean>;
  error: Ref<string | null>;
  spawn: (backendId: string, command: string[], cols?: number, rows?: number) => Promise<void>;
  write: (data: Uint8Array) => void;
  resize: (cols: number, rows: number) => Promise<void>;
  kill: () => Promise<void>;
  onData: (cb: (data: Uint8Array) => void) => void;
}

export function usePtySession(client: AiAccountsClient): UsePtySessionReturn {
  const sessionId = ref<string | null>(null);
  const isConnected = ref(false);
  const error = ref<string | null>(null);
  let socket: PtySocket | null = null;
  let dataCallback: ((data: Uint8Array) => void) | null = null;

  function onData(cb: (data: Uint8Array) => void) {
    dataCallback = cb;
  }

  async function spawn(backendId: string, command: string[], cols = 80, rows = 24) {
    error.value = null;
    const result = await client.spawnPty({
      backend_id: backendId,
      command,
      cols,
      rows,
    });
    sessionId.value = result.session_id;

    const wsUrl = client.ptyWebSocketUrl(result.session_id);
    socket = new PtySocket({
      url: wsUrl,
      onData: (data) => dataCallback?.(data),
      onClose: () => { isConnected.value = false; },
      onError: () => { error.value = 'WebSocket error'; },
      reconnectMs: 3000,
    });
    isConnected.value = true;
  }

  function write(data: Uint8Array) {
    socket?.send(data);
  }

  async function resize(cols: number, rows: number) {
    if (sessionId.value) {
      await client.resizePty(sessionId.value, cols, rows);
    }
  }

  async function kill() {
    if (sessionId.value) {
      await client.killPty(sessionId.value);
    }
    socket?.close();
    socket = null;
    sessionId.value = null;
    isConnected.value = false;
  }

  return { sessionId, isConnected, error, spawn, write, resize, kill, onData };
}
```

- [ ] **Step 2: Update vue-headless exports**

Add to `packages/vue-headless/src/index.ts`:
```typescript
export { usePtySession } from './composables/usePtySession';
export type { UsePtySessionReturn } from './composables/usePtySession';
```

- [ ] **Step 3: Write test**

```typescript
// packages/vue-headless/tests/usePtySession.test.ts
import { describe, it, expect, vi } from 'vitest';
import { usePtySession } from '../src/composables/usePtySession';

function mockClient() {
  return {
    spawnPty: vi.fn().mockResolvedValue({ session_id: 'pty-1' }),
    killPty: vi.fn().mockResolvedValue(undefined),
    resizePty: vi.fn().mockResolvedValue(undefined),
    ptyWebSocketUrl: vi.fn().mockReturnValue('ws://localhost/ws/pty/pty-1'),
  } as any;
}

// Mock WebSocket since it doesn't exist in Node
vi.stubGlobal('WebSocket', class {
  static OPEN = 1;
  binaryType = 'arraybuffer';
  readyState = 1;
  onmessage: any = null;
  onclose: any = null;
  onerror: any = null;
  send = vi.fn();
  close = vi.fn();
});

describe('usePtySession', () => {
  it('spawns a session', async () => {
    const client = mockClient();
    const { spawn, sessionId } = usePtySession(client);
    await spawn('bkd-1', ['/bin/sh']);
    expect(sessionId.value).toBe('pty-1');
    expect(client.spawnPty).toHaveBeenCalledWith({
      backend_id: 'bkd-1', command: ['/bin/sh'], cols: 80, rows: 24,
    });
  });

  it('kills a session', async () => {
    const client = mockClient();
    const { spawn, kill, sessionId } = usePtySession(client);
    await spawn('bkd-1', ['/bin/sh']);
    await kill();
    expect(sessionId.value).toBeNull();
    expect(client.killPty).toHaveBeenCalledWith('pty-1');
  });
});
```

- [ ] **Step 4: Run tests**

```bash
cd packages/vue-headless && pnpm test
```

- [ ] **Step 5: Commit**

```bash
git add packages/vue-headless/src/composables/usePtySession.ts packages/vue-headless/src/index.ts packages/vue-headless/tests/usePtySession.test.ts
git commit -m "feat(vue-headless): usePtySession composable — spawn/write/resize/kill"
```

---

## Task 7: Vue Styled TerminalView Component

**Files:**
- Modify: `packages/vue-styled/package.json` (add xterm.js deps)
- Create: `packages/vue-styled/src/components/TerminalView.vue`
- Modify: `packages/vue-styled/src/index.ts`
- Test: `packages/vue-styled/tests/TerminalView.test.ts`

- [ ] **Step 1: Add xterm.js dependencies**

```bash
cd packages/vue-styled && pnpm add @xterm/xterm @xterm/addon-fit
```

- [ ] **Step 2: Create TerminalView component**

```vue
<!-- packages/vue-styled/src/components/TerminalView.vue -->
<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch } from 'vue';
import { Terminal } from '@xterm/xterm';
import { FitAddon } from '@xterm/addon-fit';

const props = defineProps<{
  onData?: (data: Uint8Array) => void;
  onResize?: (cols: number, rows: number) => void;
  fontSize?: number;
}>();

const containerRef = ref<HTMLElement | null>(null);
let terminal: Terminal | null = null;
let fitAddon: FitAddon | null = null;
let resizeObserver: ResizeObserver | null = null;

function writeData(data: Uint8Array) {
  terminal?.write(data);
}

defineExpose({ writeData });

onMounted(() => {
  if (!containerRef.value) return;
  terminal = new Terminal({
    fontSize: props.fontSize ?? 14,
    fontFamily: 'Menlo, Monaco, "Courier New", monospace',
    theme: {
      background: '#1e1e2e',
      foreground: '#cdd6f4',
      cursor: '#f5e0dc',
    },
    cursorBlink: true,
  });
  fitAddon = new FitAddon();
  terminal.loadAddon(fitAddon);
  terminal.open(containerRef.value);
  fitAddon.fit();

  terminal.onData((data) => {
    const encoded = new TextEncoder().encode(data);
    props.onData?.(encoded);
  });

  terminal.onResize(({ cols, rows }) => {
    props.onResize?.(cols, rows);
  });

  resizeObserver = new ResizeObserver(() => {
    fitAddon?.fit();
  });
  resizeObserver.observe(containerRef.value);
});

onUnmounted(() => {
  resizeObserver?.disconnect();
  terminal?.dispose();
});
</script>

<template>
  <div ref="containerRef" class="aia-terminal-view" />
</template>

<style scoped>
.aia-terminal-view {
  width: 100%;
  height: 100%;
  min-height: 300px;
  background: #1e1e2e;
  border-radius: var(--aia-radius-md, 8px);
  overflow: hidden;
}
</style>

<style>
/* xterm.js base styles — needed globally */
@import '@xterm/xterm/css/xterm.css';
</style>
```

- [ ] **Step 3: Update vue-styled exports**

Add to `packages/vue-styled/src/index.ts`:
```typescript
export { default as TerminalView } from './components/TerminalView.vue';
```

- [ ] **Step 4: Write test**

```typescript
// packages/vue-styled/tests/TerminalView.test.ts
import { describe, it, expect, vi } from 'vitest';
import { mount } from '@vue/test-utils';
import TerminalView from '../src/components/TerminalView.vue';

// Mock xterm.js in test environment
vi.mock('@xterm/xterm', () => ({
  Terminal: class {
    open = vi.fn();
    write = vi.fn();
    onData = vi.fn();
    onResize = vi.fn();
    loadAddon = vi.fn();
    dispose = vi.fn();
  },
}));
vi.mock('@xterm/addon-fit', () => ({
  FitAddon: class {
    fit = vi.fn();
  },
}));

describe('TerminalView', () => {
  it('renders container element', () => {
    const wrapper = mount(TerminalView);
    expect(wrapper.find('.aia-terminal-view').exists()).toBe(true);
  });

  it('exposes writeData method', () => {
    const wrapper = mount(TerminalView);
    expect(typeof wrapper.vm.writeData).toBe('function');
  });
});
```

- [ ] **Step 5: Run tests**

```bash
cd packages/vue-styled && pnpm test
```

- [ ] **Step 6: Commit**

```bash
git add packages/vue-styled/src/components/TerminalView.vue packages/vue-styled/src/index.ts packages/vue-styled/package.json packages/vue-styled/tests/TerminalView.test.ts
git commit -m "feat(vue-styled): TerminalView component with xterm.js integration"
```

---

## Task 8: Version Bump + Release

**Files:**
- Modify: all package manifests (version → 0.3.0a5 / 0.3.0-alpha.5)
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Bump all versions**

Update version strings to alpha.5.

- [ ] **Step 2: Update CHANGELOG.md**

```markdown
## 0.3.0-alpha.5 (PTY) — 2026-04-XX

### Added
- `AsyncPtyHandle` — PTY subprocess wrapper with async read/write/resize
- `PtyService` — session lifecycle management (spawn/attach/kill)
- Backend `pty()` for Claude, Codex, Gemini, OpenCode
- Litestar: `POST /api/v1/pty/spawn`, `/kill`, `/resize` + WebSocket `/ws/pty/{id}`
- `@ai-accounts/ts-core`: `PtySocket` WebSocket client, `spawnPty()`, `killPty()`, `resizePty()`
- `@ai-accounts/vue-headless`: `usePtySession` composable
- `@ai-accounts/vue-styled`: `TerminalView` component with xterm.js
```

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "release: 0.3.0-alpha.5 (PTY sessions)"
```
