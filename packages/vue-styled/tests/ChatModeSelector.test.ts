import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import ChatModeSelector from '../src/components/ChatModeSelector.vue'

describe('ChatModeSelector — back-migrated from Agented', () => {
  it('renders three mode buttons', () => {
    const wrapper = mount(ChatModeSelector, { props: { mode: 'single' } })
    const labels = wrapper.findAll('.aia-chat-mode-selector__btn').map((b) => b.text())
    expect(labels).toEqual(['Single', 'All', 'Compound'])
  })

  it('marks the active mode with the active class', () => {
    const wrapper = mount(ChatModeSelector, { props: { mode: 'all' } })
    const btns = wrapper.findAll('.aia-chat-mode-selector__btn')
    expect(btns[0]!.classes()).not.toContain('aia-chat-mode-selector__btn--active')
    expect(btns[1]!.classes()).toContain('aia-chat-mode-selector__btn--active')
    expect(btns[2]!.classes()).not.toContain('aia-chat-mode-selector__btn--active')
  })

  it('emits update:mode when a mode is clicked', async () => {
    const wrapper = mount(ChatModeSelector, { props: { mode: 'single' } })
    await wrapper.findAll('.aia-chat-mode-selector__btn')[2]!.trigger('click')
    expect(wrapper.emitted('update:mode')).toBeTruthy()
    expect(wrapper.emitted('update:mode')![0]).toEqual(['compound'])
  })

  it('exposes ARIA radiogroup semantics', () => {
    const wrapper = mount(ChatModeSelector, { props: { mode: 'compound' } })
    expect(wrapper.attributes('role')).toBe('radiogroup')
    const btns = wrapper.findAll('.aia-chat-mode-selector__btn')
    expect(btns[0]!.attributes('role')).toBe('radio')
    expect(btns[2]!.attributes('aria-checked')).toBe('true')
    expect(btns[0]!.attributes('aria-checked')).toBe('false')
  })

  it('exposes a description tooltip per mode', () => {
    const wrapper = mount(ChatModeSelector, { props: { mode: 'single' } })
    const btns = wrapper.findAll('.aia-chat-mode-selector__btn')
    expect(btns[0]!.attributes('title')).toBe('Send to one backend')
    expect(btns[1]!.attributes('title')).toBe('Send to all backends simultaneously')
    expect(btns[2]!.attributes('title')).toBe('All backends + AI synthesis')
  })

  it('supports v-model:mode (two-way binding)', async () => {
    const Parent = {
      components: { ChatModeSelector },
      data() {
        return { current: 'single' as const }
      },
      template: '<ChatModeSelector v-model:mode="current" />',
    } as any
    const wrapper = mount(Parent)
    await wrapper.findAll('.aia-chat-mode-selector__btn')[1]!.trigger('click')
    expect((wrapper.vm as any).current).toBe('all')
  })
})
