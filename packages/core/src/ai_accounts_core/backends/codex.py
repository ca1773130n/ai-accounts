from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
import shutil
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, ClassVar

import httpx

from ai_accounts_core.backends._cliproxy_chat import _chat_via_cliproxy
from ai_accounts_core.domain.backend import DetectResult
from ai_accounts_core.domain.chat import ChatRole
from ai_accounts_core.login import (
    LoginComplete,
    LoginEvent,
    LoginFailed,
    LoginSession,
    PromptAnswer,
    StdoutChunk,
    TextPrompt,
    UrlPrompt,
)
from ai_accounts_core.login.cli_orchestrator import CliOrchestrator
from ai_accounts_core.metadata import (
    BackendMetadata,
    InputSpec,
    InstallCheck,
    LoginFlowSpec,
)
from ai_accounts_core.protocols.backend import (
    ChatRequest,
    ChatStreamEvent,
    Model,
    PtyHandle,
    PtyRequest,
)

# Codex CLI may print auth URLs on either chatgpt.com/auth/... (older) or
# auth.openai.com/... (newer device-code flow). Ported from Agented 78d270c:
# the PTY output detector must catch both hosts so the frontend can auto-open.
_CODEX_URL_RE = re.compile(
    r"https://(?:chatgpt\.com/auth/|auth\.openai\.com/)\S+"
)
# Codex 0.121.0 device-auth prints the code on its own line BELOW the
# "Enter this one-time code" label (e.g. "   3IKX-6ZZWB"). Length is 4-5
# alphanum either side of the dash, so allow {4,8}. The earlier labelled
# regex `code[:\s]+(...)` was matching "code authoriz" from the ALSO-printed
# phrase "device code authorization:" and capturing garbage.
_CODEX_USER_CODE_RE = re.compile(
    r"(?:^|\n)\s*([A-Z0-9]{4,8}-[A-Z0-9]{4,8})\s*$", re.MULTILINE
)
_CODEX_SUCCESS_MARKERS = ("Successfully logged in", "Authentication complete")
_CODEX_FAILURE_MARKERS = ("error:", "failed", "Error")


class _CodexOAuthDeviceSession(LoginSession):
    def __init__(self, isolation_dir: Path) -> None:
        self._sid = f"sess-{uuid.uuid4().hex[:10]}"
        self._isolation_dir = isolation_dir
        self._done = False
        self._orchestrator: CliOrchestrator | None = None
        self._cleanup_lock = asyncio.Lock()

    @property
    def session_id(self) -> str:
        return self._sid

    @property
    def backend_kind(self) -> str:
        return "codex"

    @property
    def flow_kind(self) -> str:
        return "oauth_device"

    @property
    def done(self) -> bool:
        return self._done

    async def _cleanup(self) -> None:
        async with self._cleanup_lock:
            if self._orchestrator is not None:
                try:
                    await self._orchestrator.terminate()
                except Exception:  # pragma: no cover - best-effort
                    pass
                try:
                    exit_code = await asyncio.wait_for(
                        self._orchestrator.wait(), timeout=10
                    )
                except asyncio.TimeoutError:
                    await self._orchestrator.kill()
                    await self._orchestrator.wait()
                except Exception:  # pragma: no cover - best-effort
                    pass

    async def events(self) -> AsyncIterator[LoginEvent]:
        # Codex 0.121.0 emits a device-code URL only when explicitly asked via
        # --device-auth; bare `codex login` uses the local-callback browser flow.
        # CODEX_HOME MUST be absolute — the codex CLI resolves it against its
        # own cwd, and our cwd= chdir would otherwise cause it to look for
        # backend_dirs/<id>/backend_dirs/<id> (doubled relative path).
        iso = self._isolation_dir.resolve()
        iso.mkdir(parents=True, exist_ok=True)
        self._orchestrator = CliOrchestrator(
            argv=["codex", "login", "--device-auth"],
            env={"CODEX_HOME": str(iso)},
            cwd=iso,
        )
        try:
            await self._orchestrator.start()
        except FileNotFoundError:
            self._done = True
            yield LoginFailed(code="cli_not_found", message="codex CLI not installed")
            return

        url: str | None = None
        user_code: str | None = None
        emitted_url_prompt = False
        success = False
        # Codex prints "Enter this one-time code\n   ABCD-EFGH" — the literal
        # word "code" and the code value land in DIFFERENT PTY chunks, so a
        # per-chunk regex misses the user_code. Run the regex against an
        # accumulating buffer (capped) so cross-chunk matches succeed too.
        buffer = ""
        try:
            async for chunk in self._orchestrator.read_output():
                if chunk.strip():
                    yield StdoutChunk(text=chunk)
                buffer += chunk
                if len(buffer) > 8192:
                    buffer = buffer[-8192:]
                if url is None:
                    m = _CODEX_URL_RE.search(buffer)
                    if m:
                        url = m.group(0)
                if user_code is None:
                    m = _CODEX_USER_CODE_RE.search(buffer)
                    if m:
                        user_code = m.group(1)
                if not emitted_url_prompt and url and user_code:
                    emitted_url_prompt = True
                    yield UrlPrompt(prompt_id="device", url=url, user_code=user_code)
                if any(mk in chunk for mk in _CODEX_SUCCESS_MARKERS):
                    success = True
                    break
                lower = chunk.lower()
                if "error" in lower or "failed" in lower or any(
                    mk in chunk for mk in _CODEX_FAILURE_MARKERS
                ):
                    break
        finally:
            await self._cleanup()
            self._done = True

        if success:
            yield LoginComplete(account_id="", backend_status="validating")
        else:
            yield LoginFailed(
                code="oauth_device_failed",
                message="codex login failed",
            )

    async def respond(self, answer: PromptAnswer) -> None:
        pass

    async def cancel(self) -> None:
        await self._cleanup()
        self._done = True


class _CodexCliBrowserSession(LoginSession):
    def __init__(self, isolation_dir: Path) -> None:
        self._sid = f"sess-{uuid.uuid4().hex[:10]}"
        self._isolation_dir = isolation_dir
        self._done = False
        self._orchestrator: CliOrchestrator | None = None
        self._cleanup_lock = asyncio.Lock()

    @property
    def session_id(self) -> str:
        return self._sid

    @property
    def backend_kind(self) -> str:
        return "codex"

    @property
    def flow_kind(self) -> str:
        return "cli_browser"

    @property
    def done(self) -> bool:
        return self._done

    async def _cleanup(self) -> None:
        async with self._cleanup_lock:
            if self._orchestrator is not None:
                try:
                    await self._orchestrator.terminate()
                except Exception:  # pragma: no cover - best-effort
                    pass
                try:
                    exit_code = await asyncio.wait_for(
                        self._orchestrator.wait(), timeout=10
                    )
                except asyncio.TimeoutError:
                    await self._orchestrator.kill()
                    await self._orchestrator.wait()
                except Exception:  # pragma: no cover - best-effort
                    pass

    async def events(self) -> AsyncIterator[LoginEvent]:
        # Codex 0.121.0: `codex login` is the default browser-callback flow.
        # The earlier `codex auth --browser` form does not exist in this CLI.
        # CODEX_HOME MUST be absolute (see _CodexOAuthDeviceSession comment).
        log = logging.getLogger("ai_accounts_core.backends.codex")
        iso = self._isolation_dir.resolve()
        iso.mkdir(parents=True, exist_ok=True)
        self._orchestrator = CliOrchestrator(
            argv=["codex", "login"],
            env={"CODEX_HOME": str(iso)},
            cwd=iso,
        )
        try:
            await self._orchestrator.start()
        except FileNotFoundError:
            self._done = True
            yield LoginFailed(code="cli_not_found", message="codex CLI not installed")
            return

        url_seen = False
        success = False
        captured_chunks: list[str] = []
        exit_reason = "unknown"
        try:
            async for chunk in self._orchestrator.read_output():
                captured_chunks.append(chunk)
                if chunk.strip():
                    yield StdoutChunk(text=chunk)
                if not url_seen:
                    m = _CODEX_URL_RE.search(chunk)
                    if m:
                        url_seen = True
                        log.info("codex login: URL detected, emitting UrlPrompt")
                        yield UrlPrompt(prompt_id="auth", url=m.group(0))
                if any(mk in chunk for mk in _CODEX_SUCCESS_MARKERS):
                    success = True
                    exit_reason = "success_marker"
                    break
                lower = chunk.lower()
                if "error" in lower or "failed" in lower or any(
                    mk in chunk for mk in _CODEX_FAILURE_MARKERS
                ):
                    exit_reason = f"failure_marker_in_chunk: {chunk[:120]!r}"
                    break
            else:
                exit_reason = "EOF (CLI exited cleanly)"
        finally:
            await self._cleanup()
            self._done = True

        if success:
            yield LoginComplete(account_id="", backend_status="validating")
        else:
            log.warning(
                "codex login failed; url_seen=%s exit_reason=%s captured=%r",
                url_seen,
                exit_reason,
                "".join(captured_chunks)[:600],
            )
            yield LoginFailed(
                code="auth_failed",
                message=f"codex login failed ({exit_reason}; url_seen={url_seen})",
            )

    async def respond(self, answer: PromptAnswer) -> None:
        pass

    async def cancel(self) -> None:
        await self._cleanup()
        self._done = True


class _CodexApiKeySession(LoginSession):
    def __init__(self) -> None:
        self._sid = f"sess-{uuid.uuid4().hex[:10]}"
        self._answers: asyncio.Queue[PromptAnswer] = asyncio.Queue(maxsize=1)
        self._done = False
        self._credential: bytes | None = None

    @property
    def credential(self) -> bytes | None:
        return self._credential

    @property
    def session_id(self) -> str:
        return self._sid

    @property
    def backend_kind(self) -> str:
        return "codex"

    @property
    def flow_kind(self) -> str:
        return "api_key"

    @property
    def done(self) -> bool:
        return self._done

    async def events(self) -> AsyncIterator[LoginEvent]:
        yield TextPrompt(prompt_id="api_key", prompt="OpenAI API key", hidden=True)
        try:
            ans = await asyncio.wait_for(self._answers.get(), timeout=300)
        except asyncio.TimeoutError:
            self._done = True
            yield LoginFailed(code="response_timeout", message="No response received within 5 minutes")
            return
        if ans.prompt_id == "__cancel__":
            self._done = True
            yield LoginFailed(code="cancelled", message="Login cancelled")
            return
        if not ans.answer:
            self._done = True
            yield LoginFailed(code="invalid_key", message="API key cannot be empty")
            return
        self._credential = ans.answer.encode("utf-8")
        self._done = True
        yield LoginComplete(account_id="", backend_status="validating")

    async def respond(self, answer: PromptAnswer) -> None:
        if self._done:
            return
        await self._answers.put(answer)

    async def cancel(self) -> None:
        self._done = True
        with contextlib.suppress(asyncio.QueueFull):
            self._answers.put_nowait(PromptAnswer(prompt_id="__cancel__", answer=""))


class CodexBackend:
    kind: ClassVar[str] = "codex"
    _CLI_NAME: ClassVar[str] = "codex"
    _ISOLATION_ENV_VAR: ClassVar[str] = "CODEX_HOME"
    _API_KEY_ENV_VAR: ClassVar[str] = "OPENAI_API_KEY"
    # NOTE: cli_browser flow (`codex login`) is implemented but NOT advertised
    # because Codex 0.121.0's local-callback server (localhost:1455) only
    # works when the codex subprocess survives the user's tab-switching to
    # complete OAuth in the browser, AND the wizard's SSE stream keeps the
    # subprocess alive that long. In practice the callback often fails. The
    # device-auth flow is much more reliable: codex prints a URL + code, the
    # user signs in and enters the code, no localhost server required.
    supported_login_flows: ClassVar[frozenset[str]] = frozenset(
        {"api_key", "oauth_device"}
    )

    metadata: ClassVar[BackendMetadata] = BackendMetadata(
        kind="codex",
        display_name="Codex",
        icon_url=None,
        install_check=InstallCheck(
            command=["codex", "--version"],
            version_regex=r"(\d+\.\d+\.\d+)",
        ),
        login_flows=[
            LoginFlowSpec(
                kind="oauth_device",
                display_name="Sign in with OpenAI",
                description="Sign in via a device code — codex prints a URL and code",
                requires_inputs=[],
            ),
            LoginFlowSpec(
                kind="api_key",
                display_name="API key",
                description="Paste an OpenAI API key",
                requires_inputs=[InputSpec(name="api_key", label="API key", kind="secret")],
            ),
        ],
        plan_options=None,
        config_schema={
            "type": "object",
            "properties": {
                "email": {"type": "string"},
                "config_path": {"type": "string"},
            },
        },
        supports_multi_account=True,
        isolation_env_var="CODEX_HOME",
    )

    def begin_login(
        self,
        flow_kind: str,
        config: dict,
        vault_ctx: dict,
        isolation_dir: Path,
    ) -> LoginSession:
        if flow_kind == "oauth_device":
            return _CodexOAuthDeviceSession(isolation_dir)
        if flow_kind == "cli_browser":
            return _CodexCliBrowserSession(isolation_dir)
        if flow_kind == "api_key":
            return _CodexApiKeySession()
        raise ValueError(f"unsupported flow_kind: {flow_kind}")

    async def detect(self) -> DetectResult:
        path = shutil.which(self._CLI_NAME)
        if path is None:
            return DetectResult(installed=False)
        rc, stdout, _stderr = await self._run({"argv": [path, "--version"]})
        if rc != 0:
            return DetectResult(installed=True, path=path, notes="version check failed")
        version = None
        if stdout:
            first_line = stdout.decode(errors="replace").strip().splitlines()[0]
            version = first_line or None
        return DetectResult(installed=True, version=version, path=path)

    async def validate(
        self, credential: bytes, *, isolation_dir: Path
    ) -> bool:
        path = shutil.which(self._CLI_NAME)
        if path is None:
            return False
        # Codex 0.121.0 uses `codex login status` (no top-level `auth` subcommand).
        # CODEX_HOME must be absolute — codex resolves it against its own cwd
        # and our subprocess cwd defaults to the parent's, doubling the path.
        # NOTE: `codex login status` exits 0 even when "Not logged in" — must
        # inspect output text to distinguish actual auth from a missing session.
        # Codex 0.128.0 routes the status line ("Logged in using ChatGPT") to
        # STDERR, not stdout. Check both streams so this works on 0.121.0
        # (stdout) and 0.128.0+ (stderr).
        iso = isolation_dir.resolve()
        env = self._env(credential, iso)
        rc, stdout, stderr = await self._run(
            {"argv": [path, "login", "status"], "env": env}
        )
        if rc != 0:
            return False
        out_text = stdout.decode("utf-8", errors="replace").lower()
        err_text = stderr.decode("utf-8", errors="replace").lower()
        text = f"{out_text}\n{err_text}"
        return "logged in" in text and "not logged in" not in text

    async def list_models(
        self, credential: bytes, *, isolation_dir: Path
    ) -> list[Model]:
        # Prefer live discovery from CLIProxyAPI when registered (single
        # source of truth for which model ids round-trip through
        # /v1/chat/completions). Falls back to the static set when cliproxy
        # isn't running. Codex CLI 0.128.0 has no `models list` subcommand,
        # so the static list matches what cliproxyapi 6.8.30 advertises for
        # the openai provider — kept around for offline/test environments.
        from ai_accounts_core.cliproxy import cliproxy_list_models

        live = await cliproxy_list_models("codex")
        if live:
            return [
                Model(
                    id=str(m["id"]),
                    display_name=str(m.get("display_name") or m["id"]),
                    context_window=m.get("context_window"),
                )
                for m in live
            ]
        return [
            Model(id="gpt-5.3-codex", display_name="GPT-5.3 Codex", context_window=400_000),
            Model(id="gpt-5.3-codex-spark", display_name="GPT-5.3 Codex Spark", context_window=400_000),
            Model(id="gpt-5.2-codex", display_name="GPT-5.2 Codex", context_window=400_000),
            Model(id="gpt-5.1-codex-max", display_name="GPT-5.1 Codex Max", context_window=400_000),
            Model(id="gpt-5.1-codex-mini", display_name="GPT-5.1 Codex Mini", context_window=400_000),
            Model(id="gpt-5-codex", display_name="GPT-5 Codex", context_window=400_000),
            Model(id="gpt-5-codex-mini", display_name="GPT-5 Codex Mini", context_window=400_000),
            Model(id="gpt-5.2", display_name="GPT-5.2", context_window=400_000),
            Model(id="gpt-5.1", display_name="GPT-5.1", context_window=400_000),
            Model(id="gpt-5", display_name="GPT-5", context_window=400_000),
        ]

    async def get_usage(self, credential: bytes, *, isolation_dir: Path) -> list:
        from ai_accounts_core.domain.usage import UsageWindow

        api_key = credential.decode("utf-8").strip()
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    "https://chatgpt.com/backend-api/wham/usage",
                    headers={"Authorization": f"Bearer {api_key}"},
                    timeout=15.0,
                )
                if resp.status_code != 200:
                    return []
                data = resp.json()
                windows = []
                for rl in data.get("rate_limits", []):
                    for key in ("primary_window", "secondary_window"):
                        w = rl.get(key)
                        if w:
                            resets_at = None
                            if w.get("reset_at"):
                                from datetime import UTC, datetime

                                resets_at = datetime.fromtimestamp(
                                    w["reset_at"], tz=UTC
                                )
                            windows.append(
                                UsageWindow(
                                    window_type=key,
                                    usage_percent=w.get("used_percent", 0.0),
                                    resets_at=resets_at,
                                )
                            )
                return windows
        except (httpx.HTTPError, ValueError, KeyError, OSError) as exc:
            logging.getLogger(__name__).debug("codex get_usage failed: %r", exc)
            return []

    async def chat(
        self,
        request: ChatRequest,
        credential: bytes,
        *,
        isolation_dir: Path,
    ) -> AsyncIterator[ChatStreamEvent]:
        api_key = credential.decode("utf-8").strip()
        if not api_key:
            async for event in _chat_via_cliproxy(request):
                yield event
            return
        messages_payload = [
            {"role": m.role.value, "content": m.content}
            for m in request.messages
        ]
        body: dict[str, object] = {
            "model": request.model,
            "messages": messages_payload,
            "stream": True,
        }
        if "max_tokens" in request.params:
            body["max_tokens"] = request.params["max_tokens"]
        async with httpx.AsyncClient() as client:
            async with client.stream(
                "POST",
                "https://api.openai.com/v1/chat/completions",
                json=body,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                timeout=120.0,
            ) as resp:
                if resp.status_code != 200:
                    yield ChatStreamEvent(
                        kind="error",
                        payload=f"API error {resp.status_code}",
                    )
                    return
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    payload = line[6:].strip()
                    if payload == "[DONE]":
                        break
                    data = json.loads(payload)
                    choice = data.get("choices", [{}])[0]
                    delta = choice.get("delta", {})
                    text = delta.get("content")
                    if text:
                        yield ChatStreamEvent(kind="token", payload=text)
                    finish_reason = choice.get("finish_reason")
                    if finish_reason:
                        yield ChatStreamEvent(
                            kind="done",
                            payload={
                                "finish_reason": finish_reason,
                                "model": data.get("model", request.model),
                            },
                        )

    async def pty(
        self,
        request: PtyRequest,
        credential: bytes,
        *,
        isolation_dir: Path,
    ) -> PtyHandle:
        from ai_accounts_core.pty.handle import AsyncPtyHandle

        env = dict(request.env)
        env.update(self._env(credential, isolation_dir))
        return await AsyncPtyHandle.spawn(
            command=request.command, cols=request.cols, rows=request.rows, env=env,
        )

    def _env(self, credential: bytes, isolation_dir: Path) -> dict[str, str]:
        isolation_dir.mkdir(parents=True, exist_ok=True)
        env = {**os.environ, self._ISOLATION_ENV_VAR: str(isolation_dir)}
        if credential:
            env[self._API_KEY_ENV_VAR] = credential.decode()
        return env

    async def _run(self, spec: dict[str, Any]) -> tuple[int, bytes, bytes]:
        argv = spec["argv"]
        env = spec.get("env")
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        stdout, stderr = await proc.communicate()
        return proc.returncode or 0, stdout, stderr
