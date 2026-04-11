import { describe, it, expect, vi } from 'vitest';
import { createAccountWizard } from '../src/machines/accountWizard';
import type { AiAccountsClient } from '../src/client';

function makeClient(overrides: Partial<AiAccountsClient> = {}): AiAccountsClient {
  return {
    createBackend: vi.fn().mockResolvedValue({
      id: 'bkd-1',
      kind: 'claude',
      display_name: 'A',
      status: 'unconfigured',
      config: {},
      last_error: null,
    }),
    detectBackend: vi.fn().mockResolvedValue({
      installed: true,
      version: 'x',
      path: '/usr/local/bin/claude',
      notes: null,
    }),
    loginBackend: vi.fn().mockResolvedValue({
      id: 'bkd-1',
      kind: 'claude',
      display_name: 'A',
      status: 'validating',
      config: {},
      last_error: null,
    }),
    validateBackend: vi.fn().mockResolvedValue({
      id: 'bkd-1',
      kind: 'claude',
      display_name: 'A',
      status: 'ready',
      config: {},
      last_error: null,
    }),
    ...overrides,
  } as unknown as AiAccountsClient;
}

describe('accountWizard state machine', () => {
  it('starts in idle state', () => {
    const wiz = createAccountWizard({ client: makeClient() });
    expect(wiz.state).toBe('idle');
  });

  it('start() transitions to picking_kind and emits', () => {
    const client = makeClient();
    const wiz = createAccountWizard({ client });
    const listener = vi.fn();
    wiz.subscribe(listener);
    wiz.start();
    expect(wiz.state).toBe('picking_kind');
    expect(listener).toHaveBeenCalled();
  });

  it('pickKind happy path: picking_kind -> detecting -> entering_credential', async () => {
    const client = makeClient();
    const wiz = createAccountWizard({ client });
    wiz.start();
    await wiz.pickKind('claude');
    expect(wiz.state).toBe('entering_credential');
    expect(wiz.kind).toBe('claude');
    expect(wiz.backend?.id).toBe('bkd-1');
    expect(wiz.detection?.installed).toBe(true);
  });

  it('pickKind transitions to error when CLI is not installed', async () => {
    const client = makeClient({
      detectBackend: vi.fn().mockResolvedValue({
        installed: false,
        version: null,
        path: null,
        notes: null,
      }),
    });
    const wiz = createAccountWizard({ client });
    wiz.start();
    await wiz.pickKind('claude');
    expect(wiz.state).toBe('error');
    expect(wiz.error).toMatch(/not installed/i);
  });

  it('pickKind transitions to error when createBackend rejects', async () => {
    const err = new Error('boom');
    const client = makeClient({
      createBackend: vi.fn().mockRejectedValue(err),
    });
    const wiz = createAccountWizard({ client });
    wiz.start();
    await wiz.pickKind('claude');
    expect(wiz.state).toBe('error');
    expect(wiz.error).toBe('boom');
  });

  it('submitCredential happy path: entering_credential -> validating -> done', async () => {
    const client = makeClient();
    const wiz = createAccountWizard({ client });
    wiz.start();
    await wiz.pickKind('claude');
    await wiz.submitCredential('api_key', { api_key: 'sk-ant-xxx' });
    expect(wiz.state).toBe('done');
    expect(wiz.backend?.status).toBe('ready');
  });

  it('submitCredential transitions to error when validateBackend rejects', async () => {
    const err = new Error('bad key');
    const client = makeClient({
      validateBackend: vi.fn().mockRejectedValue(err),
    });
    const wiz = createAccountWizard({ client });
    wiz.start();
    await wiz.pickKind('claude');
    await wiz.submitCredential('api_key', { api_key: 'wrong' });
    expect(wiz.state).toBe('error');
    expect(wiz.error).toBe('bad key');
  });

  it('submitCredential without a backend in progress goes to error', async () => {
    const wiz = createAccountWizard({ client: makeClient() });
    await wiz.submitCredential('api_key', { api_key: 'x' });
    expect(wiz.state).toBe('error');
    expect(wiz.error).toMatch(/no backend/i);
  });

  it('reset returns to idle and clears state', async () => {
    const wiz = createAccountWizard({ client: makeClient() });
    wiz.start();
    await wiz.pickKind('claude');
    wiz.reset();
    expect(wiz.state).toBe('idle');
    expect(wiz.error).toBeUndefined();
    expect(wiz.kind).toBeUndefined();
    expect(wiz.backend).toBeUndefined();
    expect(wiz.detection).toBeUndefined();
  });

  it('subscribe returns an unsubscribe function', () => {
    const wiz = createAccountWizard({ client: makeClient() });
    const listener = vi.fn();
    const unsubscribe = wiz.subscribe(listener);
    wiz.start();
    expect(listener).toHaveBeenCalledTimes(1);
    unsubscribe();
    wiz.reset();
    expect(listener).toHaveBeenCalledTimes(1); // unsubscribed, no second call
  });

  it('defaultDisplayName is used when creating backend', async () => {
    const client = makeClient();
    const wiz = createAccountWizard({ client, defaultDisplayName: 'My Claude' });
    wiz.start();
    await wiz.pickKind('claude');
    const call = (client.createBackend as ReturnType<typeof vi.fn>).mock.calls[0][0];
    expect(call.display_name).toBe('My Claude');
  });
});
