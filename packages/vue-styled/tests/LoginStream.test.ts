import { describe, it, expect } from 'vitest';
import { mount } from '@vue/test-utils';
import { ref } from 'vue';
import LoginStream from '../src/components/LoginStream.vue';

function mkSession(overrides: Record<string, unknown> = {}) {
  return {
    status: ref('running'),
    sessionId: ref('s-1'),
    accountId: ref('bkd-1'),
    urlPrompt: ref(null),
    textPrompt: ref(null),
    // Menu-prompt support was added to the component template (v-if on
    // session.menuPrompt.value). Without this ref on the stub, every render
    // throws `Cannot read properties of undefined (reading 'value')`.
    menuPrompt: ref(null),
    stdoutLines: ref([]),
    errorCode: ref(null),
    errorMessage: ref(null),
    start: async () => {},
    respond: async () => {},
    cancel: async () => {},
    ...overrides,
  };
}

describe('LoginStream', () => {
  it('renders URL prompt with user code', () => {
    const session = mkSession({
      urlPrompt: ref({ type: 'url_prompt', prompt_id: 'u', url: 'https://x.test', user_code: 'ABCD' }),
    });
    const w = mount(LoginStream, { props: { session: session as never } });
    expect(w.text()).toContain('https://x.test');
    expect(w.text()).toContain('ABCD');
  });

  it('renders text prompt input', () => {
    const session = mkSession({
      textPrompt: ref({ type: 'text_prompt', prompt_id: 'k', prompt: 'API key', hidden: true }),
    });
    const w = mount(LoginStream, { props: { session: session as never } });
    expect(w.find('input[type="password"]').exists()).toBe(true);
  });

  it('emits respond when form submitted', async () => {
    let captured = '';
    const session = mkSession({
      textPrompt: ref({ type: 'text_prompt', prompt_id: 'k', prompt: 'key', hidden: false }),
      respond: async (a: string) => { captured = a; },
    });
    const w = mount(LoginStream, { props: { session: session as never } });
    await w.find('input').setValue('hello');
    await w.find('form').trigger('submit');
    expect(captured).toBe('hello');
  });

  it('renders error state', () => {
    const session = mkSession({
      status: ref('failed'),
      errorCode: ref('cli_not_found'),
      errorMessage: ref('claude not installed'),
    });
    const w = mount(LoginStream, { props: { session: session as never } });
    expect(w.text()).toContain('claude not installed');
  });

  it('shows stdout scrollback', () => {
    const session = mkSession({
      stdoutLines: ref(['line 1\n', 'line 2\n']),
    });
    const w = mount(LoginStream, { props: { session: session as never } });
    const output = w.find('.aia-terminal__output');
    expect(output.exists()).toBe(true);
    expect(output.text()).toContain('line 1');
    expect(output.text()).toContain('line 2');
  });
});
