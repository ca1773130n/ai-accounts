import type { paths } from './generated';
import { parseSseLoginEvents } from './login-stream';
import type { LoginEvent, LoginFlowKind } from '../types/login';
import type { BackendMetadata } from '../types/metadata';

export type { paths } from './generated';

export interface BackendDTO {
  id: string;
  kind: string;
  display_name: string;
  status: string;
  config: Record<string, unknown>;
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
  token?: string;
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
  private readonly token: string | undefined;
  private readonly _fetch: typeof fetch;

  constructor(opts: ClientOptions) {
    this.baseUrl = opts.baseUrl.replace(/\/$/, '');
    this.token = opts.token;
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
