import asyncio
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from ai_accounts_core.backends.gemini import GeminiBackend
from ai_accounts_core.login.events import (
    LoginComplete,
    LoginEvent,
    LoginFailed,
    PromptAnswer,
    TextPrompt,
    UrlPrompt,
)


async def _drain(session) -> list[LoginEvent]:
    events: list[LoginEvent] = []
    async for ev in session.events():
        events.append(ev)
    return events


@pytest.mark.asyncio
async def test_direct_oauth_emits_url_prompt_with_pkce(tmp_path: Path):
    backend = GeminiBackend()
    session = backend.begin_login(
        flow_kind="direct_oauth",
        config={},
        vault_ctx={},
        isolation_dir=tmp_path,
    )

    events: list[LoginEvent] = []
    async for ev in session.events():
        events.append(ev)
        if isinstance(ev, TextPrompt):
            break

    url_prompts = [e for e in events if isinstance(e, UrlPrompt)]
    assert len(url_prompts) == 1
    assert "accounts.google.com/o/oauth2/v2/auth" in url_prompts[0].url
    assert "code_challenge=" in url_prompts[0].url
    assert "code_challenge_method=S256" in url_prompts[0].url
    assert "state=" in url_prompts[0].url

    await session.cancel()


@pytest.mark.asyncio
async def test_direct_oauth_happy_path(tmp_path: Path):
    backend = GeminiBackend()
    config_dir = tmp_path / "gemini_config"
    session = backend.begin_login(
        flow_kind="direct_oauth",
        config={"email": "user@example.test", "config_path": str(config_dir)},
        vault_ctx={},
        isolation_dir=tmp_path,
    )

    fake_tokens = {
        "access_token": "ya29.fake",
        "refresh_token": "1//fake_refresh",
        "token_type": "Bearer",
        "id_token": "id-token-fake",
        "expires_in": 3600,
    }

    class _FakeResponse:
        status_code = 200
        headers = {"content-type": "application/json"}

        def json(self) -> dict:
            return fake_tokens

    class _FakeAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args) -> None:
            pass

        async def post(self, *args, **kwargs):
            return _FakeResponse()

    with patch("httpx.AsyncClient", _FakeAsyncClient):
        events_task = asyncio.create_task(_drain(session))
        await asyncio.sleep(0)
        await session.respond(PromptAnswer(prompt_id="auth_code", answer="abcd1234"))
        events = await events_task

    completes = [e for e in events if isinstance(e, LoginComplete)]
    assert len(completes) == 1

    creds_file = config_dir / ".gemini" / "oauth_creds.json"
    assert creds_file.exists()
    creds = json.loads(creds_file.read_text())
    assert creds["access_token"] == "ya29.fake"
    assert creds["refresh_token"] == "1//fake_refresh"


@pytest.mark.asyncio
async def test_direct_oauth_rejects_empty_code(tmp_path: Path):
    backend = GeminiBackend()
    session = backend.begin_login(
        flow_kind="direct_oauth",
        config={},
        vault_ctx={},
        isolation_dir=tmp_path,
    )

    events_task = asyncio.create_task(_drain(session))
    await asyncio.sleep(0)
    await session.respond(PromptAnswer(prompt_id="auth_code", answer="  "))
    events = await events_task

    failures = [e for e in events if isinstance(e, LoginFailed)]
    assert len(failures) == 1
    assert failures[0].code == "empty_code"


@pytest.mark.asyncio
async def test_direct_oauth_reports_token_exchange_failure(tmp_path: Path):
    backend = GeminiBackend()
    session = backend.begin_login(
        flow_kind="direct_oauth",
        config={},
        vault_ctx={},
        isolation_dir=tmp_path,
    )

    class _FailResponse:
        status_code = 400
        headers = {"content-type": "application/json"}

        def json(self) -> dict:
            return {"error_description": "invalid_grant"}

        @property
        def text(self) -> str:
            return '{"error_description": "invalid_grant"}'

    class _FakeAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args) -> None:
            pass

        async def post(self, *args, **kwargs):
            return _FailResponse()

    # Session now retries up to 3 times on token-exchange failure
    # (peek-don't-pop PKCE state). Submit 3 bad codes to exhaust retries.
    async def _drain_with_retries(session, bad_codes: list[str]) -> list[LoginEvent]:
        events: list[LoginEvent] = []
        agen = session.events()
        attempts = 0
        async for ev in agen:
            events.append(ev)
            if isinstance(ev, TextPrompt) and attempts < len(bad_codes):
                await session.respond(
                    PromptAnswer(prompt_id="auth_code", answer=bad_codes[attempts])
                )
                attempts += 1
        return events

    with patch("httpx.AsyncClient", _FakeAsyncClient):
        events = await _drain_with_retries(session, ["bad1", "bad2", "bad3"])

    failures = [e for e in events if isinstance(e, LoginFailed)]
    assert len(failures) == 1
    assert failures[0].code == "token_exchange_failed"
    assert "invalid_grant" in failures[0].message


@pytest.mark.asyncio
async def test_token_exchange_posts_client_secret(tmp_path: Path):
    """Google requires client_secret for web-client credentials even with PKCE."""
    backend = GeminiBackend()
    session = backend.begin_login(
        flow_kind="direct_oauth",
        config={"email": "user@example.test", "config_path": str(tmp_path / "cfg")},
        vault_ctx={},
        isolation_dir=tmp_path,
    )

    captured: dict = {}

    class _FakeResponse:
        status_code = 200
        headers = {"content-type": "application/json"}

        def json(self) -> dict:
            return {
                "access_token": "ya29.fake",
                "refresh_token": "1//fake",
                "token_type": "Bearer",
                "id_token": "id",
                "expires_in": 3600,
            }

    class _FakeAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args) -> None:
            pass

        async def post(self, url, data=None, **kwargs):
            captured["url"] = url
            captured["data"] = data
            return _FakeResponse()

    with patch("httpx.AsyncClient", _FakeAsyncClient):
        events_task = asyncio.create_task(_drain(session))
        await asyncio.sleep(0)
        await session.respond(PromptAnswer(prompt_id="auth_code", answer="good"))
        await events_task

    assert captured["url"] == "https://oauth2.googleapis.com/token"
    assert "client_secret" in captured["data"]
    assert captured["data"]["client_secret"].startswith("GOCSPX-")
    assert captured["data"]["client_id"].endswith(".apps.googleusercontent.com")


@pytest.mark.asyncio
async def test_pkce_state_survives_transient_failure(tmp_path: Path):
    """Peek-don't-pop: a failed token exchange must not wipe PKCE state —
    the next paste attempt must reuse the same code_verifier."""
    backend = GeminiBackend()
    session = backend.begin_login(
        flow_kind="direct_oauth",
        config={"email": "user@example.test", "config_path": str(tmp_path / "cfg")},
        vault_ctx={},
        isolation_dir=tmp_path,
    )

    verifiers_seen: list[str] = []
    call_count = {"n": 0}

    class _Resp:
        def __init__(self, status: int, body: dict) -> None:
            self.status_code = status
            self.headers = {"content-type": "application/json"}
            self._body = body

        def json(self) -> dict:
            return self._body

        @property
        def text(self) -> str:
            return json.dumps(self._body)

    class _FakeAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args) -> None:
            pass

        async def post(self, url, data=None, **kwargs):
            verifiers_seen.append(data["code_verifier"])
            call_count["n"] += 1
            if call_count["n"] == 1:
                return _Resp(400, {"error_description": "invalid_grant"})
            return _Resp(
                200,
                {
                    "access_token": "ya29.ok",
                    "refresh_token": "1//ok",
                    "token_type": "Bearer",
                    "id_token": "id",
                    "expires_in": 3600,
                },
            )

    async def _drive() -> list[LoginEvent]:
        events: list[LoginEvent] = []
        codes = iter(["first_bad", "second_good"])
        async for ev in session.events():
            events.append(ev)
            if isinstance(ev, TextPrompt):
                nxt = next(codes, None)
                if nxt is not None:
                    await session.respond(
                        PromptAnswer(prompt_id="auth_code", answer=nxt)
                    )
        return events

    with patch("httpx.AsyncClient", _FakeAsyncClient):
        events = await _drive()

    # Both exchange calls must reuse the same PKCE verifier
    assert len(verifiers_seen) == 2
    assert verifiers_seen[0] == verifiers_seen[1]
    completes = [e for e in events if isinstance(e, LoginComplete)]
    assert len(completes) == 1


@pytest.mark.asyncio
async def test_post_success_state_not_retrievable(tmp_path: Path):
    """After successful exchange, session is done and cannot be re-driven."""
    backend = GeminiBackend()
    session = backend.begin_login(
        flow_kind="direct_oauth",
        config={"email": "u@example.test", "config_path": str(tmp_path / "cfg")},
        vault_ctx={},
        isolation_dir=tmp_path,
    )

    class _FakeResponse:
        status_code = 200
        headers = {"content-type": "application/json"}

        def json(self) -> dict:
            return {
                "access_token": "ya29.ok",
                "refresh_token": "1//ok",
                "token_type": "Bearer",
                "id_token": "id",
                "expires_in": 3600,
            }

    class _FakeAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args) -> None:
            pass

        async def post(self, *args, **kwargs):
            return _FakeResponse()

    with patch("httpx.AsyncClient", _FakeAsyncClient):
        events_task = asyncio.create_task(_drain(session))
        await asyncio.sleep(0)
        await session.respond(PromptAnswer(prompt_id="auth_code", answer="good"))
        await events_task

    assert session.done is True
    # Further respond() calls are silently ignored post-completion
    await session.respond(PromptAnswer(prompt_id="auth_code", answer="again"))
    assert session.done is True


def test_validate_config_path_rejects_traversal(tmp_path: Path):
    from ai_accounts_core.backends.gemini import _validate_config_path

    with pytest.raises(ValueError, match="outside allowed"):
        _validate_config_path("/etc/passwd", tmp_path)


def test_validate_config_path_accepts_home_relative(tmp_path: Path):
    from ai_accounts_core.backends.gemini import _validate_config_path

    result = _validate_config_path("~/.my-gemini", tmp_path)
    assert ".gemini" in str(result)


def test_validate_config_path_accepts_isolation_subdir(tmp_path: Path):
    from ai_accounts_core.backends.gemini import _validate_config_path

    sub = tmp_path / "myconf"
    sub.mkdir()
    result = _validate_config_path(str(sub), tmp_path)
    assert str(result).startswith(str(tmp_path))


def test_validate_config_path_default_returns_home(tmp_path: Path):
    from ai_accounts_core.backends.gemini import _validate_config_path

    result = _validate_config_path(None, tmp_path)
    assert result == Path.home() / ".gemini"


@pytest.mark.asyncio
async def test_credential_file_permissions(tmp_path: Path):
    import stat

    backend = GeminiBackend()
    config_dir = tmp_path / "gemini_config"
    session = backend.begin_login(
        flow_kind="direct_oauth",
        config={"email": "user@example.test", "config_path": str(config_dir)},
        vault_ctx={},
        isolation_dir=tmp_path,
    )

    fake_tokens = {
        "access_token": "ya29.fake",
        "refresh_token": "1//fake_refresh",
        "token_type": "Bearer",
        "id_token": "id-token-fake",
        "expires_in": 3600,
    }

    class _FakeResponse:
        status_code = 200
        headers = {"content-type": "application/json"}

        def json(self) -> dict:
            return fake_tokens

    class _FakeAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args) -> None:
            pass

        async def post(self, *args, **kwargs):
            return _FakeResponse()

    with patch("httpx.AsyncClient", _FakeAsyncClient):
        events_task = asyncio.create_task(_drain(session))
        await asyncio.sleep(0)
        await session.respond(PromptAnswer(prompt_id="auth_code", answer="abcd1234"))
        await events_task

    creds_file = config_dir / ".gemini" / "oauth_creds.json"
    assert creds_file.exists()
    mode = creds_file.stat().st_mode & 0o777
    assert mode == 0o600, f"expected 0600, got {oct(mode)}"


def test_direct_oauth_in_metadata_login_flows():
    meta = GeminiBackend.metadata
    flow_kinds = {f.kind for f in meta.login_flows}
    assert "direct_oauth" in flow_kinds
    assert "oauth_device" in flow_kinds
    assert "api_key" in flow_kinds
