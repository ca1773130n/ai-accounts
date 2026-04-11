import pytest

from ai_accounts_core.domain.backend import BackendStatus
from ai_accounts_core.services.accounts import AccountService
from ai_accounts_core.services.errors import (
    BackendKindUnknown,
    BackendNotFound,
    BackendValidationFailed,
)
from ai_accounts_core.testing import FakeBackend, FakeStorage, FakeVault


def _make_service():
    storage = FakeStorage()
    vault = FakeVault()
    fake_backend = FakeBackend()
    service = AccountService(
        storage=storage,
        vault=vault,
        backends={fake_backend.kind: fake_backend},
    )
    return service, storage, vault, fake_backend


@pytest.mark.asyncio
async def test_create_backend_persists_and_returns():
    service, storage, _, _ = _make_service()
    created = await service.create("fake", display_name="Test")
    assert created.display_name == "Test"
    assert created.status is BackendStatus.UNCONFIGURED
    assert created.kind == "fake"
    assert created.id.startswith("bkd-")

    repo = await storage.backends()
    fetched = await repo.get(created.id)
    assert fetched == created


@pytest.mark.asyncio
async def test_create_backend_unknown_kind_raises():
    service, _, _, _ = _make_service()
    with pytest.raises(BackendKindUnknown):
        await service.create("martian-ai", display_name="x")


@pytest.mark.asyncio
async def test_list_backends_returns_all():
    service, _, _, _ = _make_service()
    a = await service.create("fake", display_name="A")
    b = await service.create("fake", display_name="B")
    listed = await service.list()
    assert {bk.id for bk in listed} == {a.id, b.id}


@pytest.mark.asyncio
async def test_get_backend_missing_raises():
    service, _, _, _ = _make_service()
    with pytest.raises(BackendNotFound):
        await service.get("bkd-nope")


@pytest.mark.asyncio
async def test_delete_backend_removes_credential_too():
    service, storage, _, _ = _make_service()
    created = await service.create("fake", display_name="A")
    await service.login(created.id, flow_kind="api_key", inputs={})
    await service.delete(created.id)
    with pytest.raises(BackendNotFound):
        await service.get(created.id)
    repo = await storage.backends()
    assert await repo.get_credential(created.id) is None


@pytest.mark.asyncio
async def test_detect_backend_returns_result():
    service, _, _, _ = _make_service()
    created = await service.create("fake", display_name="A")
    result = await service.detect(created.id)
    assert result.installed is True
    assert result.version == "fake/0.0"


@pytest.mark.asyncio
async def test_login_then_validate_happy_path():
    service, storage, _, _ = _make_service()
    created = await service.create("fake", display_name="A")

    after_login = await service.login(created.id, flow_kind="api_key", inputs={})
    assert after_login.status is BackendStatus.VALIDATING

    # Credential was stored encrypted
    repo = await storage.backends()
    stored_cred = await repo.get_credential(created.id)
    assert stored_cred is not None
    assert stored_cred.ciphertext != b"fake-credential"  # must be encrypted

    after_validate = await service.validate(created.id)
    assert after_validate.status is BackendStatus.READY
    assert after_validate.last_error is None


@pytest.mark.asyncio
async def test_validate_failure_sets_error_status():
    from datetime import UTC, datetime

    from ai_accounts_core.domain.backend import BackendCredential

    service, storage, vault, _ = _make_service()
    created = await service.create("fake", display_name="A")
    await service.login(created.id, flow_kind="api_key", inputs={})

    # Replace stored credential with one that FakeBackend.validate rejects.
    repo = await storage.backends()
    wrong_ct = await vault.encrypt(
        b"wrong-credential", context={"backend_id": created.id}
    )
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
