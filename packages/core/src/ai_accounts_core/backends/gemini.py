from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, ClassVar

from ai_accounts_core.domain.backend import DetectResult
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

        exit_code = await self._orchestrator.wait()
        self._done = True
        if success and exit_code == 0:
            yield LoginComplete(account_id="", backend_status="validating")
        else:
            yield LoginFailed(
                code="oauth_device_failed",
                message=f"gemini auth login exited with {exit_code}",
            )

    async def respond(self, answer: PromptAnswer) -> None:
        pass

    async def cancel(self) -> None:
        if self._orchestrator is not None and not self._done:
            await self._orchestrator.terminate()
            await self._orchestrator.wait()
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
        self._answers: asyncio.Queue[PromptAnswer] = asyncio.Queue()
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

        config_path_raw = self._config.get("config_path")
        if config_path_raw:
            gemini_dir = Path(os.path.expanduser(str(config_path_raw))) / ".gemini"
        else:
            gemini_dir = Path.home() / ".gemini"
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
        (gemini_dir / "oauth_creds.json").write_text(json.dumps(creds, indent=2))

        cliproxy_dir = Path.home() / ".cli-proxy-api"
        if cliproxy_dir.exists() and email:
            safe_email = email.replace("/", "_").replace("\\", "_")
            (cliproxy_dir / f"gemini-{safe_email}.json").write_text(json.dumps(creds, indent=2))

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

        answer = await self._answers.get()
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
        await self._answers.put(answer)

    async def cancel(self) -> None:
        self._done = True


class _GeminiApiKeySession(LoginSession):
    def __init__(self) -> None:
        self._sid = f"sess-{uuid.uuid4().hex[:10]}"
        self._answers: asyncio.Queue[PromptAnswer] = asyncio.Queue()
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
        ans = await self._answers.get()
        if not ans.answer:
            self._done = True
            yield LoginFailed(code="invalid_key", message="API key cannot be empty")
            return
        self._done = True
        yield LoginComplete(account_id="", backend_status="validating")

    async def respond(self, answer: PromptAnswer) -> None:
        await self._answers.put(answer)

    async def cancel(self) -> None:
        self._done = True


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
        raise NotImplementedError("chat lands in Phase 3")

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
