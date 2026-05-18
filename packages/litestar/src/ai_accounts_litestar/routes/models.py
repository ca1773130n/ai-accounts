from ai_accounts_core.services.accounts import AccountService
from litestar import Controller, get


class ModelsController(Controller):
    path = "/api/v1/backends/{backend_id:str}/models"

    @get("/")
    async def list_models(self, account_service: AccountService, backend_id: str) -> dict:
        models = await account_service.list_models(backend_id)
        return {
            "items": [
                {
                    "id": m.id,
                    "display_name": m.display_name,
                    "context_window": m.context_window,
                    "input_price_per_mtok": m.input_price_per_mtok,
                    "output_price_per_mtok": m.output_price_per_mtok,
                }
                for m in models
            ]
        }
