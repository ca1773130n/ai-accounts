"""Council mode — a panel of role-playing agents debates a decision.

Adapted from karpathy/llm-council (independent opinions → anonymized
cross-review → chairman synthesis) for *decision-making*: given a question,
a numbered option list, and context, N council members — each a distinct
decision lens backed by one of the user's READY accounts — take positions
and vote, debate each other's anonymized arguments for one or more rebuttal
rounds, and a chairman weighs the transcript into a final decision.

Role→account assignment is round-robin over READY accounts: one account
backs all roles when it's all the user has; with several accounts the roles
spread across them (accounts are usually fewer than roles). Member identity
shown to other members is "Member N (role)" — the backing account/provider
is never revealed, mirroring llm-council's anonymized review stage.

The chairman must answer with a strict JSON object; when it doesn't, the
decision falls back to the members' majority vote so a sloppy chairman
never blocks a verdict.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ai_accounts_core.domain.chat import ChatMessage, ChatRole
from ai_accounts_core.domain.chat_events import CouncilEvent
from ai_accounts_core.ids import new_id
from ai_accounts_core.protocols.backend import ChatRequest

if TYPE_CHECKING:
    from ai_accounts_core.domain.backend import Backend
    from ai_accounts_core.services.accounts import AccountService
    from ai_accounts_core.services.scheduler import AccountScheduler

logger = logging.getLogger(__name__)

# (role, persona) — five decision lenses. Order matters only for round-robin.
_ROLES: tuple[tuple[str, str], ...] = (
    (
        "pragmatist",
        "You optimize for shipping the simplest thing that works now. "
        "Cost, effort, and time-to-done weigh heaviest for you.",
    ),
    (
        "architect",
        "You optimize for long-term design coherence and maintainability. "
        "You ask what each option costs the codebase a year from now.",
    ),
    (
        "risk-analyst",
        "You hunt failure modes: what breaks, what's irreversible, what's "
        "insecure, and which option is easiest to back out of.",
    ),
    (
        "user-advocate",
        "You represent the end user. Which option delivers the most real "
        "value and the least confusion to the person using the result?",
    ),
    (
        "contrarian",
        "You challenge the emerging consensus. Steelman the least popular "
        "option and attack the most popular one's weakest assumption.",
    ),
)

_MEMBER_TIMEOUT_SECONDS = 90.0
_CHAIRMAN_TIMEOUT_SECONDS = 120.0
_MAX_ROUNDS = 5  # hard cap — each round is len(members) real LLM calls
_MAX_OPTIONS = 10
_VOTE_RE = re.compile(r"VOTE:\s*\(?(\d+)", re.IGNORECASE)

_CHAIR_SYSTEM = (
    "You are the impartial chairman of a decision council. You did not take "
    "part in the debate; weigh the members' arguments strictly on their "
    "merits. Respond with ONLY the JSON object requested — no prose."
)


def _exc_text(exc: BaseException) -> str:
    """Human-readable error for member failures (SSE `error` must be a str)."""
    if isinstance(exc, TimeoutError):
        return f"timed out after {_MEMBER_TIMEOUT_SECONDS:.0f}s"
    return f"{type(exc).__name__}: {exc}"


def _now() -> datetime:
    return datetime.now(UTC)


def _parse_vote(text: str, n_options: int) -> int | None:
    """Last `VOTE: n` in the text, when it names a real option."""
    votes = _VOTE_RE.findall(text)
    if not votes:
        return None
    n = int(votes[-1])
    return n if 1 <= n <= n_options else None


def _parse_chair_json(text: str, n_options: int) -> dict[str, Any] | None:
    """Extract the chairman's decision JSON; None when unusable."""
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        raw = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(raw, dict):
        return None
    choice = raw.get("choice")
    if not isinstance(choice, int) or not 1 <= choice <= n_options:
        return None
    return raw


class _Member:
    """One council seat: a role bound to a backing account."""

    def __init__(
        self,
        *,
        index: int,
        role: str,
        persona: str,
        backend: Backend,
        credential: bytes,
        isolation_dir: Path,
        model_id: str,
    ) -> None:
        self.index = index  # 1-based, shown as "Member N"
        self.role = role
        self.persona = persona
        self.backend = backend
        self.credential = credential
        self.isolation_dir = isolation_dir
        self.model_id = model_id
        self.position: str | None = None
        self.vote: int | None = None


class CouncilService:
    """Convene a decision council over the user's READY accounts."""

    def __init__(self, *, account_service: AccountService, scheduler: AccountScheduler) -> None:
        self._accounts = account_service
        self._scheduler = scheduler

    async def convene(
        self,
        *,
        question: str,
        options: list[str],
        context: str = "",
        rounds: int = 1,
    ) -> AsyncIterator[CouncilEvent]:
        """Run the council; yields CouncilEvents ending in decision/council_error."""
        if len(options) < 2:
            yield CouncilEvent(kind="council_error", error="council needs at least two options")
            return
        if len(options) > _MAX_OPTIONS:
            yield CouncilEvent(
                kind="council_error", error=f"council caps at {_MAX_OPTIONS} options"
            )
            return
        # Each round costs len(members) real LLM calls against real quotas —
        # clamp regardless of what the caller sent.
        rounds = min(max(rounds, 0), _MAX_ROUNDS)

        members, roster_errors = await self._seat_members()
        for err in roster_errors:
            yield CouncilEvent(kind="member_error", error=err)
        if not members:
            yield CouncilEvent(
                kind="council_error",
                error="no READY accounts available to seat a council",
            )
            return

        council_id = new_id("cnc")
        yield CouncilEvent(
            kind="council_start",
            payload={
                "council_id": council_id,
                "question": question,
                "options": list(options),
                "rounds": rounds,
                "members": [
                    {
                        "member": m.index,
                        "role": m.role,
                        "account_label": m.backend.display_name,
                        "backend_kind": m.backend.kind,
                    }
                    for m in members
                ],
            },
        )

        # ── Stage 1: independent positions ──
        prompt = self._position_prompt(question, options, context)
        results = await self._ask_all(members, council_id, prompt)
        seated: list[_Member] = []
        for member, outcome in zip(members, results, strict=True):
            if isinstance(outcome, str):
                member.position = outcome
                member.vote = _parse_vote(outcome, len(options))
                seated.append(member)
                yield CouncilEvent(
                    kind="position",
                    role=member.role,
                    backend_kind=member.backend.kind,
                    account_label=member.backend.display_name,
                    text=outcome,
                    option=member.vote,
                )
            else:
                yield CouncilEvent(
                    kind="member_error",
                    role=member.role,
                    backend_kind=member.backend.kind,
                    account_label=member.backend.display_name,
                    error=_exc_text(outcome),
                )
        if len(seated) < 2:
            yield CouncilEvent(
                kind="council_error",
                error="council collapsed: fewer than two members produced a position",
            )
            return
        # Council traffic counts toward the scheduler's last-used bookkeeping.
        for bid in {m.backend.id for m in seated}:
            await self._scheduler.mark_used(bid)

        # ── Stage 2: anonymized rebuttal rounds ──
        for round_no in range(1, max(rounds, 0) + 1):
            transcript = self._anonymized_transcript(seated)
            rebuttals = await self._ask_all(
                seated,
                council_id,
                None,  # per-member prompt built below
                per_member_prompt=self._rebuttal_prompt_for(transcript, question, options),
            )
            for member, outcome in zip(seated, rebuttals, strict=True):
                if isinstance(outcome, str):
                    member.position = outcome
                    new_vote = _parse_vote(outcome, len(options))
                    if new_vote is not None:
                        member.vote = new_vote
                    yield CouncilEvent(
                        kind="rebuttal",
                        role=member.role,
                        backend_kind=member.backend.kind,
                        account_label=member.backend.display_name,
                        round=round_no,
                        text=outcome,
                        option=member.vote,
                    )
                else:
                    # A member dropping mid-debate keeps its stage-1 vote.
                    yield CouncilEvent(
                        kind="member_error",
                        role=member.role,
                        round=round_no,
                        error=_exc_text(outcome),
                    )

        tally: dict[str, int] = {}
        for m in seated:
            if m.vote is not None:
                key = options[m.vote - 1]
                tally[key] = tally.get(key, 0) + 1
        yield CouncilEvent(kind="votes", payload={"tally": tally})

        # ── Stage 3: chairman decision ──
        decision = await self._chair_decision(seated, council_id, question, options, context, tally)
        if decision is None:
            yield CouncilEvent(
                kind="council_error",
                error="no decision: chairman output unusable and no parseable member votes",
            )
            return
        yield CouncilEvent(kind="decision", payload=decision)

    # ── seating ──

    async def _seat_members(self) -> tuple[list[_Member], list[str]]:
        """Round-robin the role list over usable READY accounts.

        Applies the same rate-limit criteria as scheduler.pick() — seating a
        cooling-down or near-exhausted account would spend five debate calls
        pushing it over its limit, the opposite of this package's purpose.
        """
        from ai_accounts_core.services.scheduler import RATE_LIMIT_THRESHOLD

        health = await self._scheduler.get_all_health()
        accounts: list[tuple[Backend, bytes, Path, str]] = []
        errors: list[str] = []
        now = _now()
        for h in health:
            if h.rate_limited_until is not None and h.rate_limited_until > now:
                errors.append(f"{h.backend_id}: rate-limited until {h.rate_limited_until}")
                continue
            if any(w.usage_percent >= RATE_LIMIT_THRESHOLD for w in h.windows):
                errors.append(f"{h.backend_id}: usage above {RATE_LIMIT_THRESHOLD:.0f}%")
                continue
            try:
                backend = await self._accounts.get(h.backend_id)
                repo = await self._accounts._storage.backends()
                stored = await repo.get_credential(h.backend_id)
                if stored is None:
                    errors.append(f"{h.backend_id}: no credential stored")
                    continue
                credential = await self._accounts._decrypt_credential(backend, stored.ciphertext)
                isolation_dir = await self._accounts._resolve_config_dir(h.backend_id)
                impl = self._accounts._impl_for(backend.kind)
                models = await impl.list_models(credential, isolation_dir=isolation_dir)
                if not models:
                    errors.append(f"{backend.display_name} ({backend.kind}): no models available")
                    continue
                accounts.append((backend, credential, isolation_dir, models[0].id))
            except Exception as exc:  # noqa: BLE001 — one bad account must not sink the council
                logger.warning("council: skipping account %s: %r", h.backend_id, exc)
                errors.append(f"{h.backend_id}: {type(exc).__name__}: {exc}")
        if not accounts:
            return [], errors
        members = [
            _Member(
                index=i + 1,
                role=role,
                persona=persona,
                backend=accounts[i % len(accounts)][0],
                credential=accounts[i % len(accounts)][1],
                isolation_dir=accounts[i % len(accounts)][2],
                model_id=accounts[i % len(accounts)][3],
            )
            for i, (role, persona) in enumerate(_ROLES)
        ]
        return members, errors

    # ── member calls ──

    async def _ask_all(
        self,
        members: list[_Member],
        council_id: str,
        prompt: str | None,
        *,
        per_member_prompt: Callable[[_Member], str] | None = None,
    ) -> list[str | BaseException]:
        async def _one(m: _Member) -> str:
            text = per_member_prompt(m) if per_member_prompt else prompt
            assert text is not None
            return await asyncio.wait_for(
                self._chat_once(m, council_id, text), timeout=_MEMBER_TIMEOUT_SECONDS
            )

        return list(await asyncio.gather(*[_one(m) for m in members], return_exceptions=True))

    async def _chat_once(
        self,
        member: _Member,
        council_id: str,
        user_prompt: str,
        *,
        system_text: str | None = None,
    ) -> str:
        """One buffered single-turn call: role persona (or override) as system."""
        impl = self._accounts._impl_for(member.backend.kind)
        system = ChatMessage(
            id=new_id("msg"),
            session_id=council_id,
            role=ChatRole.SYSTEM,
            content=system_text
            or (
                f'You are "{member.role}", one member of a decision council. {member.persona} '
                "The council must choose exactly one numbered option. Argue from your lens, "
                "concretely and in under 200 words. Always end with a final line: "
                "VOTE: <option number>"
            ),
            created_at=_now(),
        )
        user = ChatMessage(
            id=new_id("msg"),
            session_id=council_id,
            role=ChatRole.USER,
            content=user_prompt,
            created_at=_now(),
        )
        request = ChatRequest(messages=(system, user), model=member.model_id)
        chunks: list[str] = []
        async for event in impl.chat(
            request, member.credential, isolation_dir=member.isolation_dir
        ):
            if event.kind == "token" and isinstance(event.payload, str):
                chunks.append(event.payload)
            elif event.kind == "error":
                raise RuntimeError(str(event.payload))
        text = "".join(chunks).strip()
        if not text:
            raise RuntimeError("empty response")
        return text

    # ── prompts ──

    @staticmethod
    def _format_options(options: list[str]) -> str:
        return "\n".join(f"{i}. {opt}" for i, opt in enumerate(options, 1))

    def _position_prompt(self, question: str, options: list[str], context: str) -> str:
        return (
            f"DECISION QUESTION:\n{question}\n\n"
            f"OPTIONS:\n{self._format_options(options)}\n\n"
            f"CONTEXT:\n{context.strip() or '(none provided)'}\n\n"
            "Give your position: which option should the council choose, and why? "
            'End with "VOTE: <option number>".'
        )

    @staticmethod
    def _anonymized_transcript(members: list[_Member]) -> str:
        # Accounts/providers stay hidden — only "Member N (role)" is shown,
        # mirroring llm-council's anonymized cross-review stage.
        parts = []
        for m in members:
            vote = f"voted {m.vote}" if m.vote is not None else "cast no parseable vote"
            parts.append(f"Member {m.index} ({m.role}) {vote}:\n{m.position}")
        return "\n\n".join(parts)

    def _rebuttal_prompt_for(
        self, transcript: str, question: str, options: list[str]
    ) -> Callable[[_Member], str]:
        """Bind the round's transcript so the per-member callable is loop-safe."""

        def _prompt(member: _Member) -> str:
            return self._rebuttal_prompt(member, transcript, question, options)

        return _prompt

    def _rebuttal_prompt(
        self, member: _Member, transcript: str, question: str, options: list[str]
    ) -> str:
        return (
            f"The council is deciding:\n{question}\n\n"
            f"OPTIONS:\n{self._format_options(options)}\n\n"
            f"Positions so far (anonymized):\n\n{transcript}\n\n"
            f"You are Member {member.index} ({member.role}). Rebut what you disagree with, "
            "concede what genuinely convinces you, and give your FINAL vote. "
            'End with "VOTE: <option number>".'
        )

    # ── chairman ──

    async def _chair_decision(
        self,
        members: list[_Member],
        council_id: str,
        question: str,
        options: list[str],
        context: str,
        tally: dict[str, int],
    ) -> dict[str, Any] | None:
        chair = members[0]  # first seat doubles as chairman (llm-council: designated chairman)
        prompt = (
            f"DECISION QUESTION:\n{question}\n\n"
            f"OPTIONS:\n{self._format_options(options)}\n\n"
            f"CONTEXT:\n{context.strip() or '(none provided)'}\n\n"
            f"COUNCIL TRANSCRIPT (final positions):\n\n{self._anonymized_transcript(members)}\n\n"
            f"VOTE TALLY: {json.dumps(tally)}\n\n"
            "You are the council chairman. Weigh the arguments — not merely the votes — and "
            "issue the final decision. Respond with ONLY a JSON object of this exact shape:\n"
            '{"choice": <option number>, "confidence": <0..1>, '
            '"rationale": "<why, citing the strongest arguments>", '
            '"dissent": "<the strongest argument against this choice>"}'
        )
        chair_text: str | None = None
        try:
            chair_text = await asyncio.wait_for(
                self._chat_once(chair, council_id, prompt, system_text=_CHAIR_SYSTEM),
                timeout=_CHAIRMAN_TIMEOUT_SECONDS,
            )
        except Exception as exc:  # noqa: BLE001 — fall back to majority below
            logger.warning("council: chairman call failed: %r", exc)

        parsed = _parse_chair_json(chair_text, len(options)) if chair_text else None
        if parsed is not None:
            choice = int(parsed["choice"])
            return {
                "choice": choice,
                "choice_label": options[choice - 1],
                "confidence": parsed.get("confidence"),
                "rationale": str(parsed.get("rationale") or ""),
                "dissent": str(parsed.get("dissent") or ""),
                "tally": tally,
                "decided_by": "chairman",
            }
        # Fallback: majority of parseable member votes. Ties are broken toward
        # the earlier-listed option — declared, never silent.
        if not tally:
            return None
        top = max(tally.values())
        winners = [label for label in tally if tally[label] == top]
        winners.sort(key=options.index)
        top_label = winners[0]
        tie = len(winners) > 1
        rationale = "chairman output was unusable; decided by member majority vote"
        if tie:
            rationale += (
                f" — TIE between {winners}; broke toward the earlier-listed option. "
                "Treat this decision as weak."
            )
        return {
            "choice": options.index(top_label) + 1,
            "choice_label": top_label,
            "confidence": None,
            "rationale": rationale,
            "dissent": "",
            "tally": tally,
            "decided_by": "tie_fallback" if tie else "majority_fallback",
        }
