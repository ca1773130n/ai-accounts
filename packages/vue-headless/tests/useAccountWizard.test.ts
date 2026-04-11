import { describe, it, expect, vi } from 'vitest';
import { defineComponent, h, nextTick } from 'vue';
import { mount } from '@vue/test-utils';
import { useAccountWizard, type UseAccountWizardReturn } from '../src/useAccountWizard';

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

const Harness = defineComponent({
  props: { client: { type: Object, required: true } },
  setup(props, { expose }) {
    const wiz = useAccountWizard({ client: props.client as any });
    expose({ wiz });
    return () => h('div', wiz.state.value);
  },
});

describe('useAccountWizard', () => {
  it('starts in idle state', () => {
    const client = makeClient();
    const wrapper = mount(Harness, { props: { client } });
    const wiz = (wrapper.vm as unknown as { wiz: UseAccountWizardReturn }).wiz;
    expect(wiz.state.value).toBe('idle');
  });

  it('reactively reflects transitions through the happy path', async () => {
    const client = makeClient();
    const wrapper = mount(Harness, { props: { client } });
    const wiz = (wrapper.vm as unknown as { wiz: UseAccountWizardReturn }).wiz;

    wiz.start();
    await nextTick();
    expect(wiz.state.value).toBe('picking_kind');

    await wiz.pickKind('claude');
    await nextTick();
    expect(wiz.state.value).toBe('entering_credential');
    expect(wiz.kind.value).toBe('claude');
    expect(wiz.detection.value?.installed).toBe(true);

    await wiz.submitCredential('api_key', { api_key: 'sk-ant-xxx' });
    await nextTick();
    expect(wiz.state.value).toBe('done');
  });

  it('reset returns to idle', async () => {
    const client = makeClient();
    const wrapper = mount(Harness, { props: { client } });
    const wiz = (wrapper.vm as unknown as { wiz: UseAccountWizardReturn }).wiz;

    wiz.start();
    await wiz.pickKind('claude');
    wiz.reset();
    await nextTick();
    expect(wiz.state.value).toBe('idle');
    expect(wiz.error.value).toBeUndefined();
  });
});
