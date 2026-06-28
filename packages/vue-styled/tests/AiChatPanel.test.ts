import { describe, it, expect, vi, beforeEach } from 'vitest';
import { mount } from '@vue/test-utils';
import { ref } from 'vue';
import ChatBubble from '../src/components/ChatBubble.vue';
import ChatInput from '../src/components/ChatInput.vue';
import ChatControls from '../src/components/ChatControls.vue';
import AllModeResponses from '../src/components/AllModeResponses.vue';
import CompoundSynthesis from '../src/components/CompoundSynthesis.vue';

// Mock vue-headless composables for AiChatPanel integration tests
vi.mock('@ai-accounts/vue-headless', () => {
  const makeChat = (opts: { groups?: Map<string, any> } = {}) => ({
    messages: ref([]),
    isStreaming: ref(false),
    streamingContent: ref(''),
    chatMode: ref('single'),
    sessionId: ref(null),
    selectedBackend: ref(null),
    selectedAccount: ref(null),
    selectedModel: ref(null),
    backendResponses: ref(new Map()),
    synthesisState: ref(null),
    canFinalize: ref(false),
    isFinalizing: ref(false),
    error: ref(null),
    processGroups: {
      groups: ref(opts.groups ?? new Map()),
      toggleGroup: vi.fn(),
      addGroup: vi.fn(),
      removeGroup: vi.fn(),
      collapseGroup: vi.fn(),
      expandGroup: vi.fn(),
      updateGroupContent: vi.fn(),
      clearGroups: vi.fn(),
      processToolCallDelta: vi.fn(),
    },
    setMode: vi.fn(),
    selectBackend: vi.fn(),
    resetSession: vi.fn(),
    setConfigParser: vi.fn(),
    send: vi.fn(),
    finalize: vi.fn(),
  });
  // Hold reference so tests can reconfigure before mount
  (globalThis as any).__mockChatOpts = {};
  return {
    useSmartChat: () => makeChat((globalThis as any).__mockChatOpts),
    useSmartScroll: () => ({
      containerRef: ref(null),
      showScrollButton: ref(false),
      scrollToBottom: vi.fn(),
    }),
    // AiChatPanel calls `useAiAccounts()` to get a client for listBackends()
    // on mount. Tests don't care about the result — return an empty-list stub
    // so mount() doesn't crash during `const { client } = useAiAccounts()`.
    useAiAccounts: () => ({
      client: {
        listBackends: vi.fn().mockResolvedValue({ items: [] }),
      },
    }),
  };
});

describe('AiChatPanel process groups', () => {
  beforeEach(() => {
    (globalThis as any).__mockChatOpts = {};
  });

  it('does not render process groups in minimal density by default', async () => {
    const AiChatPanel = (await import('../src/components/AiChatPanel.vue')).default;
    const wrapper = mount(AiChatPanel, { props: { density: 'minimal' } });
    expect(wrapper.find('.process-groups').exists()).toBe(false);
  });

  it('renders process groups when showProcessGroups=true and groups exist', async () => {
    const groups = new Map();
    groups.set('g1', {
      id: 'g1',
      type: 'tool_call',
      label: 'read_file',
      content: 'contents',
      timestamp: '2025-01-15T10:30:00Z',
      isExpanded: true,
      autoCollapseMs: 0,
    });
    (globalThis as any).__mockChatOpts = { groups };
    const AiChatPanel = (await import('../src/components/AiChatPanel.vue')).default;
    const wrapper = mount(AiChatPanel, { props: { showProcessGroups: true } });
    expect(wrapper.find('.process-groups').exists()).toBe(true);
    expect(wrapper.find('.process-group').exists()).toBe(true);
  });

  it('auto-enables process groups in detailed density', async () => {
    const groups = new Map();
    groups.set('g1', {
      id: 'g1', type: 'reasoning', label: 'think', content: 'x',
      timestamp: '2025-01-15T10:30:00Z', isExpanded: true, autoCollapseMs: 0,
    });
    (globalThis as any).__mockChatOpts = { groups };
    const AiChatPanel = (await import('../src/components/AiChatPanel.vue')).default;
    const wrapper = mount(AiChatPanel, { props: { density: 'detailed' } });
    // In detailed density, showProcessGroups defaults to true
    expect(wrapper.find('.process-group').exists()).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// ChatBubble
// ---------------------------------------------------------------------------
describe('ChatBubble', () => {
  it('renders user bubble with correct class', () => {
    const w = mount(ChatBubble, { props: { role: 'user', content: 'Hello' } });
    expect(w.find('.aia-bubble--user').exists()).toBe(true);
    expect(w.text()).toContain('Hello');
  });

  it('renders assistant bubble with markdown', () => {
    const w = mount(ChatBubble, { props: { role: 'assistant', content: '**bold**' } });
    expect(w.find('.aia-bubble--assistant').exists()).toBe(true);
    expect(w.find('.aia-bubble__content').html()).toContain('<strong>bold</strong>');
  });

  it('labels the author by backend and shows the model pill', () => {
    const w = mount(ChatBubble, {
      props: { role: 'assistant', content: 'hi', backend: 'claude', model: 'opus' },
    });
    expect(w.find('.aia-bubble__role').text()).toBe('Claude');
    expect(w.find('.aia-bubble__model').text()).toBe('Opus');
  });

  it('labels the deepseek backend by its display name', () => {
    const ds = mount(ChatBubble, {
      props: { role: 'assistant', content: 'hi', backend: 'deepseek' },
    });
    expect(ds.find('.aia-bubble__role').text()).toBe('DeepSeek');
  });

  it('labels goose/aider/crush backends by their display names', () => {
    const goose = mount(ChatBubble, {
      props: { role: 'assistant', content: 'hi', backend: 'goose' },
    });
    expect(goose.find('.aia-bubble__role').text()).toBe('Goose');
    const aider = mount(ChatBubble, {
      props: { role: 'assistant', content: 'hi', backend: 'aider' },
    });
    expect(aider.find('.aia-bubble__role').text()).toBe('Aider');
    const crush = mount(ChatBubble, {
      props: { role: 'assistant', content: 'hi', backend: 'crush' },
    });
    expect(crush.find('.aia-bubble__role').text()).toBe('Crush');
  });

  it('shows streaming cursor class', () => {
    const w = mount(ChatBubble, { props: { role: 'assistant', content: 'typing...', streaming: true } });
    expect(w.find('.aia-bubble--streaming').exists()).toBe(true);
  });

  it('displays formatted timestamp', () => {
    const w = mount(ChatBubble, {
      props: { role: 'user', content: 'hi', timestamp: '2025-01-15T10:30:00Z' },
    });
    expect(w.find('.aia-bubble__time').exists()).toBe(true);
    expect(w.find('.aia-bubble__time').text()).not.toBe('');
  });

  it('renders avatar U for user, author-initial for assistant (never "AI")', () => {
    const user = mount(ChatBubble, { props: { role: 'user', content: '' } });
    expect(user.find('.aia-bubble__avatar').text()).toBe('U');
    const generic = mount(ChatBubble, { props: { role: 'assistant', content: '' } });
    expect(generic.find('.aia-bubble__avatar').text()).toBe('A');
    const claude = mount(ChatBubble, { props: { role: 'assistant', content: '', backend: 'claude' } });
    expect(claude.find('.aia-bubble__avatar').text()).toBe('C');
  });
});

// ---------------------------------------------------------------------------
// ChatInput
// ---------------------------------------------------------------------------
describe('ChatInput', () => {
  it('emits send on button click', async () => {
    const w = mount(ChatInput);
    await w.find('textarea').setValue('Hello world');
    await w.find('button').trigger('click');
    expect(w.emitted('send')?.[0]).toEqual(['Hello world']);
  });

  it('clears input after send', async () => {
    const w = mount(ChatInput);
    await w.find('textarea').setValue('test');
    await w.find('button').trigger('click');
    expect((w.find('textarea').element as HTMLTextAreaElement).value).toBe('');
  });

  it('does not send empty messages', async () => {
    const w = mount(ChatInput);
    await w.find('button').trigger('click');
    expect(w.emitted('send')).toBeUndefined();
  });

  it('disables textarea when streaming', () => {
    const w = mount(ChatInput, { props: { isStreaming: true } });
    expect(w.find('textarea').attributes('disabled')).toBeDefined();
  });

  it('sends on Enter key (non-shift)', async () => {
    const w = mount(ChatInput);
    await w.find('textarea').setValue('enter-send');
    await w.find('textarea').trigger('keydown', { key: 'Enter', shiftKey: false });
    expect(w.emitted('send')?.[0]).toEqual(['enter-send']);
  });

  it('does not send on Shift+Enter', async () => {
    const w = mount(ChatInput);
    await w.find('textarea').setValue('multi-line');
    await w.find('textarea').trigger('keydown', { key: 'Enter', shiftKey: true });
    expect(w.emitted('send')).toBeUndefined();
  });
});

// ---------------------------------------------------------------------------
// ChatControls
// ---------------------------------------------------------------------------
describe('ChatControls', () => {
  const defaultProps = {
    chatMode: 'single' as const,
    selectedBackend: null,
    selectedModel: null,
    backends: [
      { kind: 'claude', displayName: 'Claude', accounts: ['a@b.com'], models: ['opus'] },
      { kind: 'antigravity', displayName: 'Antigravity', accounts: ['g@g.com'], models: ['pro'] },
    ],
  };

  it('renders mode buttons', () => {
    const w = mount(ChatControls, { props: defaultProps });
    const btns = w.findAll('.aia-controls__mode-btn');
    expect(btns).toHaveLength(3);
    expect(btns.map((b) => b.text())).toEqual(['Single', 'All', 'Compound']);
  });

  it('highlights active mode', () => {
    const w = mount(ChatControls, { props: { ...defaultProps, chatMode: 'all' as const } });
    const active = w.find('.aia-controls__mode-btn--active');
    expect(active.text()).toBe('All');
  });

  it('emits update:chatMode on mode click', async () => {
    const w = mount(ChatControls, { props: defaultProps });
    await w.findAll('.aia-controls__mode-btn')[2].trigger('click');
    expect(w.emitted('update:chatMode')?.[0]).toEqual(['compound']);
  });

  it('lists backends in dropdown', () => {
    const w = mount(ChatControls, { props: defaultProps });
    const options = w.findAll('.aia-controls__group:first-child option');
    expect(options).toHaveLength(3); // Auto + 2 backends
  });

  it('disables account/model selects when auto', () => {
    const w = mount(ChatControls, { props: defaultProps });
    const selects = w.findAll('.aia-controls__select');
    // second and third selects (account, model) should be disabled
    expect(selects[1].attributes('disabled')).toBeDefined();
    expect(selects[2].attributes('disabled')).toBeDefined();
  });
});

// ---------------------------------------------------------------------------
// AllModeResponses
// ---------------------------------------------------------------------------
describe('AllModeResponses', () => {
  function makeResponses() {
    const map = new Map();
    map.set('claude', { backend: 'claude', content: 'Claude says hi', status: 'complete' });
    map.set('antigravity', { backend: 'antigravity', content: 'Antigravity says hello', status: 'streaming' });
    return map;
  }

  it('renders a card per backend response', () => {
    const w = mount(AllModeResponses, { props: { responses: makeResponses() } });
    const cards = w.findAll('.aia-resp');
    expect(cards).toHaveLength(2);
  });

  it('shows backend names', () => {
    const w = mount(AllModeResponses, { props: { responses: makeResponses() } });
    expect(w.text()).toContain('Claude');
    expect(w.text()).toContain('Antigravity');
  });

  it('shows status badges', () => {
    const w = mount(AllModeResponses, { props: { responses: makeResponses() } });
    expect(w.text()).toContain('Done');
    expect(w.text()).toContain('Streaming');
  });

  it('renders markdown content', () => {
    const map = new Map();
    map.set('claude', { backend: 'claude', content: '**bold text**', status: 'complete' });
    const w = mount(AllModeResponses, { props: { responses: map } });
    expect(w.find('.aia-resp__body').html()).toContain('<strong>bold text</strong>');
  });

  it('shows error messages', () => {
    const map = new Map();
    map.set('claude', { backend: 'claude', content: '', status: 'error', error: 'Something failed' });
    const w = mount(AllModeResponses, { props: { responses: map } });
    expect(w.text()).toContain('Something failed');
  });
});

// ---------------------------------------------------------------------------
// CompoundSynthesis
// ---------------------------------------------------------------------------
describe('CompoundSynthesis', () => {
  const baseState = {
    status: 'complete' as const,
    content: 'Synthesized result here',
    primaryBackend: 'claude',
    backendsCollected: ['claude', 'antigravity'],
  };

  it('shows Compound Synthesis label', () => {
    const w = mount(CompoundSynthesis, { props: { state: baseState } });
    expect(w.text()).toContain('Compound Synthesis');
  });

  it('shows primary backend', () => {
    const w = mount(CompoundSynthesis, { props: { state: baseState } });
    expect(w.text()).toContain('via claude');
  });

  it('lists source backends', () => {
    const w = mount(CompoundSynthesis, { props: { state: baseState } });
    expect(w.text()).toContain('claude, antigravity');
  });

  it('renders markdown content', () => {
    const state = { ...baseState, content: '*italic*' };
    const w = mount(CompoundSynthesis, { props: { state } });
    expect(w.find('.aia-synth__content').html()).toContain('<em>italic</em>');
  });

  it('shows streaming class when streaming', () => {
    const state = { ...baseState, status: 'streaming' as const };
    const w = mount(CompoundSynthesis, { props: { state } });
    expect(w.find('.aia-synth--streaming').exists()).toBe(true);
  });

  it('shows error when present', () => {
    const state = { ...baseState, status: 'error' as const, error: 'synthesis failed' };
    const w = mount(CompoundSynthesis, { props: { state } });
    expect(w.text()).toContain('synthesis failed');
  });

  it('shows status badge', () => {
    const w = mount(CompoundSynthesis, { props: { state: baseState } });
    expect(w.text()).toContain('Complete');
  });
});
