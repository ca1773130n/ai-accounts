import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from ai_accounts_core.backends.codex import CodexBackend
from ai_accounts_core.protocols.backend import (
    CredentialLogin,
    LoginError,
    LoginFlow,
    OAuthDeviceLogin,
)


@pytest.mark.asyncio
async def test_detect_finds_cli():
    backend = CodexBackend()
    with patch("shutil.which", return_value="/usr/local/bin/codex"), \
         patch.object(backend, "_run", new=AsyncMock(return_value=(0, b"codex 1.0.0\n", b""))):
        result = await backend.detect()
    assert result.installed is True
    assert "codex" in (result.version or "").lower()


@pytest.mark.asyncio
async def test_detect_missing_cli():
    backend = CodexBackend()
    with patch("shutil.which", return_value=None):
        result = await backend.detect()
    assert result.installed is False


def test_supported_login_flows():
    assert CodexBackend.supported_login_flows == frozenset({"api_key", "oauth_device"})


def test_kind_is_codex():
    assert CodexBackend.kind == "codex"


@pytest.mark.asyncio
async def test_login_api_key_returns_credential_login(tmp_path: Path):
    backend = CodexBackend()
    result = await backend.login(
        LoginFlow(kind="api_key", inputs={"api_key": "sk-test-key"}),
        isolation_dir=tmp_path / "codex",
    )
    assert isinstance(result, CredentialLogin)
    assert result.credential == b"sk-test-key"


@pytest.mark.asyncio
async def test_login_api_key_missing_returns_error(tmp_path: Path):
    backend = CodexBackend()
    result = await backend.login(
        LoginFlow(kind="api_key", inputs={}),
        isolation_dir=tmp_path / "codex",
    )
    assert isinstance(result, LoginError)
    assert result.code == "missing_input"


@pytest.mark.asyncio
async def test_login_unsupported_flow(tmp_path: Path):
    backend = CodexBackend()
    result = await backend.login(
        LoginFlow(kind="cli_login", inputs={}),
        isolation_dir=tmp_path / "codex",
    )
    assert isinstance(result, LoginError)
    assert result.code == "unsupported_flow"


@pytest.mark.asyncio
async def test_login_oauth_no_cli(tmp_path: Path):
    backend = CodexBackend()
    with patch("shutil.which", return_value=None):
        result = await backend.login(
            LoginFlow(kind="oauth_device", inputs={}),
            isolation_dir=tmp_path / "codex",
        )
    assert isinstance(result, LoginError)
    assert result.code == "cli_missing"


@pytest.mark.asyncio
async def test_login_oauth_parses_verification_uri(tmp_path: Path):
    backend = CodexBackend()
    fake_stdout = (
        b"To finish login, visit https://platform.openai.com/device\n"
        b"and enter code ABCD-1234\n"
    )

    class FakeStream:
        def __init__(self, data: bytes) -> None:
            self._data = data
            self._read = False

        async def read(self, n: int = -1) -> bytes:
            if self._read:
                # Simulate the stream blocking indefinitely after the challenge
                await asyncio.Event().wait()
            self._read = True
            return self._data

    class FakeProc:
        returncode = None

        def __init__(self) -> None:
            self.stdout = FakeStream(fake_stdout)
            self.stderr = FakeStream(b"")

        def kill(self) -> None: ...

        async def wait(self) -> int:
            await asyncio.Event().wait()
            return 0

    with patch("shutil.which", return_value="/usr/local/bin/codex"), \
         patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=FakeProc())):
        result = await backend.login(
            LoginFlow(kind="oauth_device", inputs={}),
            isolation_dir=tmp_path / "codex",
        )

    assert isinstance(result, OAuthDeviceLogin)
    assert "openai.com" in result.verification_uri
    assert result.user_code == "ABCD-1234"
    assert result.handle.startswith("oauth-")


@pytest.mark.asyncio
async def test_login_oauth_parse_failure(tmp_path: Path):
    backend = CodexBackend()

    class FakeStream:
        async def read(self, n: int = -1) -> bytes:
            return b"some output without the expected pattern"

    class FakeProc:
        returncode = None
        def __init__(self) -> None:
            self.stdout = FakeStream()
            self.stderr = FakeStream()
        def kill(self) -> None: ...
        async def wait(self) -> int: return 0

    with patch("shutil.which", return_value="/usr/local/bin/codex"), \
         patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=FakeProc())):
        result = await backend.login(
            LoginFlow(kind="oauth_device", inputs={}),
            isolation_dir=tmp_path / "codex",
        )
    assert isinstance(result, LoginError)
    assert result.code == "parse_failed"


@pytest.mark.asyncio
async def test_poll_login_unknown_handle(tmp_path: Path):
    backend = CodexBackend()
    result = await backend.poll_login("nope", isolation_dir=tmp_path / "codex")
    assert isinstance(result, LoginError)
    assert result.code == "unknown_handle"


@pytest.mark.asyncio
async def test_poll_login_returns_pending_when_running(tmp_path: Path):
    backend = CodexBackend()

    class RunningProc:
        returncode = None

    handle = "test-handle"
    backend._oauth_procs[handle] = RunningProc()  # type: ignore[assignment]
    backend._oauth_challenges[handle] = {
        "verification_uri": "https://platform.openai.com/device",
        "user_code": "ABCD-1234",
    }

    result = await backend.poll_login(handle, isolation_dir=tmp_path / "codex")
    assert isinstance(result, OAuthDeviceLogin)
    assert result.handle == handle
    assert result.user_code == "ABCD-1234"


@pytest.mark.asyncio
async def test_poll_login_returns_complete_on_success(tmp_path: Path):
    backend = CodexBackend()

    class FinishedProc:
        returncode = 0

        async def wait(self) -> int:
            return 0

    handle = "test-handle"
    backend._oauth_procs[handle] = FinishedProc()  # type: ignore[assignment]
    backend._oauth_challenges[handle] = {
        "verification_uri": "https://platform.openai.com/device",
        "user_code": "ABCD-1234",
    }

    result = await backend.poll_login(handle, isolation_dir=tmp_path / "codex")
    assert isinstance(result, CredentialLogin)
    assert result.credential == b""
    # After success, handle should be cleaned up
    assert handle not in backend._oauth_procs


@pytest.mark.asyncio
async def test_poll_login_returns_error_on_subprocess_failure(tmp_path: Path):
    backend = CodexBackend()

    class FailedStderr:
        async def read(self, n: int = -1) -> bytes:
            return b"device code expired"

    class FailedProc:
        returncode = 1
        def __init__(self) -> None:
            self.stderr = FailedStderr()

    handle = "test-handle"
    backend._oauth_procs[handle] = FailedProc()  # type: ignore[assignment]
    backend._oauth_challenges[handle] = {"verification_uri": "x", "user_code": "y"}

    result = await backend.poll_login(handle, isolation_dir=tmp_path / "codex")
    assert isinstance(result, LoginError)
    assert result.code == "auth_failed"
    assert "expired" in result.message.lower()


@pytest.mark.asyncio
async def test_validate_with_api_key_sets_env(tmp_path: Path):
    backend = CodexBackend()
    isolation_dir = tmp_path / "codex"
    with patch("shutil.which", return_value="/usr/local/bin/codex"), \
         patch.object(backend, "_run", new=AsyncMock(return_value=(0, b"ok", b""))) as mock_run:
        result = await backend.validate(b"sk-test-key", isolation_dir=isolation_dir)
    assert result is True
    spec = mock_run.await_args.args[0]
    assert spec["env"]["OPENAI_API_KEY"] == "sk-test-key"
    assert spec["env"]["CODEX_HOME"] == str(isolation_dir)


@pytest.mark.asyncio
async def test_validate_with_empty_credential_omits_api_key_env(tmp_path: Path):
    backend = CodexBackend()
    isolation_dir = tmp_path / "codex"
    with patch("shutil.which", return_value="/usr/local/bin/codex"), \
         patch.object(backend, "_run", new=AsyncMock(return_value=(0, b"ok", b""))) as mock_run:
        result = await backend.validate(b"", isolation_dir=isolation_dir)
    assert result is True
    spec = mock_run.await_args.args[0]
    assert "OPENAI_API_KEY" not in spec["env"]
    assert spec["env"]["CODEX_HOME"] == str(isolation_dir)


@pytest.mark.asyncio
async def test_list_models_parses_json(tmp_path: Path):
    import json as _json
    backend = CodexBackend()
    payload = _json.dumps([
        {"id": "gpt-4o", "display_name": "GPT-4o", "context_window": 128_000},
    ]).encode()
    with patch("shutil.which", return_value="/usr/local/bin/codex"), \
         patch.object(backend, "_run", new=AsyncMock(return_value=(0, payload, b""))):
        models = await backend.list_models(b"", isolation_dir=tmp_path / "codex")
    assert len(models) == 1
    assert models[0].id == "gpt-4o"
