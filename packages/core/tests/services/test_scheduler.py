import pytest
from ai_accounts_core.domain.usage import FallbackChainEntry
from ai_accounts_core.services.accounts import AccountService
from ai_accounts_core.services.scheduler import AccountScheduler
from ai_accounts_core.testing.fakes import FakeBackend, FakeStorage, FakeVault


@pytest.fixture
async def scheduler(tmp_path):
    storage = FakeStorage()
    vault = FakeVault()
    fake = FakeBackend()
    accounts = AccountService(
        storage=storage,
        vault=vault,
        backends={"fake": fake},
        isolation_base_dir=tmp_path,
    )
    b1 = await accounts.create(kind="fake", display_name="Account 1")
    await accounts.store_credential(b1.id, b"sk-fake-1")
    await accounts.validate(b1.id)
    b2 = await accounts.create(kind="fake", display_name="Account 2")
    await accounts.store_credential(b2.id, b"sk-fake-2")
    await accounts.validate(b2.id)
    sched = AccountScheduler(account_service=accounts, storage=storage)
    return sched, b1.id, b2.id


@pytest.mark.asyncio
async def test_pick_returns_account(scheduler):
    sched, b1, b2 = scheduler
    result = await sched.pick()
    assert result is not None
    assert result.backend_id in (b1, b2)
    assert result.kind == "fake"
    assert result.credential is not None


@pytest.mark.asyncio
async def test_pick_with_chain_respects_priority(scheduler):
    sched, b1, b2 = scheduler
    await sched.set_chain(
        [
            FallbackChainEntry(backend_id=b2, priority=0),
            FallbackChainEntry(backend_id=b1, priority=1),
        ]
    )
    result = await sched.pick()
    assert result is not None
    assert result.backend_id == b2


@pytest.mark.asyncio
async def test_pick_skips_rate_limited(scheduler):
    sched, b1, b2 = scheduler
    await sched.set_chain(
        [
            FallbackChainEntry(backend_id=b1, priority=0),
            FallbackChainEntry(backend_id=b2, priority=1),
        ]
    )
    await sched.mark_rate_limited(b1, 3600, "429 from API")
    result = await sched.pick()
    assert result is not None
    assert result.backend_id == b2


@pytest.mark.asyncio
async def test_pick_returns_none_when_all_exhausted(scheduler):
    sched, b1, b2 = scheduler
    await sched.mark_rate_limited(b1, 3600, "429")
    await sched.mark_rate_limited(b2, 1800, "429")
    result = await sched.pick()
    assert result is None


@pytest.mark.asyncio
async def test_pick_filters_by_kind(scheduler):
    sched, b1, b2 = scheduler
    result = await sched.pick(kind="fake")
    assert result is not None
    result_wrong = await sched.pick(kind="nonexistent")
    assert result_wrong is None


@pytest.mark.asyncio
async def test_chain_crud(scheduler):
    sched, b1, b2 = scheduler
    await sched.set_chain(
        [
            FallbackChainEntry(backend_id=b2, priority=0),
            FallbackChainEntry(backend_id=b1, priority=1),
        ]
    )
    chain = await sched.get_chain()
    assert len(chain) == 2
    assert chain[0].backend_id == b2


@pytest.mark.asyncio
async def test_poll_all_updates_health(scheduler):
    sched, b1, b2 = scheduler
    await sched.poll_all()
    health = await sched.get_health(b1)
    assert len(health.windows) >= 1
    assert health.windows[0].window_type == "five_hour"


@pytest.mark.asyncio
async def test_get_all_health(scheduler):
    sched, b1, b2 = scheduler
    await sched.poll_all()
    all_health = await sched.get_all_health()
    assert len(all_health) == 2
