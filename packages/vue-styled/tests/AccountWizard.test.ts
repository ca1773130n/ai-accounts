import { describe, it, expect, vi } from 'vitest';
import { mount } from '@vue/test-utils';
import { nextTick } from 'vue';
import AccountWizard from '../src/components/AccountWizard.vue';

function makeClient() {
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
  } as any;  // eslint-disable-line @typescript-eslint/no-explicit-any
}

describe('AccountWizard', () => {
  it('renders kind picker initially', async () => {
    const wrapper = mount(AccountWizard, { props: { client: makeClient() } });
    await nextTick();
    expect(wrapper.text()).toContain('Claude');
    expect(wrapper.text()).toContain('OpenCode');
  });

  it('advances through the happy path to done', async () => {
    const client = makeClient();
    const wrapper = mount(AccountWizard, { props: { client } });
    await nextTick();
    const claudeBtn = wrapper.findAll('button').find((b) => b.text() === 'Claude');
    expect(claudeBtn).toBeTruthy();
    await claudeBtn!.trigger('click');
    await new Promise((r) => setTimeout(r, 0));
    await nextTick();
    expect(wrapper.text()).toContain('API key');

    await wrapper.find('input').setValue('sk-ant-xxx');
    await wrapper.find('form').trigger('submit.prevent');
    await new Promise((r) => setTimeout(r, 0));
    await nextTick();
    expect(wrapper.text()).toContain('Connected');
    expect(wrapper.emitted('done')).toBeTruthy();
  });

  it('shows error and retry button when detect fails', async () => {
    const client = {
      ...makeClient(),
      detectBackend: vi.fn().mockResolvedValue({
        installed: false,
        version: null,
        path: null,
        notes: null,
      }),
    };
    const wrapper = mount(AccountWizard, { props: { client: client as any } });
    await nextTick();
    const claudeBtn = wrapper.findAll('button').find((b) => b.text() === 'Claude');
    await claudeBtn!.trigger('click');
    await new Promise((r) => setTimeout(r, 0));
    await nextTick();
    expect(wrapper.text().toLowerCase()).toContain('not installed');
    expect(wrapper.findAll('button').some((b) => b.text() === 'Try again')).toBe(true);
  });
});
