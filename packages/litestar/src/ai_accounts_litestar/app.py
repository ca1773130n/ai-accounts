from litestar import Litestar, get

from ai_accounts_core import __version__ as core_version

from .config import AiAccountsConfig


@get("/health", sync_to_thread=False)
def health() -> dict[str, str]:
    return {"status": "ok", "version": core_version}


def create_app(config: AiAccountsConfig) -> Litestar:
    return Litestar(route_handlers=[health], debug=config.env == "development")
