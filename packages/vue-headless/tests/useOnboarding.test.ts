import { describe, it, expect, vi } from 'vitest';
import { defineComponent, h, nextTick } from 'vue';
import { mount } from '@vue/test-utils';
import { useOnboarding, type UseOnboardingReturn } from '../src/useOnboarding';

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
      results: { fake: { installed: true, version: 'fake/0.0', path: '/bin/fake', notes: null } },
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
      backend: null,
      oauth: null,
    }),
    pollOnboardingLogin: vi.fn().mockResolvedValue({
      kind: 'complete',
      backend: null,
      oauth: null,
    }),
    finalizeOnboarding: vi.fn().mockResolvedValue({
      id: 'onb-1',
      current_step: 'done',
      selected_backend_kind: 'fake',
      created_backend_id: 'bkd-1',
      error: null,
    }),
  } as any; // eslint-disable-line @typescript-eslint/no-explicit-any
}

const Harness = defineComponent({
  props: { client: { type: Object, required: true } },
  setup(props, { expose }) {
    const wiz = useOnboarding({ client: props.client as any }); // eslint-disable-line @typescript-eslint/no-explicit-any
    expose({ wiz });
    return () => h('div', wiz.state.value);
  },
});

describe('useOnboarding', () => {
  it('starts in idle', () => {
    const wrapper = mount(Harness, { props: { client: makeClient() } });
    const wiz = (wrapper.vm as unknown as { wiz: UseOnboardingReturn }).wiz;
    expect(wiz.state.value).toBe('idle');
  });

  it('reactively reflects full api-key happy path', async () => {
    const client = makeClient();
    const wrapper = mount(Harness, { props: { client } });
    const wiz = (wrapper.vm as unknown as { wiz: UseOnboardingReturn }).wiz;
    await wiz.start();
    await nextTick();
    expect(wiz.state.value).toBe('started');
    await wiz.detect();
    await nextTick();
    expect(wiz.state.value).toBe('picking_kind');
    await wiz.pickKind('fake');
    await nextTick();
    expect(wiz.state.value).toBe('entering_credential');
    await wiz.submitApiKey('sk');
    await nextTick();
    expect(wiz.state.value).toBe('done');
  });

  it('reset returns to idle', async () => {
    const client = makeClient();
    const wrapper = mount(Harness, { props: { client } });
    const wiz = (wrapper.vm as unknown as { wiz: UseOnboardingReturn }).wiz;
    await wiz.start();
    wiz.reset();
    await nextTick();
    expect(wiz.state.value).toBe('idle');
    expect(wiz.error.value).toBeUndefined();
  });
});
