from typing import Any

from litestar import Request, Response


def service_error_handler(request: Request[Any, Any, Any], exc: Exception) -> Response[Any]:
    return Response(
        content={"error": {"code": "service_error", "message": str(exc)}},
        status_code=500,
    )
