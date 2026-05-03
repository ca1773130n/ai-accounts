import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import CompoundSynthesis from '../src/components/CompoundSynthesis.vue'

const baseState = {
  status: 'streaming' as const,
  content: '',
  primaryBackend: 'claude',
  backendsCollected: ['claude', 'codex'],
}

describe('CompoundSynthesis', () => {
  it('renders the Compound Synthesis label', () => {
    const wrapper = mount(CompoundSynthesis, { props: { state: { ...baseState, content: 'Hello' } } })
    expect(wrapper.find('.aia-synth__label').text()).toBe('Compound Synthesis')
  })

  it('renders the primary backend in the header', () => {
    const wrapper = mount(CompoundSynthesis, { props: { state: { ...baseState, content: 'Hi' } } })
    expect(wrapper.find('.aia-synth__via').text()).toContain('claude')
  })

  it('renders the sources line when backendsCollected has entries', () => {
    const wrapper = mount(CompoundSynthesis, { props: { state: { ...baseState, content: 'Hi' } } })
    expect(wrapper.find('.aia-synth__sources').text()).toContain('claude, codex')
  })

  it('renders the status badge text per status', () => {
    const cases = [
      { status: 'waiting' as const, expected: 'Waiting...' },
      { status: 'streaming' as const, expected: 'Synthesizing' },
      { status: 'complete' as const, expected: 'Complete' },
      { status: 'error' as const, expected: 'Error' },
    ]
    for (const c of cases) {
      const wrapper = mount(CompoundSynthesis, {
        props: { state: { ...baseState, status: c.status, content: 'Hi' } },
      })
      expect(wrapper.find('.aia-synth__badge').text()).toBe(c.expected)
    }
  })

  it('renders rendered markdown in the content area', () => {
    const wrapper = mount(CompoundSynthesis, {
      props: { state: { ...baseState, status: 'complete', content: '**bold**' } },
    })
    expect(wrapper.find('.aia-synth__content').html()).toContain('<strong>bold</strong>')
  })

  it('renders the error block when state.error is set', () => {
    const wrapper = mount(CompoundSynthesis, {
      props: {
        state: { ...baseState, status: 'error', content: '', error: 'oops' },
      },
    })
    expect(wrapper.find('.aia-synth__error').text()).toBe('oops')
  })
})

describe('CompoundSynthesis — back-migrated from Agented', () => {
  it('does NOT render the sparkle glyph by default (backward compat)', () => {
    const wrapper = mount(CompoundSynthesis, {
      props: { state: { ...baseState, content: 'Hi' } },
    })
    expect(wrapper.find('.aia-synth__sparkle').exists()).toBe(false)
  })

  it('renders the sparkle glyph when sparkleIcon=true', () => {
    const wrapper = mount(CompoundSynthesis, {
      props: { state: { ...baseState, content: 'Hi' }, sparkleIcon: true },
    })
    const sparkle = wrapper.find('.aia-synth__sparkle')
    expect(sparkle.exists()).toBe(true)
    expect(sparkle.text()).toBe('✨')
  })

  it('does NOT render the placeholder by default (backward compat)', () => {
    const wrapper = mount(CompoundSynthesis, {
      props: { state: { ...baseState, status: 'streaming', content: '' } },
    })
    expect(wrapper.find('.aia-synth__placeholder').exists()).toBe(false)
    // Empty content area still rendered as before.
    expect(wrapper.find('.aia-synth__content').exists()).toBe(true)
  })

  it('renders the streaming placeholder when loadingPlaceholders + empty + streaming', () => {
    const wrapper = mount(CompoundSynthesis, {
      props: {
        state: { ...baseState, status: 'streaming', content: '' },
        loadingPlaceholders: true,
      },
    })
    expect(wrapper.find('.aia-synth__placeholder').text()).toBe('Generating synthesis...')
    // The empty content box is replaced by the placeholder.
    expect(wrapper.find('.aia-synth__content').exists()).toBe(false)
  })

  it('renders the waiting placeholder when loadingPlaceholders + empty + waiting', () => {
    const wrapper = mount(CompoundSynthesis, {
      props: {
        state: { ...baseState, status: 'waiting', content: '' },
        loadingPlaceholders: true,
      },
    })
    expect(wrapper.find('.aia-synth__placeholder').text()).toBe(
      'Waiting for backend responses...',
    )
  })

  it('does NOT render the placeholder once content arrives', () => {
    const wrapper = mount(CompoundSynthesis, {
      props: {
        state: { ...baseState, status: 'streaming', content: 'partial...' },
        loadingPlaceholders: true,
      },
    })
    expect(wrapper.find('.aia-synth__placeholder').exists()).toBe(false)
    expect(wrapper.find('.aia-synth__content').exists()).toBe(true)
  })

  it('does NOT render the placeholder for complete or error states', () => {
    const complete = mount(CompoundSynthesis, {
      props: {
        state: { ...baseState, status: 'complete', content: '' },
        loadingPlaceholders: true,
      },
    })
    expect(complete.find('.aia-synth__placeholder').exists()).toBe(false)
    const errored = mount(CompoundSynthesis, {
      props: {
        state: { ...baseState, status: 'error', content: '', error: 'x' },
        loadingPlaceholders: true,
      },
    })
    expect(errored.find('.aia-synth__placeholder').exists()).toBe(false)
  })
})
