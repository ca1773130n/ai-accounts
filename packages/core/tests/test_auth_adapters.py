import hmac

import pytest

from ai_accounts_core.adapters.auth_apikey import ApiKeyAuth
from ai_accounts_core.adapters.auth_noauth import NoAuth
from ai_accounts_core.protocols.auth import RequestContext


def _ctx(headers: dict[str, str]) -> RequestContext:
    return RequestContext(method="GET", path="/api/v1/backends", headers=headers)


@pytest.mark.asyncio
async def test_noauth_returns_local_principal():
    principal = await NoAuth().authenticate(_ctx({}))
    assert principal is not None
    assert principal.id == "local"
    assert "*" in principal.scopes


@pytest.mark.asyncio
async def test_apikey_accepts_valid_bearer(monkeypatch):
    monkeypatch.setenv("AI_ACCOUNTS_API_KEY", "secret-token-abc")
    auth = ApiKeyAuth.from_env()
    p = await auth.authenticate(_ctx({"authorization": "Bearer secret-token-abc"}))
    assert p is not None
    assert p.id == "api_key"


@pytest.mark.asyncio
async def test_apikey_rejects_missing_header(monkeypatch):
    monkeypatch.setenv("AI_ACCOUNTS_API_KEY", "secret")
    auth = ApiKeyAuth.from_env()
    assert await auth.authenticate(_ctx({})) is None


@pytest.mark.asyncio
async def test_apikey_rejects_wrong_token(monkeypatch):
    monkeypatch.setenv("AI_ACCOUNTS_API_KEY", "secret")
    auth = ApiKeyAuth.from_env()
    assert await auth.authenticate(_ctx({"authorization": "Bearer wrong"})) is None


@pytest.mark.asyncio
async def test_apikey_rejects_non_bearer_scheme(monkeypatch):
    monkeypatch.setenv("AI_ACCOUNTS_API_KEY", "secret")
    auth = ApiKeyAuth.from_env()
    assert await auth.authenticate(_ctx({"authorization": "Basic secret"})) is None


@pytest.mark.asyncio
async def test_apikey_is_case_insensitive_on_bearer_scheme(monkeypatch):
    monkeypatch.setenv("AI_ACCOUNTS_API_KEY", "secret")
    auth = ApiKeyAuth.from_env()
    assert await auth.authenticate(_ctx({"authorization": "bearer secret"})) is not None
    assert await auth.authenticate(_ctx({"authorization": "BEARER secret"})) is not None


def test_apikey_constant_time_comparison_source():
    """The implementation must use hmac.compare_digest, not ==."""
    import ai_accounts_core.adapters.auth_apikey as mod
    from pathlib import Path
    source = Path(mod.__file__).read_text()
    assert "compare_digest" in source


def test_apikey_from_env_raises_if_not_set(monkeypatch):
    monkeypatch.delenv("AI_ACCOUNTS_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="not set"):
        ApiKeyAuth.from_env()


def test_apikey_constructor_rejects_empty_token():
    with pytest.raises(ValueError, match="non-empty"):
        ApiKeyAuth("")
