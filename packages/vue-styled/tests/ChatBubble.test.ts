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
})
