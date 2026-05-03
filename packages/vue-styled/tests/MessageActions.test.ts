import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
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

describe('MessageActions — back-migrated from Agented', () => {
  beforeEach(() => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } })
  })

  it('renders text labels by default (backward compatibility)', () => {
    const wrapper = mount(MessageActions, { props: { content: 'Hello' } })
    expect(wrapper.find('.action-copy').text()).toBe('Copy')
    expect(wrapper.find('.action-icon').exists()).toBe(false)
  })

  it('iconButtons replaces text with SVG icons', () => {
    const wrapper = mount(MessageActions, {
      props: {
        content: 'Hello',
        iconButtons: true,
        allMessages: [{ role: 'user', content: 'Hi' }],
      },
    })
    const icons = wrapper.findAll('.action-icon')
    // copy + copy-all + export = 3 icons
    expect(icons.length).toBe(3)
    expect(wrapper.find('.action-copy').text()).toBe('')
  })

  it('title attribute changes with copy state', async () => {
    const wrapper = mount(MessageActions, { props: { content: 'Hello' } })
    expect(wrapper.find('.action-copy').attributes('title')).toBe('Copy message')
    await wrapper.find('.action-copy').trigger('click')
    // The success state is set after the await — give it a microtask.
    await Promise.resolve()
    await nextTick()
    expect(wrapper.find('.action-copy').attributes('title')).toBe('Copied!')
  })

  it('icon swaps from clipboard to checkmark on success', async () => {
    const wrapper = mount(MessageActions, {
      props: { content: 'Hello', iconButtons: true },
    })
    // Idle: clipboard icon (rect element).
    expect(wrapper.find('.action-copy .action-icon rect').exists()).toBe(true)
    await wrapper.find('.action-copy').trigger('click')
    await Promise.resolve()
    await nextTick()
    // Success: checkmark path (no rect).
    expect(wrapper.find('.action-copy .action-icon rect').exists()).toBe(false)
    expect(wrapper.find('.action-copy .action-icon path').exists()).toBe(true)
  })

  it('copy-all button no-ops on empty allMessages array', async () => {
    const wrapper = mount(MessageActions, {
      props: { content: 'Hello', allMessages: [] },
    })
    await wrapper.find('.action-copy-all').trigger('click')
    expect((navigator.clipboard as any).writeText).not.toHaveBeenCalled()
  })

  it('formatConversation accepts timestamp as fallback for created_at', async () => {
    const wrapper = mount(MessageActions, {
      props: {
        content: 'Hello',
        allMessages: [
          { role: 'user', content: 'Hi', timestamp: '2026-04-13T00:00:00Z' } as any,
        ],
      },
    })
    await wrapper.find('.action-copy-all').trigger('click')
    expect((navigator.clipboard as any).writeText).toHaveBeenCalledWith(
      '[user] 2026-04-13T00:00:00Z\nHi',
    )
  })

  it('formatConversation handles message with neither timestamp field', async () => {
    const wrapper = mount(MessageActions, {
      props: {
        content: 'Hello',
        allMessages: [{ role: 'user', content: 'Hi' }],
      },
    })
    await wrapper.find('.action-copy-all').trigger('click')
    expect((navigator.clipboard as any).writeText).toHaveBeenCalledWith('[user] \nHi')
  })

  it('@click.stop prevents click propagation to parent', async () => {
    const onParentClick = vi.fn()
    const wrapper = mount({
      components: { MessageActions },
      template: '<div @click="onClick"><MessageActions content="Hello" /></div>',
      methods: { onClick: onParentClick },
    } as any)
    await wrapper.find('.action-copy').trigger('click')
    expect(onParentClick).not.toHaveBeenCalled()
  })
})
