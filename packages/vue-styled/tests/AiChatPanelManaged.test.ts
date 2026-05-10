import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

// AiChatSelector (rendered when showBackendSelector=true) calls
// useAiAccounts().client.listBackends + listModels on mount. Stub the
// vue-headless surface so the component tree mounts cleanly without a
// real sidecar.
const listBackends = vi.fn()
const listModels = vi.fn()

vi.mock('@ai-accounts/vue-headless', () => ({
  useAiAccounts: () => ({
    client: {
      listBackends,
      listModels,
    },
  }),
}))

describe('AiChatPanelManaged — caller-managed sibling', () => {
  beforeEach(() => {
    listBackends.mockReset()
    listModels.mockReset()
    listBackends.mockResolvedValue({ items: [] })
    listModels.mockResolvedValue({ items: [] })
  })

  it('mounts without errors with no props', async () => {
    const AiChatPanelManaged = (await import('../src/components/AiChatPanelManaged.vue')).default
    const wrapper = mount(AiChatPanelManaged)
    expect(wrapper.find('.chat-panel').exists()).toBe(true)
    // Welcome screen renders by default with empty messages.
    expect(wrapper.find('.chat-welcome').exists()).toBe(true)
  })

  it('renders messages array as ChatBubble entries', async () => {
    const AiChatPanelManaged = (await import('../src/components/AiChatPanelManaged.vue')).default
    const wrapper = mount(AiChatPanelManaged, {
      props: {
        messages: [
          { role: 'user', content: 'hello' },
          { role: 'assistant', content: '**hi**', backend: 'claude' },
        ],
      },
    })
    expect(wrapper.findAll('.aia-bubble')).toHaveLength(2)
    expect(wrapper.text()).toContain('hello')
    // Markdown rendered through ChatBubble — strong tag should be present.
    expect(wrapper.find('.aia-bubble--assistant').html()).toContain('<strong>hi</strong>')
    // Welcome screen suppressed once messages exist.
    expect(wrapper.find('.chat-welcome').exists()).toBe(false)
  })

  it('renders streamingContent as in-flight ChatBubble with streaming=true', async () => {
    const AiChatPanelManaged = (await import('../src/components/AiChatPanelManaged.vue')).default
    const wrapper = mount(AiChatPanelManaged, {
      props: {
        isProcessing: true,
        streamingContent: 'partial response',
        chatMode: 'single',
      },
    })
    const streamingBubble = wrapper.find('.aia-bubble--streaming')
    expect(streamingBubble.exists()).toBe(true)
    expect(streamingBubble.text()).toContain('partial response')
  })

  it('emits update:inputMessage on textarea input', async () => {
    const AiChatPanelManaged = (await import('../src/components/AiChatPanelManaged.vue')).default
    const wrapper = mount(AiChatPanelManaged)
    const ta = wrapper.find('textarea')
    await ta.setValue('typed text')
    const events = wrapper.emitted('update:inputMessage')
    expect(events).toBeTruthy()
    expect(events?.[0]?.[0]).toBe('typed text')
  })

  it('emits send on send button click', async () => {
    const AiChatPanelManaged = (await import('../src/components/AiChatPanelManaged.vue')).default
    const wrapper = mount(AiChatPanelManaged, {
      props: { inputMessage: 'go' },
    })
    await wrapper.find('.btn-send').trigger('click')
    expect(wrapper.emitted('send')).toBeTruthy()
  })

  it('disables send button when input is empty', async () => {
    const AiChatPanelManaged = (await import('../src/components/AiChatPanelManaged.vue')).default
    const wrapper = mount(AiChatPanelManaged, { props: { inputMessage: '' } })
    expect(wrapper.find('.btn-send').attributes('disabled')).toBeDefined()
  })

  it('emits keydown on textarea keydown', async () => {
    const AiChatPanelManaged = (await import('../src/components/AiChatPanelManaged.vue')).default
    const wrapper = mount(AiChatPanelManaged)
    await wrapper.find('textarea').trigger('keydown', { key: 'Enter' })
    const events = wrapper.emitted('keydown')
    expect(events).toBeTruthy()
    expect((events?.[0]?.[0] as KeyboardEvent).key).toBe('Enter')
  })

  it('forwards selector v-model events from AiChatSelector', async () => {
    const AiChatPanelManaged = (await import('../src/components/AiChatPanelManaged.vue')).default
    const wrapper = mount(AiChatPanelManaged, {
      props: {
        showBackendSelector: true,
        selectedBackend: 'auto',
        selectedAccountId: null,
        selectedModel: null,
        chatMode: 'single',
      },
    })
    await flushPromises()
    const selector = wrapper.findComponent({ name: 'AiChatSelector' })
    expect(selector.exists()).toBe(true)

    selector.vm.$emit('update:backend', 'claude')
    selector.vm.$emit('update:accountId', 'bkd-1')
    selector.vm.$emit('update:model', 'sonnet-4.5')
    selector.vm.$emit('update:chatMode', 'compound')

    expect(wrapper.emitted('update:selectedBackend')?.[0]?.[0]).toBe('claude')
    expect(wrapper.emitted('update:selectedAccountId')?.[0]?.[0]).toBe('bkd-1')
    expect(wrapper.emitted('update:selectedModel')?.[0]?.[0]).toBe('sonnet-4.5')
    expect(wrapper.emitted('update:chatMode')?.[0]?.[0]).toBe('compound')
  })

  it('renders FinalizationBanner-style convert banner when canFinalize=true and emits finalize on click', async () => {
    const AiChatPanelManaged = (await import('../src/components/AiChatPanelManaged.vue')).default
    const wrapper = mount(AiChatPanelManaged, {
      props: {
        canFinalize: true,
        bannerTitle: 'Hook ready',
        bannerButtonLabel: 'Create Hook',
        entityLabel: 'hook',
        detectedEntityName: 'my-hook',
      },
    })
    const banner = wrapper.find('.convert-banner')
    expect(banner.exists()).toBe(true)
    expect(banner.text()).toContain('Hook ready')
    expect(banner.text()).toContain('my-hook')

    await wrapper.find('.btn-convert').trigger('click')
    expect(wrapper.emitted('finalize')).toBeTruthy()
  })

  it('forwards header-extra and welcome slots', async () => {
    const AiChatPanelManaged = (await import('../src/components/AiChatPanelManaged.vue')).default
    const wrapper = mount(AiChatPanelManaged, {
      slots: {
        'header-extra': '<div class="custom-header">EXTRA</div>',
        welcome: '<div class="custom-welcome">WELCOME</div>',
      },
    })
    expect(wrapper.find('.custom-header').exists()).toBe(true)
    expect(wrapper.find('.custom-header').text()).toBe('EXTRA')
    expect(wrapper.find('.custom-welcome').exists()).toBe(true)
    expect(wrapper.find('.custom-welcome').text()).toBe('WELCOME')
    // Default welcome should be replaced.
    expect(wrapper.find('.chat-welcome').exists()).toBe(false)
  })

  it('readOnly hides the input area', async () => {
    const AiChatPanelManaged = (await import('../src/components/AiChatPanelManaged.vue')).default
    const wrapper = mount(AiChatPanelManaged, { props: { readOnly: true } })
    expect(wrapper.find('.input-area').exists()).toBe(false)
    expect(wrapper.find('textarea').exists()).toBe(false)
  })

  it('renders processing indicator when isProcessing is true with no streamingContent', async () => {
    const AiChatPanelManaged = (await import('../src/components/AiChatPanelManaged.vue')).default
    const wrapper = mount(AiChatPanelManaged, {
      props: { isProcessing: true, streamingContent: '' },
    })
    expect(wrapper.find('.processing-indicator').exists()).toBe(true)
    expect(wrapper.find('.processing-indicator').text()).toContain('thinking')
  })

  it('renders process groups when processGroups Map provided', async () => {
    const AiChatPanelManaged = (await import('../src/components/AiChatPanelManaged.vue')).default
    const groups = new Map()
    groups.set('g1', {
      type: 'tool_call',
      label: 'read_file',
      content: 'file contents',
      timestamp: '2025-01-15T10:30:00Z',
      isExpanded: true,
    })
    const wrapper = mount(AiChatPanelManaged, {
      props: { processGroups: groups },
    })
    // ProcessGroup renders the badge label "Tool" for tool_call.
    expect(wrapper.text()).toContain('Tool')
    expect(wrapper.text()).toContain('read_file')
  })

  it('renders AllModeResponses for chatMode=all with backendResponses', async () => {
    const AiChatPanelManaged = (await import('../src/components/AiChatPanelManaged.vue')).default
    const responses = new Map()
    responses.set('bkd-1', {
      backend: 'bkd-1',
      backendKind: 'claude',
      content: 'Hello from claude',
      status: 'complete',
    })
    const wrapper = mount(AiChatPanelManaged, {
      props: {
        chatMode: 'all',
        backendResponses: responses,
      },
    })
    // AllModeResponses renders one .aia-resp card per response.
    expect(wrapper.findAll('.aia-resp')).toHaveLength(1)
  })

  it('omits AllModeResponses when chatMode=single', async () => {
    const AiChatPanelManaged = (await import('../src/components/AiChatPanelManaged.vue')).default
    const responses = new Map()
    responses.set('bkd-1', {
      backend: 'bkd-1',
      backendKind: 'claude',
      content: 'x',
      status: 'complete',
    })
    const wrapper = mount(AiChatPanelManaged, {
      props: { chatMode: 'single', backendResponses: responses },
    })
    expect(wrapper.findAll('.aia-resp')).toHaveLength(0)
  })

  // ────────────────────────────────────────────────────────────────────
  // CLI-runner toggle. The panel exposes a per-instance switch that
  // signals to the host whether the next message should go through the
  // host's autonomous CLI runner (tool-using agent) or the legacy
  // CLIProxyAPI path. The panel itself does no routing — these tests
  // pin the prop default, the emit, and the toggle visibility.

  it('renders the CLI runner toggle in CLIProxy mode by default', async () => {
    const AiChatPanelManaged = (await import('../src/components/AiChatPanelManaged.vue')).default
    const wrapper = mount(AiChatPanelManaged)
    const btn = wrapper.find('.cli-runner-toggle__btn')
    expect(btn.exists()).toBe(true)
    expect(btn.attributes('aria-pressed')).toBe('false')
    expect(btn.text()).toContain('CLIProxy')
    expect(btn.classes()).not.toContain('cli-runner-toggle__btn--active')
  })

  it('reflects useCliRunner=true with active styling and label', async () => {
    const AiChatPanelManaged = (await import('../src/components/AiChatPanelManaged.vue')).default
    const wrapper = mount(AiChatPanelManaged, {
      props: { useCliRunner: true },
    })
    const btn = wrapper.find('.cli-runner-toggle__btn')
    expect(btn.attributes('aria-pressed')).toBe('true')
    expect(btn.text()).toContain('CLI runner')
    expect(btn.classes()).toContain('cli-runner-toggle__btn--active')
  })

  it('emits update:useCliRunner with the inverted value on click', async () => {
    const AiChatPanelManaged = (await import('../src/components/AiChatPanelManaged.vue')).default
    const wrapper = mount(AiChatPanelManaged, {
      props: { useCliRunner: false },
    })
    await wrapper.find('.cli-runner-toggle__btn').trigger('click')
    expect(wrapper.emitted('update:useCliRunner')).toEqual([[true]])

    await wrapper.setProps({ useCliRunner: true })
    await wrapper.find('.cli-runner-toggle__btn').trigger('click')
    expect(wrapper.emitted('update:useCliRunner')?.[1]).toEqual([false])
  })

  it('hides the toggle entirely when hideCliRunnerToggle is set', async () => {
    const AiChatPanelManaged = (await import('../src/components/AiChatPanelManaged.vue')).default
    const wrapper = mount(AiChatPanelManaged, {
      props: { hideCliRunnerToggle: true },
    })
    expect(wrapper.find('.cli-runner-toggle').exists()).toBe(false)
    expect(wrapper.find('.cli-runner-toggle__btn').exists()).toBe(false)
  })
})
