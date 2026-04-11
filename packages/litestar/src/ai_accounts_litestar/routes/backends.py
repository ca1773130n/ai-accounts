from litestar import Controller, delete, get, patch, post, status_codes

from ai_accounts_core.services.accounts import AccountService

from ..dto import (
    BackendDTO,
    BackendListDTO,
    CreateBackendRequest,
    DetectResultDTO,
    UpdateBackendRequest,
)


class BackendsController(Controller):
    path = "/api/v1/backends"
    tags = ["backends"]

    @get("/")
    async def list_backends(self, account_service: AccountService) -> BackendListDTO:
        items = await account_service.list()
        return BackendListDTO(items=[BackendDTO.from_domain(b) for b in items])

    @post("/", status_code=status_codes.HTTP_201_CREATED)
    async def create_backend(
        self, data: CreateBackendRequest, account_service: AccountService
    ) -> BackendDTO:
        created = await account_service.create(
            data.kind, display_name=data.display_name, config=data.config
        )
        return BackendDTO.from_domain(created)

    @get("/{backend_id:str}")
    async def get_backend(
        self, backend_id: str, account_service: AccountService
    ) -> BackendDTO:
        return BackendDTO.from_domain(await account_service.get(backend_id))

    @patch("/{backend_id:str}")
    async def update_backend(
        self,
        backend_id: str,
        data: UpdateBackendRequest,
        account_service: AccountService,
    ) -> BackendDTO:
        kwargs: dict[str, object] = {}
        if data.display_name is not None:
            kwargs["display_name"] = data.display_name
        if data.config is not None:
            kwargs["config"] = data.config
        updated = await account_service.update(backend_id, **kwargs)  # type: ignore[arg-type]
        return BackendDTO.from_domain(updated)

    @delete("/{backend_id:str}")
    async def delete_backend(
        self, backend_id: str, account_service: AccountService
    ) -> None:
        await account_service.delete(backend_id)

    @post("/{backend_id:str}/detect")
    async def detect(
        self, backend_id: str, account_service: AccountService
    ) -> DetectResultDTO:
        return DetectResultDTO.from_domain(await account_service.detect(backend_id))

    @post("/{backend_id:str}/validate")
    async def validate(
        self, backend_id: str, account_service: AccountService
    ) -> BackendDTO:
        return BackendDTO.from_domain(await account_service.validate(backend_id))
