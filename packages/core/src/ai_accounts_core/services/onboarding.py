from __future__ import annotations

from ai_accounts_core.domain.backend import Backend, DetectResult
from ai_accounts_core.domain.onboarding import OnboardingState, OnboardingStep
from ai_accounts_core.ids import new_id
from ai_accounts_core.protocols.storage import StorageProtocol

from .accounts import AccountService, LoginResponse
from .errors import BackendKindUnknown, BackendNotFound, ServiceError


class OnboardingNotFound(ServiceError):
    code = "onboarding_not_found"


class OnboardingService:
    def __init__(
        self,
        *,
        storage: StorageProtocol,
        accounts: AccountService,
        backend_kinds: tuple[str, ...],
    ) -> None:
        self._storage = storage
        self._accounts = accounts
        self._backend_kinds = tuple(backend_kinds)

    async def start(self) -> OnboardingState:
        state = OnboardingState(
            id=new_id("onb"),
            current_step=OnboardingStep.WELCOME,
        )
        repo = await self._storage.onboarding()
        await repo.put(state)
        return state

    async def get(self, onboarding_id: str) -> OnboardingState:
        repo = await self._storage.onboarding()
        state = await repo.get(onboarding_id)
        if state is None:
            raise OnboardingNotFound(onboarding_id)
        return state

    async def detect_all(self, onboarding_id: str) -> dict[str, DetectResult]:
        state = await self.get(onboarding_id)
        results: dict[str, DetectResult] = {}
        for kind in self._backend_kinds:
            try:
                impl = self._accounts._impl_for(kind)
            except KeyError:
                continue
            results[kind] = await impl.detect()
        updated = OnboardingState(
            id=state.id,
            current_step=OnboardingStep.PICK_BACKEND,
            selected_backend_kind=state.selected_backend_kind,
            created_backend_id=state.created_backend_id,
            error=state.error,
        )
        repo = await self._storage.onboarding()
        await repo.put(updated)
        return results

    async def pick_kind(
        self, onboarding_id: str, kind: str, *, display_name: str
    ) -> Backend:
        state = await self.get(onboarding_id)
        if kind not in self._backend_kinds:
            raise BackendKindUnknown(f"unknown backend kind: {kind}")
        backend = await self._accounts.create(kind, display_name=display_name)
        updated = OnboardingState(
            id=state.id,
            current_step=OnboardingStep.LOGIN,
            selected_backend_kind=kind,
            created_backend_id=backend.id,
            error=None,
        )
        repo = await self._storage.onboarding()
        await repo.put(updated)
        return backend

    async def begin_login(
        self,
        onboarding_id: str,
        *,
        flow_kind: str,
        inputs: dict[str, str],
    ) -> LoginResponse:
        state = await self.get(onboarding_id)
        if state.created_backend_id is None:
            raise BackendNotFound("no backend selected in this onboarding session")
        return await self._accounts.login(
            state.created_backend_id, flow_kind=flow_kind, inputs=inputs
        )

    async def poll_login(
        self, onboarding_id: str, *, handle: str
    ) -> LoginResponse:
        state = await self.get(onboarding_id)
        if state.created_backend_id is None:
            raise BackendNotFound("no backend selected in this onboarding session")
        return await self._accounts.poll_login(
            state.created_backend_id, handle=handle
        )

    async def finalize(self, onboarding_id: str) -> OnboardingState:
        state = await self.get(onboarding_id)
        if state.created_backend_id is None:
            raise BackendNotFound("no backend to validate")
        repo = await self._storage.onboarding()
        try:
            await self._accounts.validate(state.created_backend_id)
        except Exception as exc:
            error_state = OnboardingState(
                id=state.id,
                current_step=OnboardingStep.VALIDATE,
                selected_backend_kind=state.selected_backend_kind,
                created_backend_id=state.created_backend_id,
                error=str(exc),
            )
            await repo.put(error_state)
            raise
        final = OnboardingState(
            id=state.id,
            current_step=OnboardingStep.DONE,
            selected_backend_kind=state.selected_backend_kind,
            created_backend_id=state.created_backend_id,
            error=None,
        )
        await repo.put(final)
        return final
