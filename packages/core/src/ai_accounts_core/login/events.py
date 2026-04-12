"""Login event types — discriminated union published via SSE during login.

Each subclass is a msgspec.Struct with a ``type`` tag. The ``LoginEvent``
alias is the union Litestar and the TS client decode against.
"""

from __future__ import annotations

import msgspec


class UrlPrompt(msgspec.Struct, tag="url_prompt", tag_field="type"):
    prompt_id: str
    url: str
    user_code: str | None = None


class TextPrompt(msgspec.Struct, tag="text_prompt", tag_field="type"):
    prompt_id: str
    prompt: str
    hidden: bool = False


class StdoutChunk(msgspec.Struct, tag="stdout", tag_field="type"):
    text: str


class ProgressUpdate(msgspec.Struct, tag="progress", tag_field="type"):
    label: str
    percent: int | None = None


class LoginComplete(msgspec.Struct, tag="complete", tag_field="type"):
    account_id: str
    backend_status: str


class LoginFailed(msgspec.Struct, tag="failed", tag_field="type"):
    code: str
    message: str


LoginEvent = (
    UrlPrompt
    | TextPrompt
    | StdoutChunk
    | ProgressUpdate
    | LoginComplete
    | LoginFailed
)


class PromptAnswer(msgspec.Struct):
    """Client→server payload for POST /login/respond."""

    prompt_id: str
    answer: str
