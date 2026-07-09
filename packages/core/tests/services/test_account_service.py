from datetime import UTC, datetime
from pathlib import Path

import pytest
from ai_accounts_core.domain.backend import BackendCredential, BackendStatus
from ai_accounts_core.services.accounts import AccountService
from ai_accounts_core.services.errors import (
    BackendKindUnknown,
    BackendNotFound,
    BackendValidationFailed,
    LoginFlowUnsupported,
)
from ai_accounts_core.testing import FakeBackend, FakeStorage, FakeVault


def _make_service(tmp_path: Path):
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


@pytest.mark.asyncio
async def test_create_backend_persists_and_returns(tmp_path):
    service, storage, _, _ = _make_service(tmp_path)
    created = await service.create("fake", display_name="Test")
    assert created.display_name == "Test"
    assert created.status is BackendStatus.UNCONFIGURED
    assert created.kind == "fake"
    assert created.id.startswith("bkd-")

    repo = await storage.backends()
    fetched = await repo.get(created.id)
    assert fetched == created


@pytest.mark.asyncio
async def test_create_backend_unknown_kind_raises(tmp_path):
    service, _, _, _ = _make_service(tmp_path)
    with pytest.raises(BackendKindUnknown):
        await service.create("martian-ai", display_name="x")


@pytest.mark.asyncio
async def test_list_backends_returns_all(tmp_path):
    service, _, _, _ = _make_service(tmp_path)
    a = await service.create("fake", display_name="A")
    b = await service.create("fake", display_name="B")
    listed = await service.list()
    assert {bk.id for bk in listed} == {a.id, b.id}


@pytest.mark.asyncio
async def test_get_backend_missing_raises(tmp_path):
    service, _, _, _ = _make_service(tmp_path)
    with pytest.raises(BackendNotFound):
        await service.get("bkd-nope")


@pytest.mark.asyncio
async def test_delete_backend_removes_credential_too(tmp_path):
    service, storage, _, _ = _make_service(tmp_path)
    created = await service.create("fake", display_name="A")
    await service.store_credential(created.id, b"fake-credential")
    await service.delete(created.id)
    with pytest.raises(BackendNotFound):
        await service.get(created.id)
    repo = await storage.backends()
    assert await repo.get_credential(created.id) is None


@pytest.mark.asyncio
async def test_detect_backend_returns_result(tmp_path):
    service, _, _, _ = _make_service(tmp_path)
    created = await service.create("fake", display_name="A")
    result = await service.detect(created.id)
    assert result.installed is True
    assert result.version == "fake/0.0"


@pytest.mark.asyncio
async def test_store_credential_then_validate_happy_path(tmp_path):
    service, storage, _, _ = _make_service(tmp_path)
    created = await service.create("fake", display_name="A")

    after = await service.store_credential(created.id, b"fake-credential")
    assert after.status is BackendStatus.VALIDATING

    repo = await storage.backends()
    stored_cred = await repo.get_credential(created.id)
    assert stored_cred is not None
    assert stored_cred.ciphertext != b"fake-credential"  # must be encrypted

    validated = await service.validate(created.id)
    assert validated.status is BackendStatus.READY
    assert validated.last_error is None


@pytest.mark.asyncio
async def test_validate_failure_sets_error_status(tmp_path):
    service, storage, vault, _ = _make_service(tmp_path)
    created = await service.create("fake", display_name="A")

    repo = await storage.backends()
    wrong_ct = await vault.encrypt(b"wrong-credential", context={"backend_id": created.id})
    await repo.put_credential(
        BackendCredential(
            id="crd-x",
            backend_id=created.id,
            ciphertext=wrong_ct,
            key_id="fake://v1",
            created_at=datetime.now(UTC),
        )
    )

    with pytest.raises(BackendValidationFailed):
        await service.validate(created.id)
    refetched = await service.get(created.id)
    assert refetched.status is BackendStatus.ERROR


@pytest.mark.asyncio
async def test_create_backend_ensures_isolation_dir(tmp_path):
    service, _, _, _ = _make_service(tmp_path)
    created = await service.create("fake", display_name="Test")
    expected_dir = tmp_path / "backend_dirs" / created.id
    assert expected_dir.exists()


@pytest.mark.asyncio
async def test_delete_backend_removes_isolation_dir(tmp_path):
    service, _, _, _ = _make_service(tmp_path)
    created = await service.create("fake", display_name="Test")
    isolation_dir = tmp_path / "backend_dirs" / created.id
    (isolation_dir / "probe.txt").write_text("hi")
    assert isolation_dir.exists()
    await service.delete(created.id)
    assert not isolation_dir.exists()


@pytest.mark.asyncio
async def test_begin_login_unsupported_flow_raises(tmp_path):
    service, _, _, _ = _make_service(tmp_path)
    created = await service.create("fake", display_name="X")
    with pytest.raises(LoginFlowUnsupported):
        await service.begin_login(created.id, flow_kind="martian_flow", inputs={})


@pytest.mark.asyncio
async def test_update_backend_display_name(tmp_path):
    service, _, _, _ = _make_service(tmp_path)
    created = await service.create("fake", display_name="Work")
    updated = await service.update(created.id, display_name="Personal")
    assert updated.display_name == "Personal"
    assert updated.kind == created.kind
    assert updated.config == created.config

    refetched = await service.get(created.id)
    assert refetched.display_name == "Personal"


@pytest.mark.asyncio
async def test_update_backend_config(tmp_path):
    service, _, _, _ = _make_service(tmp_path)
    created = await service.create("fake", display_name="A", config={"plan": "free"})
    updated = await service.update(created.id, config={"plan": "pro", "email": "x@y.z"})
    assert updated.config == {"plan": "pro", "email": "x@y.z"}
    assert updated.display_name == "A"


@pytest.mark.asyncio
async def test_update_backend_both_fields(tmp_path):
    service, _, _, _ = _make_service(tmp_path)
    created = await service.create("fake", display_name="Old")
    updated = await service.update(
        created.id, display_name="New", config={"email": "new@example.com"}
    )
    assert updated.display_name == "New"
    assert updated.config == {"email": "new@example.com"}


@pytest.mark.asyncio
async def test_update_backend_missing_raises(tmp_path):
    from ai_accounts_core.services.errors import BackendNotFound

    service, _, _, _ = _make_service(tmp_path)
    with pytest.raises(BackendNotFound):
        await service.update("bkd-nope", display_name="x")


@pytest.mark.asyncio
async def test_update_backend_preserves_fields_when_omitted(tmp_path):
    service, _, _, _ = _make_service(tmp_path)
    created = await service.create("fake", display_name="Keep", config={"email": "a@b"})
    updated = await service.update(created.id)
    assert updated.display_name == "Keep"
    assert updated.config == {"email": "a@b"}


# ── discover(): probe timeouts must be inconclusive, not destructive ────


@pytest.mark.asyncio
async def test_discover_timeout_does_not_downgrade_ready_backend(tmp_path, monkeypatch):
    """A probe timeout is no evidence the login is dead. Downgrading
    READY → ERROR on timeout knocked perfectly-valid backends out of
    scheduler.pick() ('No ai-accounts backend available' in HypePaper)."""
    service, storage, vault, fake_backend = _make_service(tmp_path)
    cfg_dir = tmp_path / "backend_dirs" / ".fake-personal"
    cfg_dir.parent.mkdir(exist_ok=True)
    cfg_dir.mkdir()
    b = await service.create("fake", display_name="p1", config={"config_path": str(cfg_dir)})
    await service.store_credential(b.id, b"fake-credential")
    b = await service.validate(b.id)
    assert b.status == BackendStatus.READY

    from ai_accounts_core.services.discovery import DiscoveredConfig

    async def fake_discover_all(kinds, *, probe_timeout=12.0):
        return [
            DiscoveredConfig(
                kind="fake",
                path=str(cfg_dir),
                suggested_name="p1",
                is_logged_in=False,
                error="probe timed out after 12.0s",
            )
        ]

    monkeypatch.setattr("ai_accounts_core.services.discovery.discover_all", fake_discover_all)
    enriched = await service.discover_existing()
    refreshed = await service.get(b.id)
    assert refreshed.status == BackendStatus.READY, "timeout must not downgrade READY"
    assert enriched[0].backend_id == b.id


@pytest.mark.asyncio
async def test_discover_definitive_failure_still_downgrades(tmp_path, monkeypatch):
    """A definitive not-logged-in probe (no timeout) keeps the existing
    READY → ERROR sync so genuinely-expired logins still surface."""
    service, storage, vault, fake_backend = _make_service(tmp_path)
    cfg_dir = tmp_path / "backend_dirs" / ".fake-personal"
    cfg_dir.parent.mkdir(exist_ok=True)
    cfg_dir.mkdir()
    b = await service.create("fake", display_name="p1", config={"config_path": str(cfg_dir)})
    await service.store_credential(b.id, b"fake-credential")
    b = await service.validate(b.id)
    assert b.status == BackendStatus.READY

    from ai_accounts_core.services.discovery import DiscoveredConfig

    async def fake_discover_all(kinds, *, probe_timeout=12.0):
        return [
            DiscoveredConfig(
                kind="fake",
                path=str(cfg_dir),
                suggested_name="p1",
                is_logged_in=False,
                error="not logged in",
            )
        ]

    monkeypatch.setattr("ai_accounts_core.services.discovery.discover_all", fake_discover_all)
    await service.discover_existing()
    refreshed = await service.get(b.id)
    assert refreshed.status == BackendStatus.ERROR


@pytest.mark.asyncio
async def test_vault_key_mismatch_flags_account_error(tmp_path, monkeypatch):
    """A credential that fails vault decryption (wrong AI_ACCOUNTS_VAULT_KEY)
    must flip the row to ERROR with a readable last_error and raise a typed
    CredentialUnreadable — not escape as an opaque 500."""
    from ai_accounts_core.protocols.vault import VaultError
    from ai_accounts_core.services.errors import CredentialUnreadable

    service, storage, vault, fake_backend = _make_service(tmp_path)
    b = await service.create("fake", display_name="p1")
    await service.store_credential(b.id, b"fake-credential")
    b = await service.validate(b.id)
    assert b.status == BackendStatus.READY

    async def bad_decrypt(ciphertext, *, context):
        raise VaultError("vault decryption failed (tamper, wrong context, or wrong key)")

    monkeypatch.setattr(vault, "decrypt", bad_decrypt)
    with pytest.raises(CredentialUnreadable):
        await service.list_models(b.id)
    refreshed = await service.get(b.id)
    assert refreshed.status == BackendStatus.ERROR
    assert "vault key mismatch" in (refreshed.last_error or "")


@pytest.mark.asyncio
async def test_discover_other_kind_glob_match_is_ignored(tmp_path, monkeypatch):
    """A candidate probed as a DIFFERENT kind that happens to glob-match an
    existing row's config_path (e.g. claude's ".claude*" catching a
    claude_custom dir) must neither downgrade the row nor surface as
    importable — the wrong-kind probe's verdict says nothing about it."""
    service, storage, vault, fake_backend = _make_service(tmp_path)
    cfg_dir = tmp_path / "backend_dirs" / ".fake-custom"
    cfg_dir.parent.mkdir(exist_ok=True)
    cfg_dir.mkdir()
    b = await service.create("fake", display_name="p1", config={"config_path": str(cfg_dir)})
    await service.store_credential(b.id, b"fake-credential")
    b = await service.validate(b.id)
    assert b.status == BackendStatus.READY

    from ai_accounts_core.services.discovery import DiscoveredConfig

    async def fake_discover_all(kinds, *, probe_timeout=12.0):
        return [
            DiscoveredConfig(
                kind="claude",
                path=str(cfg_dir),
                suggested_name="p1",
                is_logged_in=False,
                error="not logged in",
            )
        ]

    monkeypatch.setattr("ai_accounts_core.services.discovery.discover_all", fake_discover_all)
    enriched = await service.discover_existing()
    refreshed = await service.get(b.id)
    assert refreshed.status == BackendStatus.READY, "wrong-kind probe must not downgrade"
    assert enriched == []
