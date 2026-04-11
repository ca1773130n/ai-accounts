import { describe, it, expect, vi } from 'vitest';
import { AiAccountsClient } from '../src/client';

function mkClient(body: unknown, status = 200) {
  const fetchMock = vi.fn().mockResolvedValue({
    ok: status < 400,
    status,
    statusText: status === 200 ? 'OK' : status === 201 ? 'Created' : 'Error',
    json: async () => body,
  } as unknown as Response);
  return {
    client: new AiAccountsClient({ baseUrl: 'http://t', fetch: fetchMock }),
    fetchMock,
  };
}

describe('AiAccountsClient install + cliproxy', () => {
  it('installBackendCli POSTs to /backends/{kind}/install', async () => {
    const { client, fetchMock } = mkClient(
      {
        kind: 'claude',
        success: true,
        display: 'npm i -g x',
        stdout: '',
        stderr: '',
        exit_code: 0,
        binary_path: '/usr/local/bin/claude',
      },
      201
    );
    const r = await client.installBackendCli('claude');
    expect(r.success).toBe(true);
    expect(r.kind).toBe('claude');
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('http://t/api/v1/backends/claude/install');
    expect((init as RequestInit).method).toBe('POST');
  });

  it('cliproxyStatus GETs /cliproxy/status', async () => {
    const { client, fetchMock } = mkClient({
      installed: true,
      version: '1.2.3',
      binary_path: '/usr/local/bin/cliproxyapi',
    });
    const r = await client.cliproxyStatus();
    expect(r.installed).toBe(true);
    expect(r.version).toBe('1.2.3');
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('http://t/api/v1/cliproxy/status');
    expect((init as RequestInit).method).toBe('GET');
  });

  it('cliproxyInstall POSTs to /cliproxy/install', async () => {
    const { client, fetchMock } = mkClient(
      {
        success: true,
        display: 'go install ...',
        stdout: '',
        stderr: '',
        binary_path: '/bin/cliproxyapi',
      },
      201
    );
    const r = await client.cliproxyInstall();
    expect(r.success).toBe(true);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('http://t/api/v1/cliproxy/install');
    expect((init as RequestInit).method).toBe('POST');
  });

  it('cliproxyLoginBegin POSTs backend_kind + config_dir', async () => {
    const { client, fetchMock } = mkClient(
      {
        status: 'started',
        message: 'open url',
        oauth_url: 'https://x.test/auth',
        device_code: 'A-1',
      },
      201
    );
    const r = await client.cliproxyLoginBegin('claude', '/tmp/config');
    expect(r.status).toBe('started');
    expect(r.oauth_url).toBe('https://x.test/auth');
    expect(r.device_code).toBe('A-1');
    const body = JSON.parse(
      (fetchMock.mock.calls[0][1] as RequestInit).body as string
    );
    expect(body).toEqual({ backend_kind: 'claude', config_dir: '/tmp/config' });
  });

  it('cliproxyCallbackForward POSTs callback_url', async () => {
    const { client, fetchMock } = mkClient({
      status: 'completed',
      message: 'ok',
    });
    const r = await client.cliproxyCallbackForward(
      'http://localhost:8085/cb?code=x&state=y'
    );
    expect(r.status).toBe('completed');
    const body = JSON.parse(
      (fetchMock.mock.calls[0][1] as RequestInit).body as string
    );
    expect(body.callback_url).toBe('http://localhost:8085/cb?code=x&state=y');
  });
});
