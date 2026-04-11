import { describe, it, expect, vi } from 'vitest';
import { AiAccountsClient } from '../src/client';
import type { LoginEvent } from '../src/types/login';

describe('AiAccountsClient.beginLogin', () => {
  it('POSTs flow_kind + inputs and returns session_id', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 201,
      statusText: 'Created',
      json: async () => ({ session_id: 'sess-abc' }),
    } as unknown as Response);

    const client = new AiAccountsClient({ baseUrl: 'http://test', fetch: fetchMock });
    const r = await client.beginLogin('bkd-1', 'api_key', { key: 'sk-x' });
    expect(r.session_id).toBe('sess-abc');

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('http://test/api/v1/backends/bkd-1/login/begin');
    expect((init as RequestInit).method).toBe('POST');
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({
      flow_kind: 'api_key',
      inputs: { key: 'sk-x' },
    });
  });

  it('respondLogin POSTs prompt + answer', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 204,
      statusText: 'No Content',
      json: async () => ({}),
    } as unknown as Response);
    const client = new AiAccountsClient({ baseUrl: 'http://test', fetch: fetchMock });
    await client.respondLogin('bkd-1', 'sess-abc', 'p-1', 'the-answer');
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('http://test/api/v1/backends/bkd-1/login/respond');
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({
      session_id: 'sess-abc',
      prompt_id: 'p-1',
      answer: 'the-answer',
    });
  });

  it('cancelLogin POSTs session_id', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 204,
      statusText: 'No Content',
      json: async () => ({}),
    } as unknown as Response);
    const client = new AiAccountsClient({ baseUrl: 'http://test', fetch: fetchMock });
    await client.cancelLogin('bkd-1', 'sess-abc');
    const [url] = fetchMock.mock.calls[0];
    expect(url).toBe('http://test/api/v1/backends/bkd-1/login/cancel');
  });

  it('getBackendMetadata returns items', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      statusText: 'OK',
      json: async () => ({
        items: [
          {
            kind: 'fake',
            display_name: 'Fake',
            icon_url: null,
            install_check: { command: [], version_regex: '' },
            login_flows: [],
            plan_options: null,
            config_schema: {},
            supports_multi_account: true,
            isolation_env_var: null,
          },
        ],
      }),
    } as unknown as Response);
    const client = new AiAccountsClient({ baseUrl: 'http://test', fetch: fetchMock });
    const r = await client.getBackendMetadata();
    expect(r.items).toHaveLength(1);
    expect(r.items[0].kind).toBe('fake');
  });
});

describe('streamLogin', () => {
  it('parses SSE data lines into LoginEvent', async () => {
    const body = [
      'event: login',
      'data: {"type":"text_prompt","prompt_id":"p","prompt":"key","hidden":true}',
      '',
      'event: login',
      'data: {"type":"complete","account_id":"bkd-1","backend_status":"validating"}',
      '',
      '',
    ].join('\n');

    const encoder = new TextEncoder();
    const stream = new ReadableStream({
      start(controller) {
        controller.enqueue(encoder.encode(body));
        controller.close();
      },
    });

    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      statusText: 'OK',
      body: stream,
      headers: new Headers({ 'content-type': 'text/event-stream' }),
    } as unknown as Response);

    const client = new AiAccountsClient({ baseUrl: 'http://test', fetch: fetchMock });
    const events: LoginEvent[] = [];
    for await (const e of client.streamLogin('bkd-1', 'sess-abc')) {
      events.push(e);
    }
    expect(events).toHaveLength(2);
    expect(events[0].type).toBe('text_prompt');
    expect(events[1].type).toBe('complete');
  });
});
