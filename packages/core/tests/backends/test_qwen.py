from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from ai_accounts_core.backends.qwen import QwenBackend, _QwenApiKeySession
from ai_accounts_core.login.events import (
    LoginComplete,
    MenuPrompt,
    PromptAnswer,
    TextPrompt,
)

_CN_BASE = "https://dashscope.aliyuncs.com/compatible-mode/v1"
_INTL_BASE = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"


def _credential(base_url: str = _CN_BASE, api_key: str = "sk-qwen-test") -> bytes:
    return json.dumps({"api_key": api_key, "base_url": base_url}).encode()


async def _drain(session) -> list:
    return [evt async for evt in session.events()]


def test_qwen_metadata_and_login_flow():
    backend = QwenBackend()
    assert backend.kind == "qwen"
    assert backend.metadata.kind == "qwen"
    assert backend.supported_login_flows == frozenset({"api_key"})
    session = backend.begin_login("api_key", {}, {}, Path("."))
    assert isinstance(session, _QwenApiKeySession)
    assert session.flow_kind == "api_key"
    assert session.backend_kind == "qwen"


def test_qwen_begin_login_rejects_unknown_flow():
    backend = QwenBackend()
    with pytest.raises(ValueError, match="unsupported"):
        backend.begin_login("cli_browser", {}, {}, Path("."))


@pytest.mark.asyncio
async def test_qwen_login_menu_then_api_key_cn_region(tmp_path: Path):
    """The login session first emits a region MenuPrompt (CN/Intl/Custom),
    then a hidden api_key TextPrompt, and stores JSON {api_key, base_url}."""
    backend = QwenBackend()
    session = backend.begin_login("api_key", {}, {}, tmp_path)

    events_task = asyncio.create_task(_drain(session))
    await asyncio.sleep(0)
    await session.respond(PromptAnswer(prompt_id="region", answer="1"))
    await asyncio.sleep(0)
    await session.respond(PromptAnswer(prompt_id="api_key", answer="sk-qwen-cn"))
    events = await events_task

    # First event is the region menu with three options.
    menus = [e for e in events if isinstance(e, MenuPrompt)]
    assert len(menus) == 1
    assert isinstance(events[0], MenuPrompt)
    assert menus[0].prompt_id == "region"
    assert len(menus[0].options) == 3
    labels = " ".join(o.label for o in menus[0].options)
    assert "China" in labels
    assert "International" in labels
    assert "Custom" in labels

    # Then a hidden api_key prompt.
    text_prompts = [e for e in events if isinstance(e, TextPrompt)]
    assert [p.prompt_id for p in text_prompts] == ["api_key"]
    assert text_prompts[0].hidden is True

    completes = [e for e in events if isinstance(e, LoginComplete)]
    assert len(completes) == 1

    assert session.credential is not None
    decoded = json.loads(session.credential.decode())
    assert decoded == {"api_key": "sk-qwen-cn", "base_url": _CN_BASE}


@pytest.mark.asyncio
async def test_qwen_login_intl_region(tmp_path: Path):
    backend = QwenBackend()
    session = backend.begin_login("api_key", {}, {}, tmp_path)

    events_task = asyncio.create_task(_drain(session))
    await asyncio.sleep(0)
    await session.respond(PromptAnswer(prompt_id="region", answer="2"))
    await asyncio.sleep(0)
    await session.respond(PromptAnswer(prompt_id="api_key", answer="sk-qwen-intl"))
    await events_task

    assert session.credential is not None
    decoded = json.loads(session.credential.decode())
    assert decoded == {"api_key": "sk-qwen-intl", "base_url": _INTL_BASE}


@pytest.mark.asyncio
async def test_qwen_login_custom_region_prompts_base_url(tmp_path: Path):
    """Selecting Custom yields a follow-up base_url TextPrompt."""
    backend = QwenBackend()
    session = backend.begin_login("api_key", {}, {}, tmp_path)
    custom = "https://my.dashscope.example/v1"

    events_task = asyncio.create_task(_drain(session))
    await asyncio.sleep(0)
    await session.respond(PromptAnswer(prompt_id="region", answer="3"))
    await asyncio.sleep(0)
    await session.respond(PromptAnswer(prompt_id="base_url", answer=custom))
    await asyncio.sleep(0)
    await session.respond(PromptAnswer(prompt_id="api_key", answer="sk-qwen-custom"))
    events = await events_task

    text_prompts = [e for e in events if isinstance(e, TextPrompt)]
    assert [p.prompt_id for p in text_prompts] == ["base_url", "api_key"]

    assert session.credential is not None
    decoded = json.loads(session.credential.decode())
    assert decoded == {"api_key": "sk-qwen-custom", "base_url": custom}


@pytest.mark.asyncio
async def test_qwen_login_cancel(tmp_path: Path):
    from ai_accounts_core.login.events import LoginFailed

    backend = QwenBackend()
    session = backend.begin_login("api_key", {}, {}, tmp_path)

    events_task = asyncio.create_task(_drain(session))
    await asyncio.sleep(0)
    await session.cancel()
    events = await events_task

    assert any(isinstance(e, LoginFailed) for e in events)
    assert session.credential is None


@pytest.mark.asyncio
async def test_qwen_validate_true_on_200(tmp_path: Path, httpx_mock):
    httpx_mock.add_response(
        url=f"{_CN_BASE}/models",
        method="GET",
        json={"data": [{"id": "qwen3-coder-plus"}]},
    )
    backend = QwenBackend()
    ok = await backend.validate(_credential(), isolation_dir=tmp_path)
    assert ok is True
    req = httpx_mock.get_requests()[0]
    assert str(req.url) == f"{_CN_BASE}/models"
    assert req.headers["authorization"] == "Bearer sk-qwen-test"


@pytest.mark.asyncio
async def test_qwen_validate_false_on_401(tmp_path: Path, httpx_mock):
    httpx_mock.add_response(url=f"{_CN_BASE}/models", method="GET", status_code=401)
    backend = QwenBackend()
    assert await backend.validate(_credential(), isolation_dir=tmp_path) is False


@pytest.mark.asyncio
async def test_qwen_validate_empty_credential_false(tmp_path: Path):
    backend = QwenBackend()
    assert await backend.validate(b"", isolation_dir=tmp_path) is False


@pytest.mark.asyncio
async def test_qwen_env_sets_dashscope_key(tmp_path: Path):
    backend = QwenBackend()
    env = backend._env(_credential(), tmp_path)
    assert env["DASHSCOPE_API_KEY"] == "sk-qwen-test"


@pytest.mark.asyncio
async def test_qwen_detect_is_keyless():
    result = await QwenBackend().detect()
    assert result.installed is True


@pytest.mark.asyncio
async def test_qwen_get_usage_empty(tmp_path: Path):
    assert await QwenBackend().get_usage(_credential(), isolation_dir=tmp_path) == []
