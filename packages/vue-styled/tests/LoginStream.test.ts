import { describe, it, expect, vi, beforeEach } from 'vitest';
import { mount } from '@vue/test-utils';
import { nextTick, ref } from 'vue';
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

  describe('force-fresh OAuth + incognito copy', () => {
    beforeEach(() => {
      // happy-dom clipboard stub
      Object.defineProperty(globalThis.navigator, 'clipboard', {
        value: { writeText: vi.fn().mockResolvedValue(undefined) },
        configurable: true,
      });
      // Prevent auto-open from popping windows during tests
      (globalThis as unknown as { open: unknown }).open = vi.fn();
    });

    it('rewrites Google OAuth URL with prompt=select_account and login_hint', () => {
      const session = mkSession({
        urlPrompt: ref({
          type: 'url_prompt',
          prompt_id: 'u',
          url: 'https://accounts.google.com/o/oauth2/v2/auth?client_id=abc',
        }),
      });
      const w = mount(LoginStream, {
        props: { session: session as never, backendKind: 'gemini', email: 'alice@example.com' },
      });
      const anchor = w.find('a.aia-url-link');
      const href = anchor.attributes('href')!;
      const u = new URL(href);
      expect(u.searchParams.get('prompt')).toBe('select_account consent');
      expect(u.searchParams.get('login_hint')).toBe('alice@example.com');
    });

    it('rewrites Claude OAuth URL with prompt=login', () => {
      const session = mkSession({
        urlPrompt: ref({
          type: 'url_prompt',
          prompt_id: 'u',
          url: 'https://claude.ai/oauth/authorize?state=s',
        }),
      });
      const w = mount(LoginStream, {
        props: { session: session as never, backendKind: 'claude', email: 'bob@example.com' },
      });
      const href = w.find('a.aia-url-link').attributes('href')!;
      expect(new URL(href).searchParams.get('prompt')).toBe('login');
      expect(new URL(href).searchParams.get('login_hint')).toBe('bob@example.com');
    });

    it('copies URL to clipboard on "Copy for Incognito" click and shows hint', async () => {
      const session = mkSession({
        urlPrompt: ref({
          type: 'url_prompt',
          prompt_id: 'u',
          url: 'https://accounts.google.com/o/oauth2/v2/auth',
        }),
      });
      const w = mount(LoginStream, {
        props: { session: session as never, backendKind: 'gemini', email: '' },
      });
      const btn = w.find('button.aia-copy-incognito-btn');
      expect(btn.exists()).toBe(true);
      expect(w.find('.aia-incognito-hint').exists()).toBe(false);
      await btn.trigger('click');
      await nextTick();
      // clipboard.writeText was called with the effective URL
      const writeText = (navigator.clipboard as { writeText: ReturnType<typeof vi.fn> }).writeText;
      expect(writeText).toHaveBeenCalledTimes(1);
      const copied = writeText.mock.calls[0]![0] as string;
      expect(copied).toContain('prompt=select_account+consent');
      expect(w.find('.aia-incognito-hint').exists()).toBe(true);
      expect(w.text()).toContain('incognito');
    });
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
