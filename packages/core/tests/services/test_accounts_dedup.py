from pathlib import Path

import pytest
from ai_accounts_core.services.accounts import AccountService
from ai_accounts_core.testing import FakeBackend, FakeStorage, FakeVault


def _service(tmp_path: Path) -> AccountService:
    return AccountService(
        storage=FakeStorage(),
        vault=FakeVault(),
        backends={"claude": FakeBackend(), "codex": FakeBackend()},
        isolation_base_dir=tmp_path / "iso",
    )


@pytest.mark.asyncio
async def test_create_dedups_by_config_path(tmp_path: Path):
    svc = _service(tmp_path)
    first = await svc.create(
        kind="claude",
        display_name="Personal 1",
        config={"config_path": "~/.claude-personal1", "email": "user@example.com"},
    )
    second = await svc.create(
        kind="claude",
        display_name="Personal 1 (again)",
        config={"config_path": "~/.claude-personal1", "email": "user@example.com"},
    )
    assert first.id == second.id, "same config_path should return the same backend id"
    assert second.display_name == "Personal 1 (again)"
    all_backends = await svc.list()
    assert len([b for b in all_backends if b.kind == "claude"]) == 1


@pytest.mark.asyncio
async def test_create_dedups_by_api_key_env(tmp_path: Path):
    svc = _service(tmp_path)
    first = await svc.create(
        kind="claude",
        display_name="Personal1",
        config={"api_key_env": "ANTHROPIC_API_KEY_PERSONAL1"},
    )
    second = await svc.create(
        kind="claude",
        display_name="Personal1 copy",
        config={"api_key_env": "ANTHROPIC_API_KEY_PERSONAL1"},
    )
    assert first.id == second.id
    all_backends = await svc.list()
    assert len(all_backends) == 1


@pytest.mark.asyncio
async def test_create_does_not_dedup_across_kinds(tmp_path: Path):
    svc = _service(tmp_path)
    a = await svc.create(
        kind="claude",
        display_name="Shared",
        config={"config_path": "~/.shared"},
    )
    b = await svc.create(
        kind="codex",
        display_name="Shared",
        config={"config_path": "~/.shared"},
    )
    assert a.id != b.id


@pytest.mark.asyncio
async def test_create_does_not_dedup_with_empty_config(tmp_path: Path):
    svc = _service(tmp_path)
    first = await svc.create(kind="claude", display_name="A", config={})
    second = await svc.create(kind="claude", display_name="B", config={})
    # Empty config has no dedup key, so both rows should be kept.
    assert first.id != second.id


@pytest.mark.asyncio
async def test_create_dedups_by_email_when_no_path_or_env(tmp_path: Path):
    svc = _service(tmp_path)
    first = await svc.create(
        kind="claude",
        display_name="A",
        config={"email": "user@example.com"},
    )
    second = await svc.create(
        kind="claude",
        display_name="B",
        config={"email": "user@example.com"},
    )
    assert first.id == second.id
