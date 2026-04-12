from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import shutil
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, ClassVar

import httpx

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

def _validate_config_path(config_path: str | None, isolation_dir: Path) -> Path:
    """Validate config_path is safe. Returns the resolved gemini config dir."""
    if not config_path:
        return Path.home() / ".gemini"
    expanded = Path(os.path.expanduser(str(config_path)))
    resolved = expanded.resolve()
    # Must not escape outside home or isolation directory
    allowed_roots = (Path.home().resolve(), isolation_dir.resolve())
    if not any(str(resolved).startswith(str(root)) for root in allowed_roots):
        raise ValueError(f"config_path '{config_path}' resolves outside allowed directories")
    return resolved / ".gemini"


_GEMINI_URL_RE = re.compile(r"https://accounts\.google\.com/o/oauth2/device/\S+")
_GEMINI_USER_CODE_RE = re.compile(r"([A-Z0-9]{4}-[A-Z0-9]{4})")
_GEMINI_SUCCESS_MARKERS = ("Login successful", "Authenticated")
_GEMINI_FAILURE_MARKERS = ("error:", "failed")


class _GeminiOAuthDeviceSession(LoginSession):
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
        return "gemini"

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
        self._orchestrator = CliOrchestrator(
            argv=["gemini", "auth", "login", "--device"],
            env={"GEMINI_CLI_HOME": str(self._isolation_dir)},
            cwd=self._isolation_dir,
        )
        try:
            await self._orchestrator.start()
        except FileNotFoundError:
            self._done = True
            yield LoginFailed(code="cli_not_found", message="gemini CLI not installed")
            return

        url: str | None = None
        user_code: str | None = None
        emitted_url_prompt = False
        success = False
        try:
            async for chunk in self._orchestrator.read_output():
                if chunk.strip():
                    yield StdoutChunk(text=chunk)
                if url is None:
                    m = _GEMINI_URL_RE.search(chunk)
                    if m:
                        url = m.group(0)
                if user_code is None:
                    m = _GEMINI_USER_CODE_RE.search(chunk)
                    if m:
                        user_code = m.group(1)
                if not emitted_url_prompt and url and user_code:
                    emitted_url_prompt = True
                    yield UrlPrompt(prompt_id="device", url=url, user_code=user_code)
                if any(mk in chunk for mk in _GEMINI_SUCCESS_MARKERS):
                    success = True
                    break
                lower = chunk.lower()
                if "error" in lower or "failed" in lower or any(
                    mk in chunk for mk in _GEMINI_FAILURE_MARKERS
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
                message="gemini auth login failed",
            )

    async def respond(self, answer: PromptAnswer) -> None:
        pass

    async def cancel(self) -> None:
        await self._cleanup()
        self._done = True


class _GeminiDirectOAuthSession(LoginSession):
    """Direct Google OAuth flow using PKCE — bypasses Gemini CLI's broken TUI auth.

    Emits a UrlPrompt with the Google consent URL, awaits the user's auth code
    as a TextPrompt response, exchanges for tokens via oauth2.googleapis.com,
    and writes the credentials to ~/.gemini/oauth_creds.json (+ optionally
    ~/.cli-proxy-api/gemini-<email>.json).
    """

    _CLIENT_ID = "681255809395-oo8ft2oprdrnp9e3aqf6av3hmdib135j.apps.googleusercontent.com"
    _REDIRECT_URI = "https://codeassist.google.com/authcode"
    _SCOPES = " ".join(
        [
            "https://www.googleapis.com/auth/cloud-platform",
            "https://www.googleapis.com/auth/userinfo.email",
            "https://www.googleapis.com/auth/userinfo.profile",
        ]
    )

    def __init__(self, config: dict, isolation_dir: Path) -> None:
        self._sid = f"sess-{uuid.uuid4().hex[:10]}"
        self._config = config
        self._isolation_dir = isolation_dir
        self._answers: asyncio.Queue[PromptAnswer] = asyncio.Queue(maxsize=1)
        self._done = False
        self._state: str | None = None
        self._code_verifier: str | None = None

    @property
    def session_id(self) -> str:
        return self._sid

    @property
    def backend_kind(self) -> str:
        return "gemini"

    @property
    def flow_kind(self) -> str:
        return "direct_oauth"

    @property
    def done(self) -> bool:
        return self._done

    def _build_oauth_url(self) -> str:
        import base64
        import hashlib
        import secrets
        from urllib.parse import urlencode

        self._code_verifier = secrets.token_urlsafe(64)
        code_challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(self._code_verifier.encode()).digest())
            .decode()
            .rstrip("=")
        )
        self._state = secrets.token_hex(32)

        return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(
            {
                "client_id": self._CLIENT_ID,
                "redirect_uri": self._REDIRECT_URI,
                "response_type": "code",
                "scope": self._SCOPES,
                "access_type": "offline",
                "code_challenge_method": "S256",
                "code_challenge": code_challenge,
                "state": self._state,
                "prompt": "consent",
            }
        )

    async def _exchange_code(self, auth_code: str) -> dict:
        import httpx

        async with httpx.AsyncClient(timeout=15.0) as http:
            resp = await http.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "code": auth_code,
                    "client_id": self._CLIENT_ID,
                    "redirect_uri": self._REDIRECT_URI,
                    "grant_type": "authorization_code",
                    "code_verifier": self._code_verifier or "",
                },
            )
        if resp.status_code != 200:
            ct = resp.headers.get("content-type", "")
            if ct.startswith("application/json"):
                err = resp.json().get("error_description") or resp.json().get("error")
            else:
                err = resp.text[:200]
            raise RuntimeError(f"token exchange failed: {err}")
        return resp.json()

    def _write_credentials(self, tokens: dict) -> None:
        import time

        email = str(self._config.get("email", ""))

        gemini_dir = _validate_config_path(
            self._config.get("config_path"),
            self._isolation_dir,
        )
        gemini_dir.mkdir(parents=True, exist_ok=True)

        expiry_ms = int(time.time() * 1000) + int(tokens.get("expires_in", 3600)) * 1000

        creds = {
            "access_token": tokens.get("access_token", ""),
            "refresh_token": tokens.get("refresh_token", ""),
            "scope": self._SCOPES,
            "token_type": tokens.get("token_type", "Bearer"),
            "id_token": tokens.get("id_token", ""),
            "expiry_date": expiry_ms,
        }
        creds_file = gemini_dir / "oauth_creds.json"
        creds_file.write_text(json.dumps(creds, indent=2))
        os.chmod(creds_file, 0o600)

        cliproxy_dir = Path.home() / ".cli-proxy-api"
        if cliproxy_dir.exists() and email:
            safe_email = email.replace("/", "_").replace("\\", "_").replace("..", "_")
            proxy_file = cliproxy_dir / f"gemini-{safe_email}.json"
            proxy_file.write_text(json.dumps(creds, indent=2))
            os.chmod(proxy_file, 0o600)

    async def events(self) -> AsyncIterator[LoginEvent]:
        try:
            oauth_url = self._build_oauth_url()
        except Exception as exc:
            self._done = True
            yield LoginFailed(code="pkce_init_failed", message=str(exc))
            return

        yield UrlPrompt(prompt_id="oauth", url=oauth_url)
        yield TextPrompt(
            prompt_id="auth_code",
            prompt="Paste the authorization code from Google",
            hidden=False,
        )

        try:
            answer = await asyncio.wait_for(self._answers.get(), timeout=300)
        except asyncio.TimeoutError:
            self._done = True
            yield LoginFailed(code="response_timeout", message="No response received within 5 minutes")
            return
        if answer.prompt_id == "__cancel__":
            self._done = True
            yield LoginFailed(code="cancelled", message="Login cancelled")
            return
        auth_code = answer.answer.strip()
        if not auth_code:
            self._done = True
            yield LoginFailed(code="empty_code", message="Authorization code cannot be empty")
            return

        try:
            tokens = await self._exchange_code(auth_code)
        except Exception as exc:
            self._done = True
            yield LoginFailed(code="token_exchange_failed", message=str(exc))
            return

        try:
            self._write_credentials(tokens)
        except Exception as exc:
            self._done = True
            yield LoginFailed(code="credential_write_failed", message=str(exc))
            return

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


class _GeminiApiKeySession(LoginSession):
    def __init__(self) -> None:
        self._sid = f"sess-{uuid.uuid4().hex[:10]}"
        self._answers: asyncio.Queue[PromptAnswer] = asyncio.Queue(maxsize=1)
        self._done = False

    @property
    def session_id(self) -> str:
        return self._sid

    @property
    def backend_kind(self) -> str:
        return "gemini"

    @property
    def flow_kind(self) -> str:
        return "api_key"

    @property
    def done(self) -> bool:
        return self._done

    async def events(self) -> AsyncIterator[LoginEvent]:
        yield TextPrompt(prompt_id="api_key", prompt="Google AI Studio API key", hidden=True)
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


class GeminiBackend:
    kind: ClassVar[str] = "gemini"
    _CLI_NAME: ClassVar[str] = "gemini"
    _ISOLATION_ENV_VAR: ClassVar[str] = "GEMINI_CLI_HOME"
    _API_KEY_ENV_VAR: ClassVar[str] = "GEMINI_API_KEY"
    supported_login_flows: ClassVar[frozenset[str]] = frozenset(
        {"api_key", "oauth_device", "direct_oauth"}
    )

    metadata: ClassVar[BackendMetadata] = BackendMetadata(
        kind="gemini",
        display_name="Gemini",
        icon_url=None,
        install_check=InstallCheck(
            command=["gemini", "--version"],
            version_regex=r"(\d+\.\d+\.\d+)",
        ),
        login_flows=[
            LoginFlowSpec(
                kind="oauth_device",
                display_name="Sign in with Google",
                description="Sign in via Google device flow",
                requires_inputs=[],
            ),
            LoginFlowSpec(
                kind="direct_oauth",
                display_name="Sign in with Google (direct)",
                description="Paste a Google OAuth code from the Code Assist page",
                requires_inputs=[],
            ),
            LoginFlowSpec(
                kind="api_key",
                display_name="API key",
                description="Paste a Google AI Studio API key",
                requires_inputs=[InputSpec(name="api_key", label="API key", kind="secret")],
            ),
        ],
        plan_options=None,
        config_schema={
            "type": "object",
            "properties": {
                "email": {"type": "string"},
            },
        },
        supports_multi_account=True,
        isolation_env_var="GEMINI_CLI_HOME",
    )

    def begin_login(
        self,
        flow_kind: str,
        config: dict,
        vault_ctx: dict,
        isolation_dir: Path,
    ) -> LoginSession:
        if flow_kind == "oauth_device":
            return _GeminiOAuthDeviceSession(isolation_dir)
        if flow_kind == "direct_oauth":
            return _GeminiDirectOAuthSession(config, isolation_dir)
        if flow_kind == "api_key":
            return _GeminiApiKeySession()
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
        env = self._env(credential, isolation_dir)
        rc, _stdout, _stderr = await self._run(
            {"argv": [path, "auth", "status"], "env": env}
        )
        return rc == 0

    async def list_models(
        self, credential: bytes, *, isolation_dir: Path
    ) -> list[Model]:
        path = shutil.which(self._CLI_NAME)
        if path is None:
            return []
        env = self._env(credential, isolation_dir)
        rc, stdout, _stderr = await self._run(
            {"argv": [path, "models", "list", "--json"], "env": env}
        )
        if rc != 0:
            return []
        try:
            raw = json.loads(stdout)
        except json.JSONDecodeError:
            return []
        return [
            Model(
                id=item["id"],
                display_name=item.get("display_name", item["id"]),
                context_window=item.get("context_window"),
            )
            for item in raw
        ]

    async def chat(
        self,
        request: ChatRequest,
        credential: bytes,
        *,
        isolation_dir: Path,
    ) -> AsyncIterator[ChatStreamEvent]:
        api_key = credential.decode("utf-8").strip()
        contents = []
        for m in request.messages:
            if m.role == ChatRole.SYSTEM:
                continue
            role = "model" if m.role == ChatRole.ASSISTANT else "user"
            contents.append({"role": role, "parts": [{"text": m.content}]})
        body: dict[str, object] = {"contents": contents}
        system_msgs = [
            m.content for m in request.messages if m.role == ChatRole.SYSTEM
        ]
        if system_msgs:
            body["system_instruction"] = {"parts": [{"text": system_msgs[0]}]}
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{request.model}:streamGenerateContent?alt=sse&key={api_key}"
        )
        async with httpx.AsyncClient() as client:
            async with client.stream(
                "POST",
                url,
                json=body,
                headers={"Content-Type": "application/json"},
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
                    data = json.loads(line[6:])
                    candidates = data.get("candidates", [])
                    if not candidates:
                        continue
                    candidate = candidates[0]
                    parts = candidate.get("content", {}).get("parts", [])
                    if parts:
                        text = parts[0].get("text", "")
                        if text:
                            yield ChatStreamEvent(
                                kind="token", payload=text
                            )
                    finish_reason = candidate.get("finishReason")
                    if finish_reason:
                        yield ChatStreamEvent(
                            kind="done",
                            payload={
                                "finish_reason": finish_reason,
                                "model": request.model,
                            },
                        )

    async def pty(
        self,
        request: PtyRequest,
        credential: bytes,
        *,
        isolation_dir: Path,
    ) -> PtyHandle:
        raise NotImplementedError("pty lands in Phase 4")

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
