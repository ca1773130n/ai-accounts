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
    await service.login(created.id, flow_kind="api_key", inputs={})
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
async def test_login_then_validate_happy_path(tmp_path):
    service, storage, _, _ = _make_service(tmp_path)
    created = await service.create("fake", display_name="A")

    after_login = await service.login(created.id, flow_kind="api_key", inputs={})
    assert after_login.kind == "complete"
    assert after_login.backend is not None
    assert after_login.backend.status is BackendStatus.VALIDATING

    # Credential was stored encrypted
    repo = await storage.backends()
    stored_cred = await repo.get_credential(created.id)
    assert stored_cred is not None
    assert stored_cred.ciphertext != b"fake-credential"  # must be encrypted

    after_validate = await service.validate(created.id)
    assert after_validate.status is BackendStatus.READY
    assert after_validate.last_error is None


@pytest.mark.asyncio
async def test_validate_failure_sets_error_status(tmp_path):
    service, storage, vault, _ = _make_service(tmp_path)
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
async def test_login_oauth_returns_pending_response(tmp_path):
    service, _, _, _ = _make_service(tmp_path)
    created = await service.create("fake", display_name="Test")
    response = await service.login(created.id, flow_kind="oauth_device", inputs={})
    assert response.kind == "pending"
    assert response.oauth is not None
    assert response.oauth.handle.startswith("fake-handle-")


@pytest.mark.asyncio
async def test_poll_login_eventually_completes(tmp_path):
    service, _, _, _ = _make_service(tmp_path)
    created = await service.create("fake", display_name="Test")
    start = await service.login(created.id, flow_kind="oauth_device", inputs={})
    assert start.kind == "pending"
    handle = start.oauth.handle

    first_poll = await service.poll_login(created.id, handle=handle)
    assert first_poll.kind == "pending"
    second_poll = await service.poll_login(created.id, handle=handle)
    assert second_poll.kind == "complete"
    assert second_poll.backend.status is BackendStatus.VALIDATING

    validated = await service.validate(created.id)
    assert validated.status is BackendStatus.READY


@pytest.mark.asyncio
async def test_login_unsupported_flow_raises(tmp_path):
    from ai_accounts_core.protocols.backend import CredentialLogin
    from ai_accounts_core.testing import FakeStorage, FakeVault

    class ApiKeyOnlyFake:
        kind = "ko"
        supported_login_flows: frozenset[str] = frozenset({"api_key"})

        async def detect(self):  # type: ignore[return]
            from ai_accounts_core.domain.backend import DetectResult
            return DetectResult(installed=True)

        async def login(self, flow, *, isolation_dir):  # type: ignore[return]
            return CredentialLogin(credential=b"x")

        async def poll_login(self, handle, *, isolation_dir):  # type: ignore[return]
            from ai_accounts_core.protocols.backend import LoginError
            return LoginError(code="not_pollable", message="")

        async def validate(self, credential, *, isolation_dir) -> bool:
            return True

        async def list_models(self, credential, *, isolation_dir):  # type: ignore[return]
            return []

        async def chat(self, request, credential, *, isolation_dir):
            raise NotImplementedError

        async def pty(self, request, credential, *, isolation_dir):
            raise NotImplementedError

    svc = AccountService(
        storage=FakeStorage(),
        vault=FakeVault(),
        backends={"ko": ApiKeyOnlyFake()},  # type: ignore[dict-item]
        isolation_base_dir=tmp_path / "backend_dirs",
    )
    created = await svc.create("ko", display_name="X")
    with pytest.raises(LoginFlowUnsupported):
        await svc.login(created.id, flow_kind="oauth_device", inputs={})
