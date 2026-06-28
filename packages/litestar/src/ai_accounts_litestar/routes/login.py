"""Login session routes — /begin, /stream (SSE), /respond, /cancel."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

import msgspec
from ai_accounts_core.login import LoginComplete, PromptAnswer
from ai_accounts_core.services.accounts import AccountService
from ai_accounts_core.services.errors import (
    BackendKindUnknown,
    BackendNotFound,
    LoginFlowUnsupported,
)
from litestar import Controller, get, post
from litestar.exceptions import HTTPException, NotFoundException
from litestar.response import ServerSentEvent
from litestar.status_codes import HTTP_201_CREATED, HTTP_204_NO_CONTENT

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


class _WriteEagerRequest(msgspec.Struct, kw_only=True):
    """Body for POST /login/write: write arbitrary stdin to the CLI."""

    session_id: str
    text: str


def _not_found(session_id: str) -> NotFoundException:
    # Intentionally does not distinguish "wrong backend" from "no such
    # session" so attackers cannot probe for session IDs across backends.
    return NotFoundException(detail=f"session {session_id} not found")


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
        # Enforce that the session was registered for *this* backend_id.
        # Without this, any leaked session_id could be used to attach to
        # another backend's login stream or misroute the resulting credential.
        session = await account_service.login_registry.get(session_id, backend_id=backend_id)
        if session is None:
            raise _not_found(session_id)

        registry = account_service.login_registry

        async def gen() -> AsyncIterator[dict[str, str]]:
            try:
                # Replay the cached UrlPrompt to the subscriber FIRST, so
                # reconnecting clients (refresh, network blip) immediately
                # see the OAuth URL instead of waiting for the next live
                # event. Live dedup happens on the client via the existing
                # url_already_emitted flag in useLoginSession.
                cached_url = session.last_url_prompt
                if cached_url is not None:
                    yield {
                        "event": "login",
                        "data": msgspec.json.encode(cached_url).decode(),
                    }
                async for event in session.events_with_replay():
                    # Avoid emitting the same UrlPrompt back-to-back when
                    # the live iterator's first event turns out to be the
                    # one we just replayed.
                    if cached_url is not None and event is cached_url:
                        continue
                    # LoginComplete is the session's "I'm done collecting
                    # credentials" event — the wizard auto-advances past the
                    # login step on it. We must NOT emit it until after
                    # store_credential + validate have actually succeeded;
                    # otherwise an invalid api-key (or any validation
                    # failure) shows the user a green "Login complete"
                    # while the backend silently transitions to error and
                    # the wizard has already moved on. Hold the event,
                    # run the side-effects, then emit either the original
                    # LoginComplete (success path) OR a LoginFailed-shaped
                    # error frame (failure path) — never both.
                    if isinstance(event, LoginComplete):
                        try:
                            # API key flows store the key; CLI-browser
                            # flows store empty bytes (the CLI wrote its
                            # OAuth token to the config dir).
                            cred = session.credential or b""
                            await account_service.store_credential(backend_id, cred)
                            await account_service.validate(backend_id)
                        except Exception as exc:
                            logger.warning(
                                "failed to auto-store credential for %s",
                                backend_id,
                                exc_info=True,
                            )
                            err_payload = {
                                "type": "failed",
                                "code": "credential_store_failed",
                                "message": (
                                    f"login completed but credential "
                                    f"persistence/validation failed: "
                                    f"{type(exc).__name__}: {exc}"
                                ),
                            }
                            yield {
                                "event": "login",
                                "data": msgspec.json.encode(err_payload).decode(),
                            }
                            continue
                        # Validate succeeded — now safe to tell the client
                        # the login completed.
                        logger.info(
                            "auto-stored credential for %s after login",
                            backend_id,
                        )
                        yield {
                            "event": "login",
                            "data": msgspec.json.encode(event).decode(),
                        }
                    else:
                        yield {
                            "event": "login",
                            "data": msgspec.json.encode(event).decode(),
                        }
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
        session = await account_service.login_registry.get(data.session_id, backend_id=backend_id)
        if session is None:
            raise _not_found(data.session_id)
        await session.respond(PromptAnswer(prompt_id=data.prompt_id, answer=data.answer))

    @post("/write", status_code=HTTP_204_NO_CONTENT)
    async def write_eager(
        self,
        backend_id: str,
        data: _WriteEagerRequest,
        account_service: AccountService,
    ) -> None:
        """Write text directly to the CLI's stdin.

        Used for the AccountWizard's eager paste-code form, which submits
        the OAuth code before the CLI has emitted its own textPrompt.
        """
        session = await account_service.login_registry.get(data.session_id, backend_id=backend_id)
        if session is None:
            raise _not_found(data.session_id)
        await session.write_eager(data.text)

    @post("/cancel", status_code=HTTP_204_NO_CONTENT)
    async def cancel(
        self,
        backend_id: str,
        data: _CancelRequest,
        account_service: AccountService,
    ) -> None:
        session = await account_service.login_registry.get(data.session_id, backend_id=backend_id)
        if session is None:
            # Cancel is idempotent; an already-gone session is not an error
            # for a correctly-scoped client. A backend mismatch is silently
            # ignored (same shape) to avoid probing across backends.
            return
        await session.cancel()
        await account_service.login_registry.remove(data.session_id)
