import { describe, it, expect, vi, beforeEach } from 'vitest';
import { createOnboardingFlow } from '../src/machines/onboardingFlow';
import type { AiAccountsClient } from '../src/client';

function makeClient(overrides: Partial<AiAccountsClient> = {}): AiAccountsClient {
  return {
    startOnboarding: vi.fn().mockResolvedValue({
      id: 'onb-1',
      current_step: 'welcome',
      selected_backend_kind: null,
      created_backend_id: null,
      error: null,
    }),
    detectForOnboarding: vi.fn().mockResolvedValue({
      results: {
        fake: { installed: true, version: 'fake/0.0', path: '/bin/fake', notes: null },
      },
    }),
    pickOnboardingKind: vi.fn().mockResolvedValue({
      id: 'bkd-1',
      kind: 'fake',
      display_name: 'X',
      status: 'unconfigured',
      config: {},
      last_error: null,
    }),
    beginOnboardingLogin: vi.fn().mockResolvedValue({
      kind: 'complete',
      backend: {
        id: 'bkd-1',
        kind: 'fake',
        display_name: 'X',
        status: 'validating',
        config: {},
        last_error: null,
      },
      oauth: null,
    }),
    pollOnboardingLogin: vi.fn().mockResolvedValue({
      kind: 'complete',
      backend: {
        id: 'bkd-1',
        kind: 'fake',
        display_name: 'X',
        status: 'validating',
        config: {},
        last_error: null,
      },
      oauth: null,
    }),
    finalizeOnboarding: vi.fn().mockResolvedValue({
      id: 'onb-1',
      current_step: 'done',
      selected_backend_kind: 'fake',
      created_backend_id: 'bkd-1',
      error: null,
    }),
    ...overrides,
  } as unknown as AiAccountsClient;
}

// suppress unused import warning
void (beforeEach as unknown);

describe('onboardingFlow', () => {
  it('starts in idle', () => {
    const wiz = createOnboardingFlow({ client: makeClient() });
    expect(wiz.state).toBe('idle');
  });

  it('full api-key happy path', async () => {
    const client = makeClient();
    const wiz = createOnboardingFlow({ client });
    await wiz.start();
    expect(wiz.state).toBe('started');
    await wiz.detect();
    expect(wiz.state).toBe('picking_kind');
    expect(wiz.kinds).toHaveLength(1);
    await wiz.pickKind('fake');
    expect(wiz.state).toBe('entering_credential');
    await wiz.submitApiKey('sk-xxx');
    expect(wiz.state).toBe('done');
    expect(wiz.createdBackendId).toBe('bkd-1');
  });

  it('oauth flow polls until complete', async () => {
    let callCount = 0;
    const client = makeClient({
      beginOnboardingLogin: vi.fn().mockImplementation((_id: string, flow: string) => {
        if (flow === 'oauth_device') {
          return Promise.resolve({
            kind: 'pending',
            backend: null,
            oauth: {
              verification_uri: 'https://example.com/device',
              user_code: 'ABCD-1234',
              expires_at: '2026-04-11T18:00:00Z',
              handle: 'h-1',
            },
          });
        }
        return Promise.resolve({ kind: 'complete', backend: null, oauth: null });
      }),
      pollOnboardingLogin: vi.fn().mockImplementation(() => {
        callCount++;
        if (callCount < 2) {
          return Promise.resolve({
            kind: 'pending',
            backend: null,
            oauth: {
              verification_uri: 'https://example.com/device',
              user_code: 'ABCD-1234',
              expires_at: '2026-04-11T18:00:00Z',
              handle: 'h-1',
            },
          });
        }
        return Promise.resolve({ kind: 'complete', backend: null, oauth: null });
      }),
    });
    const wiz = createOnboardingFlow({ client, pollIntervalMs: 1 });
    await wiz.start();
    await wiz.detect();
    await wiz.pickKind('fake');
    await wiz.submitOauthDevice();
    expect(wiz.state).toBe('oauth_polling');
    expect(wiz.oauthChallenge?.user_code).toBe('ABCD-1234');
    // Wait for the polling loop to complete
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(wiz.state).toBe('done');
  });

  it('error state when start fails', async () => {
    const client = makeClient({
      startOnboarding: vi.fn().mockRejectedValue(new Error('network down')),
    });
    const wiz = createOnboardingFlow({ client });
    await wiz.start();
    expect(wiz.state).toBe('error');
    expect(wiz.error).toContain('network down');
  });

  it('reset returns to idle', async () => {
    const wiz = createOnboardingFlow({ client: makeClient() });
    await wiz.start();
    wiz.reset();
    expect(wiz.state).toBe('idle');
    expect(wiz.error).toBeUndefined();
  });

  it('subscribe returns an unsubscribe', async () => {
    const wiz = createOnboardingFlow({ client: makeClient() });
    const listener = vi.fn();
    const unsubscribe = wiz.subscribe(listener);
    await wiz.start();
    expect(listener).toHaveBeenCalled();
    const callCount = listener.mock.calls.length;
    unsubscribe();
    wiz.reset();
    expect(listener.mock.calls.length).toBe(callCount);
  });
});
