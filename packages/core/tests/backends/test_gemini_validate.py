import pytest

from ai_accounts_core.backends.gemini import GeminiBackend


@pytest.mark.asyncio
async def test_list_models_empty_for_blank_credential(tmp_path):
    backend = GeminiBackend()
    models = await backend.list_models(b"", isolation_dir=tmp_path)
    assert models == []


@pytest.mark.asyncio
async def test_list_models_uses_http_not_cli(tmp_path, monkeypatch):
    """Patch _run to fail loudly — list_models must not invoke any subprocess."""

    backend = GeminiBackend()

    async def explode(spec):
        raise RuntimeError(f"_run should not be called by list_models, got {spec}")

    monkeypatch.setattr(backend, "_run", explode)
    # With blank credential we expect [] without any _run call.
    models = await backend.list_models(b"", isolation_dir=tmp_path)
    assert models == []


@pytest.mark.asyncio
async def test_list_models_parses_google_response(tmp_path, monkeypatch):
    """Mock httpx.AsyncClient.get to return a fake Google models response."""

    import httpx
    from ai_accounts_core.backends import gemini as gemini_mod

    fake_payload = {
        "models": [
            {
                "name": "models/gemini-2.5-pro",
                "displayName": "Gemini 2.5 Pro",
                "inputTokenLimit": 2_000_000,
            },
            {
                "name": "models/gemini-2.5-flash",
                "displayName": "Gemini 2.5 Flash",
                "inputTokenLimit": 1_000_000,
            },
        ]
    }

    class _FakeResp:
        status_code = 200

        def json(self):
            return fake_payload

    class _FakeClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

        async def get(self, *a, **kw):
            return _FakeResp()

    monkeypatch.setattr(gemini_mod.httpx, "AsyncClient", _FakeClient)

    backend = GeminiBackend()
    models = await backend.list_models(b"fake-key", isolation_dir=tmp_path)
    ids = [m.id for m in models]
    assert ids == ["gemini-2.5-pro", "gemini-2.5-flash"]
    assert models[0].context_window == 2_000_000
