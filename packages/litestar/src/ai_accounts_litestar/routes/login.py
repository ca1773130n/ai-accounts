"""Login session routes — /begin, /stream (SSE), /respond, /cancel."""

from __future__ import annotations

import logging

import msgspec
from litestar import Controller, get, post
from litestar.exceptions import HTTPException, NotFoundException
from litestar.response import ServerSentEvent
from litestar.status_codes import HTTP_201_CREATED, HTTP_204_NO_CONTENT

from ai_accounts_core.login import LoginComplete, PromptAnswer
from ai_accounts_core.services.accounts import AccountService
from ai_accounts_core.services.errors import (
    BackendKindUnknown,
    BackendNotFound,
    LoginFlowUnsupported,
)

logger = logging.getLogger(__name__)


class _BeginRequest(msgspec.Struct, kw_only=True):
    flow_kind: str
    inputs: dict[str, str] = {}


class _BeginResponse(msgspec.Struct, kw_only=True):
    session_id: str


class _RespondRequest(msgspec.Struct, kw_only=True):
    session_id: str
    prompt_id: str
    answer: str


class _CancelRequest(msgspec.Struct, kw_only=True):
    session_id: str


class LoginController(Controller):
    path = "/api/v1/backends/{backend_id:str}/login"
    tags = ["login"]

    @post("/begin", status_code=HTTP_201_CREATED)
    async def begin(
        self,
        backend_id: str,
        data: _BeginRequest,
        account_service: AccountService,
    ) -> _BeginResponse:
        try:
            session = await account_service.begin_login(
                backend_id, flow_kind=data.flow_kind, inputs=data.inputs
            )
        except BackendNotFound as e:
            raise NotFoundException(detail=str(e)) from e
        except (BackendKindUnknown, LoginFlowUnsupported) as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        return _BeginResponse(session_id=session.session_id)

    @get("/stream")
    async def stream(
        self,
        backend_id: str,
        session_id: str,
        account_service: AccountService,
    ) -> ServerSentEvent:
        session = await account_service.login_registry.get(session_id)
        if session is None:
            raise NotFoundException(detail=f"session {session_id} not found")

        registry = account_service.login_registry

        async def gen():
            try:
                async for event in session.events():
                    yield {
                        "event": "login",
                        "data": msgspec.json.encode(event).decode(),
                    }
                    # After LoginComplete, auto-store credential so the
                    # backend transitions to READY. For CLI-browser/OAuth
                    # flows, the CLI wrote the token to its config dir —
                    # we store empty bytes as the "credential" since
                    # validate()/list_models()/chat() use the config dir
                    # via CLAUDE_CONFIG_DIR / CODEX_HOME / etc.
                    if isinstance(event, LoginComplete):
                        try:
                            # API key flows store the key; CLI-browser
                            # flows store empty bytes (the CLI wrote its
                            # OAuth token to the config dir).
                            cred = session.credential or b""
                            await account_service.store_credential(
                                backend_id, cred
                            )
                            await account_service.validate(backend_id)
                            logger.info(
                                "auto-stored credential for %s after login",
                                backend_id,
                            )
                        except Exception:
                            logger.warning(
                                "failed to auto-store credential for %s",
                                backend_id,
                                exc_info=True,
                            )
            finally:
                await session.cancel()
                await registry.remove(session_id)

        return ServerSentEvent(gen())

    @post("/respond", status_code=HTTP_204_NO_CONTENT)
    async def respond(
        self,
        backend_id: str,
        data: _RespondRequest,
        account_service: AccountService,
    ) -> None:
        session = await account_service.login_registry.get(data.session_id)
        if session is None:
            raise NotFoundException(detail=f"session {data.session_id} not found")
        await session.respond(PromptAnswer(prompt_id=data.prompt_id, answer=data.answer))

    @post("/cancel", status_code=HTTP_204_NO_CONTENT)
    async def cancel(
        self,
        backend_id: str,
        data: _CancelRequest,
        account_service: AccountService,
    ) -> None:
        session = await account_service.login_registry.get(data.session_id)
        if session is None:
            return
        await session.cancel()
        await account_service.login_registry.remove(data.session_id)
