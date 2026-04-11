from pathlib import Path

import pytest

from ai_accounts_core.domain.onboarding import OnboardingStep
from ai_accounts_core.services.accounts import AccountService
from ai_accounts_core.services.errors import BackendKindUnknown
from ai_accounts_core.services.onboarding import (
    OnboardingNotFound,
    OnboardingService,
)
from ai_accounts_core.testing import FakeBackend, FakeStorage, FakeVault


@pytest.fixture
def onboarding_service(tmp_path: Path):
    storage = FakeStorage()
    vault = FakeVault()
    fake_backend = FakeBackend()
    accounts = AccountService(
        storage=storage,
        vault=vault,
        backends={fake_backend.kind: fake_backend},
        isolation_base_dir=tmp_path / "backend_dirs",
    )
    return OnboardingService(
        storage=storage,
        accounts=accounts,
        backend_kinds=("fake",),
    )


@pytest.mark.asyncio
async def test_start_returns_welcome_state(onboarding_service):
    state = await onboarding_service.start()
    assert state.current_step is OnboardingStep.WELCOME
    assert state.id.startswith("onb-")


@pytest.mark.asyncio
async def test_get_unknown_raises(onboarding_service):
    with pytest.raises(OnboardingNotFound):
        await onboarding_service.get("onb-nope")


@pytest.mark.asyncio
async def test_detect_transitions_to_pick_backend(onboarding_service):
    state = await onboarding_service.start()
    detections = await onboarding_service.detect_all(state.id)
    assert "fake" in detections
    assert detections["fake"].installed is True
    updated = await onboarding_service.get(state.id)
    assert updated.current_step is OnboardingStep.PICK_BACKEND


@pytest.mark.asyncio
async def test_pick_kind_creates_backend_and_transitions_to_login(onboarding_service):
    state = await onboarding_service.start()
    await onboarding_service.detect_all(state.id)
    created = await onboarding_service.pick_kind(
        state.id, "fake", display_name="Fake Account"
    )
    assert created.kind == "fake"
    updated = await onboarding_service.get(state.id)
    assert updated.current_step is OnboardingStep.LOGIN
    assert updated.created_backend_id == created.id
    assert updated.selected_backend_kind == "fake"


@pytest.mark.asyncio
async def test_pick_kind_unknown_kind_raises(onboarding_service):
    state = await onboarding_service.start()
    await onboarding_service.detect_all(state.id)
    with pytest.raises(BackendKindUnknown):
        await onboarding_service.pick_kind(state.id, "martian", display_name="X")


@pytest.mark.asyncio
async def test_begin_login_api_key_happy_path(onboarding_service):
    state = await onboarding_service.start()
    await onboarding_service.detect_all(state.id)
    await onboarding_service.pick_kind(state.id, "fake", display_name="X")
    response = await onboarding_service.begin_login(
        state.id, flow_kind="api_key", inputs={}
    )
    assert response.kind == "complete"


@pytest.mark.asyncio
async def test_finalize_validates_and_transitions_to_done(onboarding_service):
    state = await onboarding_service.start()
    await onboarding_service.detect_all(state.id)
    await onboarding_service.pick_kind(state.id, "fake", display_name="X")
    await onboarding_service.begin_login(state.id, flow_kind="api_key", inputs={})
    final = await onboarding_service.finalize(state.id)
    assert final.current_step is OnboardingStep.DONE
    assert final.created_backend_id is not None
    assert final.error is None


@pytest.mark.asyncio
async def test_oauth_polling_through_onboarding(onboarding_service):
    state = await onboarding_service.start()
    await onboarding_service.detect_all(state.id)
    await onboarding_service.pick_kind(state.id, "fake", display_name="X")
    start = await onboarding_service.begin_login(
        state.id, flow_kind="oauth_device", inputs={}
    )
    assert start.kind == "pending"
    handle = start.oauth.handle

    first = await onboarding_service.poll_login(state.id, handle=handle)
    assert first.kind == "pending"
    second = await onboarding_service.poll_login(state.id, handle=handle)
    assert second.kind == "complete"

    final = await onboarding_service.finalize(state.id)
    assert final.current_step is OnboardingStep.DONE
