import type { paths } from './generated';
import { parseSseLoginEvents } from './login-stream';
import { parseSseChatEvents } from './chat-stream';
import { parseSseSmartChatEvents } from './smart-chat-stream';
import type { LoginEvent, LoginFlowKind } from '../types/login';
import type { SmartChatEvent, SendChatRequest, ChatMode } from '../types/smart-chat';
import type { BackendMetadata } from '../types/metadata';
import type {
  InstallResult,
  CliproxyStatus,
  CliproxyInstallResult,
  CliproxyLoginBeginResponse,
  CliproxyCallbackForwardResponse,
  CliproxyLoginStatus,
} from '../types/install';
import type { ChatSessionDTO, ChatSessionDetailDTO, ChatDelta } from '../types/chat';
import type { AccountHealthDTO, PickResultDTO, FallbackChainEntryDTO } from '../types/scheduler';

export type { paths } from './generated';

export interface BackendDTO {
  id: string;
  kind: string;
  display_name: string;
  status: string;
  config: Record<string, unknown>;
  config_dir: string | null;
  last_error: string | null;
}

export interface DetectResultDTO {
  installed: boolean;
  version: string | null;
  path: string | null;
  notes: string | null;
}

export interface OAuthDeviceLoginDTO {
  verification_uri: string;
  user_code: string;
  expires_at: string; // ISO 8601 datetime
  handle: string;
}

export interface LoginResponseDTO {
  kind: 'complete' | 'pending';
  backend: BackendDTO | null;
  oauth: OAuthDeviceLoginDTO | null;
}

export interface OnboardingStateDTO {
  id: string;
  current_step: 'welcome' | 'detect' | 'pick_backend' | 'login' | 'validate' | 'done';
  selected_backend_kind: string | null;
  created_backend_id: string | null;
  error: string | null;
}

export interface DetectResultsDTO {
  results: Record<string, DetectResultDTO>;
}

export interface ClientOptions {
  baseUrl: string;
  /**
   * Bearer token sent on every authenticated request.  May be a string
   * (captured once) or a getter (re-read per request).  Use the getter
   * form when the token is sourced from a place that can change after
   * the client is constructed — e.g. ``localStorage`` after the user
   * generates an admin key on the welcome page; capturing at
   * construction would leave the client permanently unauthenticated
   * because the key didn't exist yet when the Vue app booted.
   */
  token?: string | (() => string | undefined | null);
  fetch?: typeof fetch;
}

export interface ApiError extends Error {
  code: string;
  status: number;
}

async function toError(r: Response): Promise<ApiError> {
  let code = 'http_error';
  let message = r.statusText;
  try {
    const body = (await r.json()) as { error?: { code?: string; message?: string } };
    if (body.error) {
      code = body.error.code ?? code;
      message = body.error.message ?? message;
    }
  } catch {
    // non-JSON body or empty — stick with statusText
  }
  const err = new Error(message) as ApiError;
  err.code = code;
  err.status = r.status;
  return err;
}

export class AiAccountsClient {
  private readonly baseUrl: string;
  private readonly _resolveToken: () => string | undefined | null;
  private readonly _fetch: typeof fetch;

  constructor(opts: ClientOptions) {
    this.baseUrl = opts.baseUrl.replace(/\/$/, '');
    // Normalize ``token`` to a getter so authenticated requests pick up
    // the current value on every call. Static-string callers still work.
    if (typeof opts.token === 'function') {
      this._resolveToken = opts.token;
    } else {
      const captured = opts.token;
      this._resolveToken = () => captured;
    }
    // Bind to globalThis so the global `fetch` retains its Window/ServiceWorker
    // context when called as a method via `this._fetch(...)`. Without this,
    // browsers throw "Illegal invocation". A caller-supplied fetch is assumed
    // to already be bound correctly, so we only wrap the default.
    if (opts.fetch) {
      this._fetch = opts.fetch;
    } else {
      this._fetch = (input, init) => fetch(input, init);
    }
    // paths is imported for type-checking — proves generated file exists and compiles.
    // Re-exported above for consumer use.
    void (null as unknown as paths);
  }

  private get token(): string | undefined {
    const t = this._resolveToken();
    return t == null ? undefined : t;
  }

  private headers(): Record<string, string> {
    const h: Record<string, string> = { 'content-type': 'application/json' };
    if (this.token) h['authorization'] = `Bearer ${this.token}`;
    return h;
  }

  async listBackends(): Promise<{ items: BackendDTO[] }> {
    const r = await this._fetch(`${this.baseUrl}/api/v1/backends/`, {
      headers: this.headers(),
    });
    if (!r.ok) throw await toError(r);
    return (await r.json()) as { items: BackendDTO[] };
  }

  async createBackend(input: {
    kind: string;
    display_name: string;
    config?: Record<string, unknown>;
  }): Promise<BackendDTO> {
    const r = await this._fetch(`${this.baseUrl}/api/v1/backends/`, {
      method: 'POST',
      headers: this.headers(),
      body: JSON.stringify({ config: {}, ...input }),
    });
    if (!r.ok) throw await toError(r);
    return (await r.json()) as BackendDTO;
  }

  async getBackend(id: string): Promise<BackendDTO> {
    const r = await this._fetch(
      `${this.baseUrl}/api/v1/backends/${encodeURIComponent(id)}`,
      { headers: this.headers() }
    );
    if (!r.ok) throw await toError(r);
    return (await r.json()) as BackendDTO;
  }

  async deleteBackend(id: string): Promise<void> {
    const r = await this._fetch(
      `${this.baseUrl}/api/v1/backends/${encodeURIComponent(id)}`,
      { method: 'DELETE', headers: this.headers() }
    );
    if (!r.ok) throw await toError(r);
  }

  async updateBackend(
    id: string,
    patch: { display_name?: string; config?: Record<string, unknown> }
  ): Promise<BackendDTO> {
    const r = await this._fetch(
      `${this.baseUrl}/api/v1/backends/${encodeURIComponent(id)}`,
      {
        method: 'PATCH',
        headers: this.headers(),
        body: JSON.stringify(patch),
      }
    );
    if (!r.ok) throw await toError(r);
    return (await r.json()) as BackendDTO;
  }

  async detectBackend(id: string): Promise<DetectResultDTO> {
    return this.postAction<DetectResultDTO>(id, 'detect');
  }

  async loginBackend(
    id: string,
    flowKind: string,
    inputs: Record<string, string>
  ): Promise<LoginResponseDTO> {
    return this.postAction<LoginResponseDTO>(id, 'login', { flow_kind: flowKind, inputs });
  }

  async pollBackendLogin(id: string, handle: string): Promise<LoginResponseDTO> {
    const r = await this._fetch(
      `${this.baseUrl}/api/v1/backends/${encodeURIComponent(id)}/login/poll`,
      {
        method: 'POST',
        headers: this.headers(),
        body: JSON.stringify({ handle }),
      }
    );
    if (!r.ok) throw await toError(r);
    return (await r.json()) as LoginResponseDTO;
  }

  async validateBackend(id: string): Promise<BackendDTO> {
    return this.postAction<BackendDTO>(id, 'validate');
  }

  async beginLogin(
    accountId: string,
    flowKind: LoginFlowKind,
    inputs: Record<string, string>
  ): Promise<{ session_id: string }> {
    const r = await this._fetch(
      `${this.baseUrl}/api/v1/backends/${encodeURIComponent(accountId)}/login/begin`,
      {
        method: 'POST',
        headers: this.headers(),
        body: JSON.stringify({ flow_kind: flowKind, inputs }),
      }
    );
    if (!r.ok) throw await toError(r);
    return (await r.json()) as { session_id: string };
  }

  async respondLogin(
    accountId: string,
    sessionId: string,
    promptId: string,
    answer: string
  ): Promise<void> {
    const r = await this._fetch(
      `${this.baseUrl}/api/v1/backends/${encodeURIComponent(accountId)}/login/respond`,
      {
        method: 'POST',
        headers: this.headers(),
        body: JSON.stringify({ session_id: sessionId, prompt_id: promptId, answer }),
      }
    );
    if (!r.ok) throw await toError(r);
  }

  /**
   * Write arbitrary text to the CLI's stdin during an in-flight login
   * session. Unlike respondLogin, this does NOT require an active
   * textPrompt — used by the AccountWizard's eager paste-code form,
   * which lets users submit the OAuth code before the CLI has emitted
   * its own "Paste code here if prompted >" text prompt.
   */
  async writeEagerLogin(
    accountId: string,
    sessionId: string,
    text: string
  ): Promise<void> {
    const r = await this._fetch(
      `${this.baseUrl}/api/v1/backends/${encodeURIComponent(accountId)}/login/write`,
      {
        method: 'POST',
        headers: this.headers(),
        body: JSON.stringify({ session_id: sessionId, text }),
      }
    );
    if (!r.ok) throw await toError(r);
  }

  async cancelLogin(accountId: string, sessionId: string): Promise<void> {
    const r = await this._fetch(
      `${this.baseUrl}/api/v1/backends/${encodeURIComponent(accountId)}/login/cancel`,
      {
        method: 'POST',
        headers: this.headers(),
        body: JSON.stringify({ session_id: sessionId }),
      }
    );
    if (!r.ok) throw await toError(r);
  }

  async *streamLogin(
    accountId: string,
    sessionId: string
  ): AsyncIterable<LoginEvent> {
    const url = `${this.baseUrl}/api/v1/backends/${encodeURIComponent(accountId)}/login/stream?session_id=${encodeURIComponent(sessionId)}`;
    const headers: Record<string, string> = { Accept: 'text/event-stream' };
    if (this.token) headers['authorization'] = `Bearer ${this.token}`;
    const r = await this._fetch(url, { method: 'GET', headers });
    if (!r.ok) throw await toError(r);
    yield* parseSseLoginEvents(r);
  }

  async discoverConfigs(): Promise<{
    items: Array<{
      kind: string;
      path: string;
      suggested_name: string;
      is_logged_in: boolean;
      error: string | null;
      // Set when the path is already an imported backend — the server
      // has already synced that backend's status to is_logged_in.
      backend_id: string | null;
    }>;
  }> {
    // Probes real CLI prompts ("claude -p hello") against each glob match
    // AND each already-imported account, so stale "ready" statuses (token
    // expiry, manual logout, etc.) surface in the same call. Can take up
    // to ~12s per candidate (parallelized); user-triggered.
    const r = await this._fetch(`${this.baseUrl}/api/v1/discovery/`, {
      method: 'GET',
      headers: this.headers(),
    });
    if (!r.ok) throw await toError(r);
    return r.json() as Promise<{
      items: Array<{
        kind: string;
        path: string;
        suggested_name: string;
        is_logged_in: boolean;
        error: string | null;
        backend_id: string | null;
      }>;
    }>;
  }

  async importDiscovered(input: {
    kind: string;
    path: string;
    display_name?: string;
  }): Promise<BackendDTO> {
    const r = await this._fetch(`${this.baseUrl}/api/v1/discovery/import`, {
      method: 'POST',
      headers: this.headers(),
      body: JSON.stringify(input),
    });
    if (!r.ok) throw await toError(r);
    return r.json() as Promise<BackendDTO>;
  }

  async listModels(backendId: string): Promise<{ items: Array<{ id: string; display_name: string; context_window: number | null }> }> {
    const r = await this._fetch(
      `${this.baseUrl}/api/v1/backends/${encodeURIComponent(backendId)}/models/`,
      { method: 'GET', headers: this.headers() }
    );
    if (!r.ok) throw await toError(r);
    return (await r.json()) as { items: Array<{ id: string; display_name: string; context_window: number | null }> };
  }

  async getBackendMetadata(): Promise<{ items: BackendMetadata[] }> {
    const r = await this._fetch(`${this.baseUrl}/api/v1/backends/_meta`, {
      headers: this.headers(),
    });
    if (!r.ok) throw await toError(r);
    return (await r.json()) as { items: BackendMetadata[] };
  }

  async startOnboarding(): Promise<OnboardingStateDTO> {
    const r = await this._fetch(`${this.baseUrl}/api/v1/onboarding`, {
      method: 'POST',
      headers: this.headers(),
    });
    if (!r.ok) throw await toError(r);
    return (await r.json()) as OnboardingStateDTO;
  }

  async getOnboarding(id: string): Promise<OnboardingStateDTO> {
    const r = await this._fetch(
      `${this.baseUrl}/api/v1/onboarding/${encodeURIComponent(id)}`,
      { headers: this.headers() }
    );
    if (!r.ok) throw await toError(r);
    return (await r.json()) as OnboardingStateDTO;
  }

  async detectForOnboarding(id: string): Promise<DetectResultsDTO> {
    return this.onboardingAction<DetectResultsDTO>(id, 'detect');
  }

  async pickOnboardingKind(id: string, kind: string, displayName: string): Promise<BackendDTO> {
    return this.onboardingAction<BackendDTO>(id, 'pick', {
      kind,
      display_name: displayName,
    });
  }

  async beginOnboardingLogin(
    id: string,
    flowKind: string,
    inputs: Record<string, string>
  ): Promise<LoginResponseDTO> {
    return this.onboardingAction<LoginResponseDTO>(id, 'login', {
      flow_kind: flowKind,
      inputs,
    });
  }

  async pollOnboardingLogin(id: string, handle: string): Promise<LoginResponseDTO> {
    return this.onboardingAction<LoginResponseDTO>(id, 'login/poll', { handle });
  }

  async finalizeOnboarding(id: string): Promise<OnboardingStateDTO> {
    return this.onboardingAction<OnboardingStateDTO>(id, 'finalize');
  }

  // --- Backend CLI install ---

  async installBackendCli(kind: string): Promise<InstallResult> {
    const r = await this._fetch(
      `${this.baseUrl}/api/v1/backends/${encodeURIComponent(kind)}/install`,
      {
        method: 'POST',
        headers: this.headers(),
      }
    );
    if (!r.ok) throw await toError(r);
    return (await r.json()) as InstallResult;
  }

  // --- CLIProxyAPI ---

  async cliproxyStatus(): Promise<CliproxyStatus> {
    const r = await this._fetch(`${this.baseUrl}/api/v1/cliproxy/status`, {
      method: 'GET',
      headers: this.headers(),
    });
    if (!r.ok) throw await toError(r);
    return (await r.json()) as CliproxyStatus;
  }

  async cliproxyInstall(): Promise<CliproxyInstallResult> {
    const r = await this._fetch(`${this.baseUrl}/api/v1/cliproxy/install`, {
      method: 'POST',
      headers: this.headers(),
    });
    if (!r.ok) throw await toError(r);
    return (await r.json()) as CliproxyInstallResult;
  }

  async cliproxyLoginBegin(
    backendKind: string,
    configDir?: string
  ): Promise<CliproxyLoginBeginResponse> {
    const r = await this._fetch(`${this.baseUrl}/api/v1/cliproxy/login/begin`, {
      method: 'POST',
      headers: this.headers(),
      body: JSON.stringify({ backend_kind: backendKind, config_dir: configDir ?? null }),
    });
    if (!r.ok) throw await toError(r);
    return (await r.json()) as CliproxyLoginBeginResponse;
  }

  async cliproxyCallbackForward(
    callbackUrl: string
  ): Promise<CliproxyCallbackForwardResponse> {
    const r = await this._fetch(
      `${this.baseUrl}/api/v1/cliproxy/login/callback-forward`,
      {
        method: 'POST',
        headers: this.headers(),
        body: JSON.stringify({ callback_url: callbackUrl }),
      }
    );
    if (!r.ok) throw await toError(r);
    return (await r.json()) as CliproxyCallbackForwardResponse;
  }

  async cliproxyLoginStatus(sessionId: string): Promise<CliproxyLoginStatus> {
    const r = await this._fetch(
      `${this.baseUrl}/api/v1/cliproxy/login/status?session_id=${encodeURIComponent(sessionId)}`,
      { method: 'GET', headers: this.headers() }
    );
    if (!r.ok) throw await toError(r);
    return (await r.json()) as CliproxyLoginStatus;
  }

  // --- CLIProxyAPI Server Lifecycle ---

  async cliproxyServerStart(port: number = 8317, apiKey: string = 'not-needed'): Promise<{ status: string; port: number; pid: number | null; message: string }> {
    const r = await this._fetch(`${this.baseUrl}/api/v1/cliproxy/server/start`, {
      method: 'POST', headers: this.headers(),
      body: JSON.stringify({ port, api_key: apiKey }),
    });
    if (!r.ok) throw await toError(r);
    return (await r.json()) as any;
  }

  async cliproxyServerStop(): Promise<{ status: string; message: string }> {
    const r = await this._fetch(`${this.baseUrl}/api/v1/cliproxy/server/stop`, {
      method: 'POST', headers: this.headers(),
    });
    if (!r.ok) throw await toError(r);
    return (await r.json()) as any;
  }

  async cliproxyServerStatus(): Promise<{ installed: boolean; running: boolean; port: number; version: string | null }> {
    const r = await this._fetch(`${this.baseUrl}/api/v1/cliproxy/server/status`, {
      headers: this.headers(),
    });
    if (!r.ok) throw await toError(r);
    return (await r.json()) as any;
  }

  // --- Conversations / Chat ---

  async createConversation(input: { backend_id: string; model: string; title?: string }): Promise<ChatSessionDTO> {
    const r = await this._fetch(`${this.baseUrl}/api/v1/conversations/`, {
      method: 'POST', headers: this.headers(), body: JSON.stringify(input),
    });
    if (!r.ok) throw await toError(r);
    return (await r.json()) as ChatSessionDTO;
  }

  async listConversations(backendId?: string): Promise<{ items: ChatSessionDTO[] }> {
    const qs = backendId ? `?backend_id=${encodeURIComponent(backendId)}` : '';
    const r = await this._fetch(`${this.baseUrl}/api/v1/conversations/${qs}`, { headers: this.headers() });
    if (!r.ok) throw await toError(r);
    return (await r.json()) as { items: ChatSessionDTO[] };
  }

  async getConversation(id: string): Promise<ChatSessionDetailDTO> {
    const r = await this._fetch(`${this.baseUrl}/api/v1/conversations/${encodeURIComponent(id)}`, { headers: this.headers() });
    if (!r.ok) throw await toError(r);
    return (await r.json()) as ChatSessionDetailDTO;
  }

  async *streamChat(sessionId: string, content: string): AsyncIterable<ChatDelta> {
    const url = `${this.baseUrl}/api/v1/conversations/${encodeURIComponent(sessionId)}/messages`;
    const headers: Record<string, string> = { ...this.headers(), Accept: 'text/event-stream' };
    const r = await this._fetch(url, { method: 'POST', headers, body: JSON.stringify({ content }) });
    if (!r.ok) throw await toError(r);
    yield* parseSseChatEvents(r);
  }

  // --- Scheduler ---

  async getSchedulerHealth(): Promise<{ items: AccountHealthDTO[] }> {
    const r = await this._fetch(`${this.baseUrl}/api/v1/scheduler/health`, { headers: this.headers() });
    if (!r.ok) throw await toError(r);
    return (await r.json()) as { items: AccountHealthDTO[] };
  }

  async getAccountHealth(id: string): Promise<AccountHealthDTO> {
    const r = await this._fetch(`${this.baseUrl}/api/v1/scheduler/health/${encodeURIComponent(id)}`, { headers: this.headers() });
    if (!r.ok) throw await toError(r);
    return (await r.json()) as AccountHealthDTO;
  }

  async schedulerPick(kind?: string): Promise<PickResultDTO | null> {
    const r = await this._fetch(`${this.baseUrl}/api/v1/scheduler/pick`, {
      method: 'POST', headers: this.headers(),
      body: JSON.stringify(kind ? { kind } : {}),
    });
    if (r.status === 204) return null;
    if (!r.ok) throw await toError(r);
    return (await r.json()) as PickResultDTO;
  }

  async getChain(): Promise<{ entries: FallbackChainEntryDTO[] }> {
    const r = await this._fetch(`${this.baseUrl}/api/v1/scheduler/chain`, { headers: this.headers() });
    if (!r.ok) throw await toError(r);
    return (await r.json()) as { entries: FallbackChainEntryDTO[] };
  }

  async setChain(entries: FallbackChainEntryDTO[]): Promise<void> {
    const r = await this._fetch(`${this.baseUrl}/api/v1/scheduler/chain`, {
      method: 'PUT', headers: this.headers(), body: JSON.stringify({ entries }),
    });
    if (!r.ok) throw await toError(r);
  }

  async markRateLimited(backendId: string, seconds: number, reason: string): Promise<void> {
    const r = await this._fetch(`${this.baseUrl}/api/v1/scheduler/mark-limited`, {
      method: 'POST', headers: this.headers(),
      body: JSON.stringify({ backend_id: backendId, cooldown_seconds: seconds, reason }),
    });
    if (!r.ok) throw await toError(r);
  }

  // --- Smart Chat ---

  async *sendChat(
    request: SendChatRequest,
    opts: { signal?: AbortSignal; lastEventId?: number } = {},
  ): AsyncIterable<SmartChatEvent> {
    const url = `${this.baseUrl}/api/v1/chat/send`;
    const headers: Record<string, string> = {
      ...this.headers(),
      Accept: 'text/event-stream',
    };
    if (opts.lastEventId && opts.lastEventId > 0) {
      headers['Last-Event-ID'] = String(opts.lastEventId);
    }
    const r = await this._fetch(url, {
      method: 'POST',
      headers,
      body: JSON.stringify(request),
      ...(opts.signal ? { signal: opts.signal } : {}),
    });
    if (!r.ok) throw await toError(r);
    yield* parseSseSmartChatEvents(r);
  }

  async createChatSession(backendId: string, model: string): Promise<ChatSessionDTO> {
    return this.createConversation({ backend_id: backendId, model });
  }

  async listChatSessions(backendId?: string): Promise<{ items: ChatSessionDTO[] }> {
    return this.listConversations(backendId);
  }

  private async postAction<T>(id: string, action: string, body?: unknown): Promise<T> {
    const r = await this._fetch(
      `${this.baseUrl}/api/v1/backends/${encodeURIComponent(id)}/${action}`,
      {
        method: 'POST',
        headers: this.headers(),
        ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
      }
    );
    if (!r.ok) throw await toError(r);
    return (await r.json()) as T;
  }

  private async onboardingAction<T>(id: string, action: string, body?: unknown): Promise<T> {
    const r = await this._fetch(
      `${this.baseUrl}/api/v1/onboarding/${encodeURIComponent(id)}/${action}`,
      {
        method: 'POST',
        headers: this.headers(),
        ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
      }
    );
    if (!r.ok) throw await toError(r);
    return (await r.json()) as T;
  }
}
