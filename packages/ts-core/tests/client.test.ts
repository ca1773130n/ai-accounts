import { describe, it, expect, vi } from 'vitest';
import { AiAccountsClient, type ApiError } from '../src/client';

type MockResponse = {
  ok?: boolean;
  status?: number;
  statusText?: string;
  body?: unknown;
};

function mockFetch(response: MockResponse) {
  return vi.fn().mockResolvedValue({
    ok: response.ok ?? true,
    status: response.status ?? 200,
    statusText: response.statusText ?? 'OK',
    json: async () => response.body ?? {},
  } as unknown as Response);
}

describe('AiAccountsClient', () => {
  it('listBackends returns items from body', async () => {
    const fetchMock = mockFetch({ body: { items: [] } });
    const client = new AiAccountsClient({
      baseUrl: 'http://localhost:20000',
      fetch: fetchMock,
    });
    const result = await client.listBackends();
    expect(result.items).toEqual([]);
    expect(fetchMock).toHaveBeenCalledWith(
      'http://localhost:20000/api/v1/backends/',
      expect.anything()
    );
  });

  it('createBackend posts with body', async () => {
    const fetchMock = mockFetch({
      body: {
        id: 'bkd-1',
        kind: 'claude',
        display_name: 'X',
        status: 'unconfigured',
        config: {},
        last_error: null,
      },
    });
    const client = new AiAccountsClient({
      baseUrl: 'http://localhost:20000',
      fetch: fetchMock,
    });
    const created = await client.createBackend({ kind: 'claude', display_name: 'X' });
    expect(created.id).toBe('bkd-1');
    const callArgs = fetchMock.mock.calls[0];
    expect(callArgs[1]?.method).toBe('POST');
  });

  it('throws ApiError with code from error envelope', async () => {
    const fetchMock = mockFetch({
      ok: false,
      status: 404,
      statusText: 'Not Found',
      body: { error: { code: 'backend_not_found', message: 'nope' } },
    });
    const client = new AiAccountsClient({
      baseUrl: 'http://localhost:20000',
      fetch: fetchMock,
    });
    try {
      await client.getBackend('bkd-nope');
      expect.fail('should have thrown');
    } catch (e) {
      const err = e as ApiError;
      expect(err.code).toBe('backend_not_found');
      expect(err.status).toBe(404);
      expect(err.message).toBe('nope');
    }
  });

  it('sends bearer token when provided', async () => {
    const fetchMock = mockFetch({ body: { items: [] } });
    const client = new AiAccountsClient({
      baseUrl: 'http://localhost:20000',
      token: 'secret',
      fetch: fetchMock,
    });
    await client.listBackends();
    const headers = (fetchMock.mock.calls[0][1] as RequestInit).headers as Record<
      string,
      string
    >;
    expect(headers.authorization).toBe('Bearer secret');
  });

  it('deleteBackend uses DELETE method and does not return JSON', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 204,
      statusText: 'No Content',
      json: async () => ({}),
    } as unknown as Response);
    const client = new AiAccountsClient({
      baseUrl: 'http://localhost:20000',
      fetch: fetchMock,
    });
    await client.deleteBackend('bkd-1');
    const callArgs = fetchMock.mock.calls[0];
    expect(callArgs[1]?.method).toBe('DELETE');
  });

  it('loginBackend returns LoginResponseDTO for complete', async () => {
    const fetchMock = mockFetch({
      body: {
        kind: 'complete',
        backend: {
          id: 'bkd-1',
          kind: 'claude',
          display_name: 'X',
          status: 'validating',
          config: {},
          last_error: null,
        },
        oauth: null,
      },
    });
    const client = new AiAccountsClient({ baseUrl: 'http://test', fetch: fetchMock });
    const response = await client.loginBackend('bkd-1', 'api_key', {});
    expect(response.kind).toBe('complete');
    expect(response.backend?.id).toBe('bkd-1');
    expect(response.oauth).toBeNull();
  });

  it('loginBackend returns LoginResponseDTO for pending OAuth', async () => {
    const fetchMock = mockFetch({
      body: {
        kind: 'pending',
        backend: null,
        oauth: {
          verification_uri: 'https://example.com/device',
          user_code: 'ABCD-1234',
          expires_at: '2026-04-11T18:00:00+00:00',
          handle: 'h-1',
        },
      },
    });
    const client = new AiAccountsClient({ baseUrl: 'http://test', fetch: fetchMock });
    const response = await client.loginBackend('bkd-1', 'oauth_device', {});
    expect(response.kind).toBe('pending');
    expect(response.oauth?.user_code).toBe('ABCD-1234');
  });

  it('pollBackendLogin hits the /login/poll endpoint', async () => {
    const fetchMock = mockFetch({
      body: { kind: 'complete', backend: { id: 'bkd-1', status: 'validating' }, oauth: null },
    });
    const client = new AiAccountsClient({ baseUrl: 'http://test', fetch: fetchMock });
    await client.pollBackendLogin('bkd-1', 'handle-x');
    const url = fetchMock.mock.calls[0][0] as string;
    expect(url).toContain('/api/v1/backends/bkd-1/login/poll');
    const opts = fetchMock.mock.calls[0][1] as RequestInit;
    expect(opts.method).toBe('POST');
    expect(JSON.parse(opts.body as string)).toEqual({ handle: 'handle-x' });
  });

  it('startOnboarding creates a session', async () => {
    const fetchMock = mockFetch({
      body: {
        id: 'onb-1',
        current_step: 'welcome',
        selected_backend_kind: null,
        created_backend_id: null,
        error: null,
      },
    });
    const client = new AiAccountsClient({ baseUrl: 'http://test', fetch: fetchMock });
    const state = await client.startOnboarding();
    expect(state.current_step).toBe('welcome');
    expect(state.id).toBe('onb-1');
  });

  it('detectForOnboarding returns results map', async () => {
    const fetchMock = mockFetch({
      body: {
        results: {
          fake: { installed: true, version: 'fake/0.0', path: '/bin/fake', notes: null },
        },
      },
    });
    const client = new AiAccountsClient({ baseUrl: 'http://test', fetch: fetchMock });
    const detect = await client.detectForOnboarding('onb-1');
    expect(detect.results.fake.installed).toBe(true);
  });

  it('finalizeOnboarding returns final state', async () => {
    const fetchMock = mockFetch({
      body: {
        id: 'onb-1',
        current_step: 'done',
        selected_backend_kind: 'fake',
        created_backend_id: 'bkd-1',
        error: null,
      },
    });
    const client = new AiAccountsClient({ baseUrl: 'http://test', fetch: fetchMock });
    const final = await client.finalizeOnboarding('onb-1');
    expect(final.current_step).toBe('done');
    expect(final.created_backend_id).toBe('bkd-1');
  });
});
