import { describe, it, expect, vi } from 'vitest';
import { mount } from '@vue/test-utils';
import { nextTick } from 'vue';
import OnboardingFlow from '../src/components/OnboardingFlow.vue';

function makeClient() {
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
        claude: { installed: true, version: 'x', path: '/bin/claude', notes: null },
      },
    }),
    pickOnboardingKind: vi.fn().mockResolvedValue({
      id: 'bkd-1',
      kind: 'claude',
      display_name: 'X',
      status: 'unconfigured',
      config: {},
      last_error: null,
    }),
    beginOnboardingLogin: vi.fn().mockResolvedValue({
      kind: 'complete',
      backend: null,
      oauth: null,
    }),
    pollOnboardingLogin: vi.fn(),
    finalizeOnboarding: vi.fn().mockResolvedValue({
      id: 'onb-1',
      current_step: 'done',
      selected_backend_kind: 'claude',
      created_backend_id: 'bkd-1',
      error: null,
    }),
  } as any; // eslint-disable-line @typescript-eslint/no-explicit-any
}

describe('OnboardingFlow', () => {
  it('renders welcome initially', () => {
    const wrapper = mount(OnboardingFlow, { props: { client: makeClient() } });
    expect(wrapper.text()).toContain('Get started');
  });

  it('shows OAuth challenge when oauth is in progress', async () => {
    const client = {
      ...makeClient(),
      beginOnboardingLogin: vi.fn().mockResolvedValue({
        kind: 'pending',
        backend: null,
        oauth: {
          verification_uri: 'https://example.com/device',
          user_code: 'ABCD-1234',
          expires_at: '2026-04-11T18:00:00Z',
          handle: 'h-1',
        },
      }),
      pollOnboardingLogin: vi.fn().mockReturnValue(new Promise(() => {})),
    };
    const wrapper = mount(OnboardingFlow, {
      props: {
        client: client as any, // eslint-disable-line @typescript-eslint/no-explicit-any
        supportedFlowsByKind: { claude: ['api_key', 'oauth_device'] },
      },
    });
    // Click "Get started"
    await wrapper.find('button').trigger('click');
    await new Promise((r) => setTimeout(r, 10));
    await nextTick();
    // Click Claude card
    const claudeBtn = wrapper.findAll('button').find((b) => b.text().includes('Claude'));
    expect(claudeBtn).toBeTruthy();
    await claudeBtn!.trigger('click');
    await new Promise((r) => setTimeout(r, 10));
    await nextTick();
    // Click "Login with browser" tab
    const oauthTab = wrapper.findAll('button').find((b) => b.text().includes('browser'));
    await oauthTab!.trigger('click');
    await nextTick();
    // Click "Start browser login"
    const startBtn = wrapper.findAll('button').find((b) => b.text() === 'Start browser login');
    await startBtn!.trigger('click');
    await new Promise((r) => setTimeout(r, 10));
    await nextTick();
    expect(wrapper.text()).toContain('ABCD-1234');
    expect(wrapper.text()).toContain('https://example.com/device');
  });

  it('shows error with retry button on failure', async () => {
    const client = {
      ...makeClient(),
      startOnboarding: vi.fn().mockRejectedValue(new Error('nope')),
    };
    const wrapper = mount(OnboardingFlow, { props: { client: client as any } }); // eslint-disable-line @typescript-eslint/no-explicit-any
    await wrapper.find('button').trigger('click');
    await new Promise((r) => setTimeout(r, 10));
    await nextTick();
    expect(wrapper.text()).toContain('nope');
    expect(wrapper.findAll('button').some((b) => b.text() === 'Try again')).toBe(true);
  });
});
