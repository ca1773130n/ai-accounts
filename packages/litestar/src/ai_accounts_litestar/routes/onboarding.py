from litestar import Controller, get, post, status_codes

from ai_accounts_core.services.onboarding import OnboardingService

from ..dto import (
    BackendDTO,
    DetectResultDTO,
    DetectResultsDTO,
    LoginRequest,
    LoginResponseDTO,
    OnboardingStateDTO,
    PickKindRequest,
    PollLoginRequest,
)


class OnboardingController(Controller):
    path = "/api/v1/onboarding"
    tags = ["onboarding"]

    @post("/", status_code=status_codes.HTTP_201_CREATED)
    async def start(
        self, onboarding_service: OnboardingService
    ) -> OnboardingStateDTO:
        state = await onboarding_service.start()
        return OnboardingStateDTO.from_domain(state)

    @get("/{onboarding_id:str}")
    async def get_state(
        self, onboarding_id: str, onboarding_service: OnboardingService
    ) -> OnboardingStateDTO:
        state = await onboarding_service.get(onboarding_id)
        return OnboardingStateDTO.from_domain(state)

    @post("/{onboarding_id:str}/detect")
    async def detect(
        self, onboarding_id: str, onboarding_service: OnboardingService
    ) -> DetectResultsDTO:
        results = await onboarding_service.detect_all(onboarding_id)
        return DetectResultsDTO(
            results={k: DetectResultDTO.from_domain(v) for k, v in results.items()}
        )

    @post("/{onboarding_id:str}/pick")
    async def pick(
        self,
        onboarding_id: str,
        data: PickKindRequest,
        onboarding_service: OnboardingService,
    ) -> BackendDTO:
        backend = await onboarding_service.pick_kind(
            onboarding_id, data.kind, display_name=data.display_name
        )
        return BackendDTO.from_domain(backend)

    @post("/{onboarding_id:str}/login")
    async def login(
        self,
        onboarding_id: str,
        data: LoginRequest,
        onboarding_service: OnboardingService,
    ) -> LoginResponseDTO:
        response = await onboarding_service.begin_login(
            onboarding_id, flow_kind=data.flow_kind, inputs=data.inputs
        )
        return LoginResponseDTO.from_service(response)

    @post("/{onboarding_id:str}/login/poll")
    async def poll_login(
        self,
        onboarding_id: str,
        data: PollLoginRequest,
        onboarding_service: OnboardingService,
    ) -> LoginResponseDTO:
        response = await onboarding_service.poll_login(
            onboarding_id, handle=data.handle
        )
        return LoginResponseDTO.from_service(response)

    @post("/{onboarding_id:str}/finalize")
    async def finalize(
        self, onboarding_id: str, onboarding_service: OnboardingService
    ) -> OnboardingStateDTO:
        state = await onboarding_service.finalize(onboarding_id)
        return OnboardingStateDTO.from_domain(state)
