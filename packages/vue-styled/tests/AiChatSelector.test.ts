import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

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

const baseBackends = [
  {
    id: 'bkd-claude-1',
    kind: 'claude',
    display_name: 'team@x.com',
    status: 'ready',
    config: {},
    config_dir: null,
    last_error: null,
  },
  {
    id: 'bkd-claude-2',
    kind: 'claude',
    display_name: 'me@y.com',
    status: 'ready',
    config: {},
    config_dir: null,
    last_error: null,
  },
  {
    id: 'bkd-codex-1',
    kind: 'codex',
    display_name: 'codex@z.com',
    status: 'ready',
    config: {},
    config_dir: null,
    last_error: null,
  },
]

describe('AiChatSelector — back-migrated from Agented', () => {
  beforeEach(() => {
    listBackends.mockReset()
    listModels.mockReset()
    listBackends.mockResolvedValue({ items: baseBackends })
    listModels.mockResolvedValue({ items: [{ id: 'sonnet-4.5' }, { id: 'sonnet-4.6' }] })
  })

  it('mounts and renders three select dropdowns + the trailing slot host', async () => {
    const AiChatSelector = (await import('../src/components/AiChatSelector.vue')).default
    const wrapper = mount(AiChatSelector, {
      props: { backend: 'auto', accountId: null, model: null },
    })
    await flushPromises()
    expect(wrapper.findAll('.aia-chat-selector__select')).toHaveLength(3)
    expect(wrapper.find('.aia-chat-selector__select--backend').exists()).toBe(true)
    expect(wrapper.find('.aia-chat-selector__select--account').exists()).toBe(true)
    expect(wrapper.find('.aia-chat-selector__select--model').exists()).toBe(true)
  })

  it('groups backends by kind in the Backend dropdown (one Claude, one Codex)', async () => {
    const AiChatSelector = (await import('../src/components/AiChatSelector.vue')).default
    const wrapper = mount(AiChatSelector, {
      props: { backend: 'auto', accountId: null, model: null },
    })
    await flushPromises()
    const opts = wrapper
      .find('.aia-chat-selector__select--backend')
      .findAll('option')
      .map((o) => o.attributes('value'))
    // ['auto', 'claude', 'codex'] — duplicates collapsed by kind.
    expect(opts).toEqual(['auto', 'claude', 'codex'])
  })

  it('Account dropdown lists per-account display_name when a kind is selected', async () => {
    const AiChatSelector = (await import('../src/components/AiChatSelector.vue')).default
    const wrapper = mount(AiChatSelector, {
      props: { backend: 'claude', accountId: null, model: null },
    })
    await flushPromises()
    const accountSel = wrapper.find('.aia-chat-selector__select--account')
    expect((accountSel.element as HTMLSelectElement).disabled).toBe(false)
    const labels = accountSel.findAll('option').map((o) => o.text())
    expect(labels).toContain('team@x.com')
    expect(labels).toContain('me@y.com')
  })

  it('Account dropdown is disabled in auto mode', async () => {
    const AiChatSelector = (await import('../src/components/AiChatSelector.vue')).default
    const wrapper = mount(AiChatSelector, {
      props: { backend: 'auto', accountId: null, model: null },
    })
    await flushPromises()
    const sel = wrapper.find('.aia-chat-selector__select--account')
    expect((sel.element as HTMLSelectElement).disabled).toBe(true)
  })

  it('eagerly loads models for the selected kind on mount and populates the Model dropdown', async () => {
    const AiChatSelector = (await import('../src/components/AiChatSelector.vue')).default
    const wrapper = mount(AiChatSelector, {
      props: { backend: 'claude', accountId: null, model: null },
    })
    await flushPromises()
    expect(listModels).toHaveBeenCalledWith('bkd-claude-1')
    const opts = wrapper.find('.aia-chat-selector__select--model').findAll('option')
    expect(opts.map((o) => o.text())).toEqual(['Auto', 'sonnet-4.5', 'sonnet-4.6'])
  })

  it('emits update:backend when the Backend dropdown changes', async () => {
    const AiChatSelector = (await import('../src/components/AiChatSelector.vue')).default
    const wrapper = mount(AiChatSelector, {
      props: { backend: 'auto', accountId: null, model: null },
    })
    await flushPromises()
    const sel = wrapper.find('.aia-chat-selector__select--backend')
    await sel.setValue('claude')
    expect(wrapper.emitted('update:backend')![0]).toEqual(['claude'])
  })

  it('forces single mode when a specific backend is picked while in all/compound', async () => {
    const AiChatSelector = (await import('../src/components/AiChatSelector.vue')).default
    const wrapper = mount(AiChatSelector, {
      props: { backend: 'auto', accountId: null, model: null, chatMode: 'compound' },
    })
    await flushPromises()
    const sel = wrapper.find('.aia-chat-selector__select--backend')
    await sel.setValue('claude')
    expect(wrapper.emitted('update:chatMode')![0]).toEqual(['single'])
  })

  it('does NOT force single mode when chatMode is undefined', async () => {
    const AiChatSelector = (await import('../src/components/AiChatSelector.vue')).default
    const wrapper = mount(AiChatSelector, {
      props: { backend: 'auto', accountId: null, model: null },
    })
    await flushPromises()
    await wrapper.find('.aia-chat-selector__select--backend').setValue('claude')
    expect(wrapper.emitted('update:chatMode')).toBeFalsy()
  })

  it('renders the chatMode radio strip when chatMode prop is provided', async () => {
    const AiChatSelector = (await import('../src/components/AiChatSelector.vue')).default
    const wrapper = mount(AiChatSelector, {
      props: { backend: 'auto', accountId: null, model: null, chatMode: 'all' },
    })
    await flushPromises()
    const labels = wrapper.findAll('.aia-chat-selector__mode-radio').map((l) => l.text())
    expect(labels).toEqual(['Single', 'All', 'Compound'])
    expect(wrapper.find('.aia-chat-selector__mode-radio--active').text()).toBe('All')
  })

  it('does NOT render the chatMode strip when chatMode is undefined', async () => {
    const AiChatSelector = (await import('../src/components/AiChatSelector.vue')).default
    const wrapper = mount(AiChatSelector, {
      props: { backend: 'auto', accountId: null, model: null },
    })
    await flushPromises()
    expect(wrapper.find('.aia-chat-selector__mode-group').exists()).toBe(false)
  })

  it('emits update:accountId / update:model with null when backend kind changes', async () => {
    const AiChatSelector = (await import('../src/components/AiChatSelector.vue')).default
    const wrapper = mount(AiChatSelector, {
      props: { backend: 'claude', accountId: 'bkd-claude-1', model: 'sonnet-4.5' },
    })
    await flushPromises()
    await wrapper.setProps({ backend: 'codex' })
    await flushPromises()
    expect(wrapper.emitted('update:accountId')!.at(-1)).toEqual([null])
    expect(wrapper.emitted('update:model')!.at(-1)).toEqual([null])
  })

  it('survives a sidecar listBackends() failure with an Auto-only Backend dropdown', async () => {
    listBackends.mockRejectedValueOnce(new Error('sidecar unreachable'))
    const AiChatSelector = (await import('../src/components/AiChatSelector.vue')).default
    const wrapper = mount(AiChatSelector, {
      props: { backend: 'auto', accountId: null, model: null },
    })
    await flushPromises()
    const opts = wrapper
      .find('.aia-chat-selector__select--backend')
      .findAll('option')
      .map((o) => o.attributes('value'))
    expect(opts).toEqual(['auto'])
  })

  it('exposes a trailing slot for caller-supplied controls', async () => {
    const AiChatSelector = (await import('../src/components/AiChatSelector.vue')).default
    const wrapper = mount(AiChatSelector, {
      props: { backend: 'auto', accountId: null, model: null },
      slots: { trailing: '<button class="trailing-extra">Reset</button>' },
    })
    await flushPromises()
    expect(wrapper.find('.trailing-extra').exists()).toBe(true)
  })
})
