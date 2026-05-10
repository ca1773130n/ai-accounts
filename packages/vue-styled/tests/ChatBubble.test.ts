import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import ChatBubble from '../src/components/ChatBubble.vue'

describe('ChatBubble — back-migrated upgrades from Agented', () => {
  it('renders as before with bare props (backward compatibility)', () => {
    const wrapper = mount(ChatBubble, {
      props: { role: 'assistant', content: 'hello' },
    })
    expect(wrapper.find('.aia-bubble').exists()).toBe(true)
    expect(wrapper.find('.aia-bubble__avatar').text()).toBe('AI')
    expect(wrapper.find('.aia-bubble__role').text()).toBe('assistant')
  })

  it('avatarPaths renders an SVG instead of the role letter', () => {
    const wrapper = mount(ChatBubble, {
      props: {
        role: 'assistant',
        content: 'hi',
        avatarPaths: ['M12 2L9 9 2 12l7 3 3 7 3-7 7-3-7-3z'],
      },
    })
    const avatar = wrapper.find('.aia-bubble__avatar')
    expect(avatar.find('svg').exists()).toBe(true)
    expect(avatar.find('svg path').exists()).toBe(true)
    expect(avatar.text().trim()).toBe('') // letter fallback suppressed
  })

  it('falls back to role letter when avatarPaths is empty array', () => {
    const wrapper = mount(ChatBubble, {
      props: { role: 'assistant', content: 'hi', avatarPaths: [] },
    })
    expect(wrapper.find('.aia-bubble__avatar').text()).toBe('AI')
    expect(wrapper.find('.aia-bubble__avatar svg').exists()).toBe(false)
  })

  it('assistantName overrides the role label in the header', () => {
    const wrapper = mount(ChatBubble, {
      props: { role: 'assistant', content: 'hi', assistantName: 'Claude' },
    })
    expect(wrapper.find('.aia-bubble__role').text()).toBe('Claude')
  })

  it("user role displays 'You' regardless of assistantName", () => {
    const wrapper = mount(ChatBubble, {
      props: { role: 'user', content: 'hi', assistantName: 'Claude' },
    })
    expect(wrapper.find('.aia-bubble__role').text()).toBe('You')
  })

  it('fade-in class is present by default', () => {
    const wrapper = mount(ChatBubble, {
      props: { role: 'assistant', content: 'hi' },
    })
    expect(wrapper.find('.aia-bubble').classes()).toContain('aia-bubble--fade-in')
  })

  it('skipTransition suppresses the fade-in class', () => {
    const wrapper = mount(ChatBubble, {
      props: { role: 'assistant', content: 'hi', skipTransition: true },
    })
    expect(wrapper.find('.aia-bubble').classes()).not.toContain('aia-bubble--fade-in')
  })

  it('streaming class still applies on top of fade-in', () => {
    const wrapper = mount(ChatBubble, {
      props: { role: 'assistant', content: 'hi', streaming: true },
    })
    const cls = wrapper.find('.aia-bubble').classes()
    expect(cls).toContain('aia-bubble--streaming')
    expect(cls).toContain('aia-bubble--fade-in')
  })

  // Regression: bad timestamps (e.g. SQLite's "2026-05-10 12:34:56"
  // without the ISO ``T`` / ``Z``) used to render as the literal
  // string ``"Invalid Date"`` because
  // ``new Date(bad).toLocaleTimeString()`` doesn't throw — the catch
  // branch never fired. Pin the ``isNaN(getTime())`` guard so the
  // bubble shows nothing instead.

  it('omits timestamp when prop is null', () => {
    const wrapper = mount(ChatBubble, {
      props: { role: 'assistant', content: 'hi', timestamp: null },
    })
    expect(wrapper.find('.aia-bubble__time').exists()).toBe(false)
  })

  it('does not leak the literal "Invalid Date" string for unparseable timestamps', () => {
    const wrapper = mount(ChatBubble, {
      props: {
        role: 'assistant',
        content: 'hi',
        timestamp: 'not-a-date-at-all',
      },
    })
    expect(wrapper.text()).not.toContain('Invalid Date')
  })

  it('renders ISO timestamps as a localized time string', () => {
    const wrapper = mount(ChatBubble, {
      props: {
        role: 'assistant',
        content: 'hi',
        timestamp: '2026-05-10T12:34:56Z',
      },
    })
    const time = wrapper.find('.aia-bubble__time')
    expect(time.exists()).toBe(true)
    expect(time.text()).not.toBe('')
    expect(time.text()).not.toContain('Invalid')
  })
})
