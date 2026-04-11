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
});
