from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

from ai_accounts_core.domain.chat import ChatDelta, ChatMessage, ChatRole
from ai_accounts_core.domain.chat_events import AllModeEvent, CompoundEvent, ToolCallEvent
from ai_accounts_core.ids import new_id
from ai_accounts_core.protocols.backend import ChatRequest
from ai_accounts_core.services.chat import ChatService
from ai_accounts_core.services.scheduler import AccountScheduler

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(UTC)


class ChatOrchestrator:
    def __init__(self, *, chat_service: ChatService, scheduler: AccountScheduler) -> None:
        self._chat = chat_service
        self._scheduler = scheduler

    async def send_single(
        self,
        *,
        session_id: str,
        content: str,
        backend_kind: str | None = None,
        account_id: str | None = None,
        model: str | None = None,
    ) -> AsyncIterator[ChatDelta | ToolCallEvent]:
        """Single mode: use ChatService.send_message which already handles credentials."""
        async for event in self._chat.send_message(session_id=session_id, content=content):
            if event.kind == "tool_call":
                yield ToolCallEvent(
                    id=event.tool_id or "",
                    name=event.tool_name,
                    arguments=event.tool_arguments,
                )
            else:
                yield event

    # ── All-mode: parallel fan-out ──

    async def send_all(
        self,
        *,
        session_id: str,
        content: str,
    ) -> AsyncIterator[AllModeEvent]:
        """Fan out to every READY backend in parallel, merging events via a queue."""
        # Persist user message
        user_msg = ChatMessage(
            id=new_id("msg"),
            session_id=session_id,
            role=ChatRole.USER,
            content=content,
            created_at=_now(),
        )
        await self._chat.append_message(user_msg)

        # Build context from history
        history = await self._chat.get_messages(session_id)

        health_list = await self._scheduler.get_all_health()
        ready = list(health_list)
        if not ready:
            yield AllModeEvent(kind="backend_error", backend="none", error="No backends available")
            return

        queue: asyncio.Queue[AllModeEvent | None] = asyncio.Queue()
        tasks: list[asyncio.Task[None]] = []

        async def _call_one(health) -> None:  # noqa: ANN001
            # Use backend_id as key so multiple accounts of the same kind
            # produce distinct streams (not merged under one kind label).
            bid = health.backend_id
            kind = health.kind
            # Resolve a friendly label (display_name / email) for the UI card.
            label: str | None = None
            try:
                bdetail = await self._scheduler._accounts.get(bid)
                label = getattr(bdetail, "display_name", None) or None
            except Exception:
                pass
            try:
                result = await self._scheduler.pick(kind=kind)
                if not result:
                    await queue.put(
                        AllModeEvent(
                            kind="backend_error", backend=bid, backend_kind=kind,
                            account_label=label, error="no account available",
                        ),
                    )
                    return
                impl = self._scheduler._accounts._impl_for(kind)
                # Pick a real model id — passing model="auto" downstream causes
                # CLIProxyAPI to mis-route (it has no "auto" provider mapping)
                # and return 401/429 from a stranger provider's credentials.
                # Use the backend's first advertised model as a sensible default.
                try:
                    models = await impl.list_models(
                        result.credential, isolation_dir=Path(result.isolation_dir)
                    )
                except Exception:
                    models = []
                model_id = models[0].id if models else "auto"
                request = ChatRequest(messages=tuple(history), model=model_id)
                async for event in impl.chat(
                    request, result.credential, isolation_dir=Path(result.isolation_dir),
                ):
                    if event.kind == "token" and isinstance(event.payload, str):
                        await queue.put(AllModeEvent(
                            kind="backend_delta", backend=bid, backend_kind=kind,
                            account_label=label, text=event.payload,
                        ))
                    elif event.kind == "error":
                        await queue.put(AllModeEvent(
                            kind="backend_error", backend=bid, backend_kind=kind,
                            account_label=label, error=str(event.payload),
                        ))
                await queue.put(AllModeEvent(
                    kind="backend_complete", backend=bid, backend_kind=kind, account_label=label,
                ))
            except Exception as exc:
                logger.error("send_all backend %s failed: %s", bid, exc, exc_info=True)
                await queue.put(AllModeEvent(
                    kind="backend_error", backend=bid, backend_kind=kind,
                    account_label=label, error=f"{type(exc).__name__}: {exc}",
                ))

        async def _call_one_with_timeout(health) -> None:  # noqa: ANN001
            """Wrap _call_one with timeout — catch TimeoutError at the outer level."""
            try:
                await asyncio.wait_for(_call_one(health), timeout=30.0)
            except asyncio.TimeoutError:
                await queue.put(AllModeEvent(
                    kind="backend_timeout", backend=health.backend_id,
                    backend_kind=health.kind,
                ))

        for h in ready:
            task = asyncio.create_task(_call_one_with_timeout(h))
            tasks.append(task)

        async def _monitor() -> None:
            for t in tasks:
                try:
                    await t
                except BaseException as exc:
                    logger.warning("fan-out task error: %s", exc, exc_info=True)
            await queue.put(None)  # sentinel MUST be sent no matter what

        monitor_task = asyncio.create_task(_monitor())

        while True:
            event = await queue.get()
            if event is None:
                break
            yield event

        await monitor_task

    # ── Compound-mode: fan-out + synthesis ──

    async def send_compound(
        self,
        *,
        session_id: str,
        content: str,
        primary_kind: str | None = None,
    ) -> AsyncIterator[CompoundEvent]:
        """Fan out to all backends, collect responses, then synthesise via the primary."""
        # Phase 1: fan out (reuse send_all, collect text)
        responses: dict[str, str] = {}
        async for event in self.send_all(session_id=session_id, content=content):
            yield CompoundEvent(
                kind=event.kind, backend=event.backend,
                backend_kind=event.backend_kind, account_label=event.account_label,
                text=event.text, error=event.error,
            )
            if event.kind == "backend_delta" and event.text:
                responses.setdefault(event.backend, "")
                responses[event.backend] += event.text

        if not responses:
            yield CompoundEvent(kind="synthesis_error", error="No backend responses to synthesize")
            return

        # Phase 2: synthesise via primary backend
        # Resolve primary kind — if not specified, look up the kind of the first responder
        if primary_kind:
            primary = primary_kind
        else:
            first_bid = next(iter(responses))
            try:
                first_backend = await self._scheduler._accounts.get(first_bid)
                primary = first_backend.kind
            except Exception as exc:
                logger.exception(
                    "compound synthesis: failed to resolve primary kind from first responder %s",
                    first_bid,
                )
                yield CompoundEvent(
                    kind="synthesis_error",
                    error=f"Could not resolve synthesis backend: {type(exc).__name__}: {exc}",
                )
                return
        yield CompoundEvent(
            kind="synthesis_start",
            primary_backend=primary,
            backends_collected=tuple(responses.keys()),
        )

        synthesis_prompt = "Given these responses from multiple AI backends:\n\n"
        for backend, text in responses.items():
            synthesis_prompt += f"**{backend}:**\n{text}\n\n"
        synthesis_prompt += (
            "Please synthesize a unified, comprehensive response combining the best insights from all."
        )

        result = await self._scheduler.pick(kind=primary)
        if not result:
            yield CompoundEvent(kind="synthesis_error", error=f"No {primary} account for synthesis")
            return

        impl = self._scheduler._accounts._impl_for(primary)
        synth_msg = ChatMessage(
            id=new_id("msg"),
            session_id=session_id,
            role=ChatRole.USER,
            content=synthesis_prompt,
            created_at=_now(),
        )
        # Same model resolution as send_all: synth must hit a real provider.
        try:
            synth_models = await impl.list_models(
                result.credential, isolation_dir=Path(result.isolation_dir)
            )
        except Exception:
            synth_models = []
        synth_model_id = synth_models[0].id if synth_models else "auto"
        synth_request = ChatRequest(messages=(synth_msg,), model=synth_model_id)
        try:
            async for event in impl.chat(
                synth_request, result.credential, isolation_dir=Path(result.isolation_dir),
            ):
                if event.kind == "token" and isinstance(event.payload, str):
                    yield CompoundEvent(kind="synthesis_delta", text=event.payload)
            yield CompoundEvent(kind="synthesis_complete")
        except Exception as exc:
            logger.error("compound synthesis failed for primary=%s: %s", primary, exc, exc_info=True)
            yield CompoundEvent(kind="synthesis_error", error=f"Synthesis failed: {type(exc).__name__}: {exc}")
