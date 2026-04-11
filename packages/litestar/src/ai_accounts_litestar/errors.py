from typing import Any

from litestar import Request, Response

from ai_accounts_core.services.errors import ServiceError

_STATUS_BY_CODE: dict[str, int] = {
    "backend_not_found": 404,
    "backend_kind_unknown": 400,
    "backend_already_exists": 409,
    "backend_not_ready": 409,
    "backend_validation_failed": 400,
    "credential_missing": 409,
    "login_flow_unsupported": 400,
    "onboarding_not_found": 404,
}


def service_error_handler(
    request: Request[Any, Any, Any], exc: Exception
) -> Response[Any]:
    if isinstance(exc, ServiceError):
        status = _STATUS_BY_CODE.get(exc.code, 500)
        return Response(
            content={"error": {"code": exc.code, "message": str(exc) or exc.code}},
            status_code=status,
        )
    return Response(
        content={"error": {"code": "internal_error", "message": str(exc)}},
        status_code=500,
    )
