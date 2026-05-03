import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import AllModeResponses from '../src/components/AllModeResponses.vue'
import type { BackendResponseState } from '@ai-accounts/vue-headless'

function makeResponses(...rows: Array<Partial<BackendResponseState> & { backend: string }>): Map<string, BackendResponseState> {
  const m = new Map<string, BackendResponseState>()
  for (const r of rows) {
    m.set(r.backend, {
      backend: r.backend,
      backendKind: r.backendKind ?? 'claude',
      accountLabel: r.accountLabel,
      content: r.content ?? '',
      status: r.status ?? 'streaming',
      error: r.error,
    })
  }
  return m
}

describe('AllModeResponses', () => {
  it('renders one card per response', () => {
    const wrapper = mount(AllModeResponses, {
      props: {
        responses: makeResponses(
          { backend: 'bkd-1', backendKind: 'claude', content: 'Hello', status: 'complete' },
          { backend: 'bkd-2', backendKind: 'codex', content: 'Hi', status: 'complete' },
        ),
      },
    })
    expect(wrapper.findAll('.aia-resp')).toHaveLength(2)
  })

  it('shows the backend label and account label', () => {
    const wrapper = mount(AllModeResponses, {
      props: {
        responses: makeResponses({
          backend: 'bkd-1',
          backendKind: 'claude',
          accountLabel: 'team@x.com',
          content: 'Hi',
          status: 'complete',
        }),
      },
    })
    expect(wrapper.find('.aia-resp__name').text()).toBe('Claude')
    expect(wrapper.find('.aia-resp__account').text()).toBe('team@x.com')
  })

  it('renders status badge text', () => {
    const wrapper = mount(AllModeResponses, {
      props: {
        responses: makeResponses(
          { backend: 'a', status: 'streaming', content: 'partial' },
          { backend: 'b', status: 'complete', content: 'done' },
          { backend: 'c', status: 'error', content: '', error: 'boom' },
          { backend: 'd', status: 'timeout', content: '', error: 'timed out' },
        ),
      },
    })
    const badges = wrapper.findAll('.aia-resp__badge').map((b) => b.text())
    expect(badges).toEqual(['Streaming', 'Done', 'Error', 'Timeout'])
  })

  it('renders the explained error block with raw detail', () => {
    const wrapper = mount(AllModeResponses, {
      props: {
        responses: makeResponses({
          backend: 'a',
          status: 'error',
          content: '',
          error: 'no models available',
        }),
      },
    })
    expect(wrapper.find('.aia-resp__error-title').text()).toBe('No models available')
    expect(wrapper.find('.aia-resp__error-detail').text()).toBe('no models available')
  })

  it('suppresses the body for an error card with no content', () => {
    const wrapper = mount(AllModeResponses, {
      props: {
        responses: makeResponses({
          backend: 'a',
          status: 'error',
          content: '',
          error: 'boom',
        }),
      },
    })
    expect(wrapper.find('.aia-resp__body').exists()).toBe(false)
  })
})

describe('AllModeResponses — back-migrated from Agented', () => {
  it('does NOT render a summary header by default (backward compat)', () => {
    const wrapper = mount(AllModeResponses, {
      props: {
        responses: makeResponses({ backend: 'a', status: 'complete', content: 'Hi' }),
      },
    })
    expect(wrapper.find('.aia-responses__summary').exists()).toBe(false)
    expect(wrapper.findAll('.aia-resp')).toHaveLength(1)
  })

  it('summaryHeader=true hides cards behind a single toggle', async () => {
    const wrapper = mount(AllModeResponses, {
      props: {
        summaryHeader: true,
        responses: makeResponses(
          { backend: 'a', status: 'complete', content: 'A' },
          { backend: 'b', status: 'streaming', content: 'partial' },
        ),
      },
    })
    expect(wrapper.find('.aia-responses__summary').exists()).toBe(true)
    expect(wrapper.findAll('.aia-resp')).toHaveLength(0)
    await wrapper.find('.aia-responses__summary').trigger('click')
    expect(wrapper.findAll('.aia-resp')).toHaveLength(2)
  })

  it('summaryHeader chevron toggles the is-open class', async () => {
    const wrapper = mount(AllModeResponses, {
      props: {
        summaryHeader: true,
        responses: makeResponses({ backend: 'a', status: 'complete', content: 'Hi' }),
      },
    })
    const chev = wrapper.find('.aia-responses__summary-chevron')
    expect(chev.classes()).not.toContain('is-open')
    await wrapper.find('.aia-responses__summary').trigger('click')
    expect(chev.classes()).toContain('is-open')
  })

  it('summary count shows N/total during streaming', () => {
    const wrapper = mount(AllModeResponses, {
      props: {
        summaryHeader: true,
        responses: makeResponses(
          { backend: 'a', status: 'complete', content: 'A' },
          { backend: 'b', status: 'streaming', content: 'partial' },
          { backend: 'c', status: 'streaming', content: '' },
        ),
      },
    })
    expect(wrapper.find('.aia-responses__summary-count').text()).toBe('1/3 backends responded')
  })

  it('summary count shows total when all are complete', () => {
    const wrapper = mount(AllModeResponses, {
      props: {
        summaryHeader: true,
        responses: makeResponses(
          { backend: 'a', status: 'complete', content: 'A' },
          { backend: 'b', status: 'complete', content: 'B' },
        ),
      },
    })
    expect(wrapper.find('.aia-responses__summary-count').text()).toBe('2 backend responses')
  })

  it('summaryHeader is hidden when responses map is empty', () => {
    const wrapper = mount(AllModeResponses, {
      props: { summaryHeader: true, responses: new Map() },
    })
    expect(wrapper.find('.aia-responses__summary').exists()).toBe(false)
  })

  it('waitingPlaceholder is null by default — empty streaming card renders no placeholder', () => {
    const wrapper = mount(AllModeResponses, {
      props: {
        responses: makeResponses({ backend: 'a', status: 'streaming', content: '' }),
      },
    })
    expect(wrapper.find('.aia-resp__body').html()).not.toContain('Waiting')
  })

  it('waitingPlaceholder text appears in the body of an empty streaming card', () => {
    const wrapper = mount(AllModeResponses, {
      props: {
        waitingPlaceholder: 'Waiting for response...',
        responses: makeResponses({ backend: 'a', status: 'streaming', content: '' }),
      },
    })
    expect(wrapper.find('.aia-resp__body').html()).toContain('Waiting for response...')
  })

  it('waitingPlaceholder is suppressed once content arrives', () => {
    const wrapper = mount(AllModeResponses, {
      props: {
        waitingPlaceholder: 'Waiting for response...',
        responses: makeResponses({ backend: 'a', status: 'streaming', content: 'real content' }),
      },
    })
    expect(wrapper.find('.aia-resp__body').html()).not.toContain('Waiting for response')
    expect(wrapper.find('.aia-resp__body').html()).toContain('real content')
  })
})
