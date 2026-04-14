import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import MessageActions from '../src/components/MessageActions.vue'

describe('MessageActions', () => {
  beforeEach(() => {
    // Reset clipboard mock between tests
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } })
  })

  it('renders copy button', () => {
    const wrapper = mount(MessageActions, { props: { content: 'Hello' } })
    expect(wrapper.find('.action-copy').exists()).toBe(true)
  })

  it('copies content to clipboard on click', async () => {
    const wrapper = mount(MessageActions, { props: { content: 'Hello world' } })
    await wrapper.find('.action-copy').trigger('click')
    expect((navigator.clipboard as any).writeText).toHaveBeenCalledWith('Hello world')
  })

  it('shows copy-all button when allMessages provided', () => {
    const wrapper = mount(MessageActions, {
      props: {
        content: 'Hello',
        allMessages: [
          { role: 'user', content: 'Hi', created_at: '2026-01-01T00:00:00Z' },
          { role: 'assistant', content: 'Hello', created_at: '2026-01-01T00:00:01Z' },
        ],
      },
    })
    expect(wrapper.find('.action-copy-all').exists()).toBe(true)
  })

  it('shows export button when allMessages provided', () => {
    const wrapper = mount(MessageActions, {
      props: {
        content: 'Hello',
        allMessages: [{ role: 'user', content: 'Hi' }],
      },
    })
    expect(wrapper.find('.action-export').exists()).toBe(true)
  })

  it('does not show copy-all/export when allMessages not provided', () => {
    const wrapper = mount(MessageActions, { props: { content: 'Hello' } })
    expect(wrapper.find('.action-copy-all').exists()).toBe(false)
    expect(wrapper.find('.action-export').exists()).toBe(false)
  })
})
