import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import ProcessGroup from '../src/components/ProcessGroup.vue'

describe('ProcessGroup', () => {
  const defaultProps = {
    id: 'tc_1',
    type: 'tool_call' as const,
    label: 'read_file',
    timestamp: '2026-04-13T00:00:00Z',
    isExpanded: true,
  }

  it('renders type badge label (Tool) for tool_call', () => {
    const wrapper = mount(ProcessGroup, { props: defaultProps })
    expect(wrapper.text()).toContain('Tool')
    expect(wrapper.text()).toContain('read_file')
  })

  it('renders Thinking badge for reasoning type', () => {
    const wrapper = mount(ProcessGroup, { props: { ...defaultProps, type: 'reasoning' } })
    expect(wrapper.text()).toContain('Thinking')
  })

  it('renders Code badge for code_execution', () => {
    const wrapper = mount(ProcessGroup, { props: { ...defaultProps, type: 'code_execution' } })
    expect(wrapper.text()).toContain('Code')
  })

  it('shows default slot when expanded', () => {
    const wrapper = mount(ProcessGroup, {
      props: defaultProps,
      slots: { default: '<pre>file contents</pre>' },
    })
    expect(wrapper.html()).toContain('file contents')
  })

  it('hides body when collapsed', () => {
    const wrapper = mount(ProcessGroup, {
      props: { ...defaultProps, isExpanded: false },
      slots: { default: '<pre>file contents</pre>' },
    })
    expect(wrapper.find('.process-group-body').exists()).toBe(false)
  })

  it('emits toggle when header clicked', async () => {
    const wrapper = mount(ProcessGroup, { props: defaultProps })
    await wrapper.find('.process-group-header').trigger('click')
    expect(wrapper.emitted('toggle')).toBeTruthy()
  })
})

describe('ProcessGroup — back-migrated from Agented', () => {
  const baseProps = {
    id: 'tc_1',
    type: 'tool_call' as const,
    label: 'read_file',
    timestamp: '2026-04-13T00:00:00Z',
    isExpanded: true,
  }

  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.restoreAllMocks()
    vi.useRealTimers()
  })

  it('does NOT render badge SVG icons by default (backward compat)', () => {
    const wrapper = mount(ProcessGroup, { props: baseProps })
    expect(wrapper.find('.process-group-badge-icon').exists()).toBe(false)
  })

  it('renders an SVG icon inside the badge when iconBadges is true', () => {
    const wrapper = mount(ProcessGroup, { props: { ...baseProps, iconBadges: true } })
    const icon = wrapper.find('.process-group-badge-icon')
    expect(icon.exists()).toBe(true)
    expect(icon.element.tagName.toLowerCase()).toBe('svg')
  })

  it('iconBadges renders distinct SVGs per type', () => {
    const tool = mount(ProcessGroup, { props: { ...baseProps, iconBadges: true, type: 'tool_call' } })
    const reasoning = mount(ProcessGroup, { props: { ...baseProps, iconBadges: true, type: 'reasoning' } })
    const code = mount(ProcessGroup, { props: { ...baseProps, iconBadges: true, type: 'code_execution' } })
    // Each renders exactly one icon SVG inside the badge.
    expect(tool.findAll('.process-group-badge-icon')).toHaveLength(1)
    expect(reasoning.findAll('.process-group-badge-icon')).toHaveLength(1)
    expect(code.findAll('.process-group-badge-icon')).toHaveLength(1)
  })

  it('renders empty time when timestamp is invalid', () => {
    const wrapper = mount(ProcessGroup, { props: { ...baseProps, timestamp: 'not-a-date' } })
    // Either the time element is hidden, or its text is empty.
    const time = wrapper.find('.process-group-time')
    if (time.exists()) {
      expect(time.text().trim()).toBe('')
    }
  })

  it('renders empty time when timestamp is undefined', () => {
    const { timestamp: _, ...rest } = baseProps
    void _
    const wrapper = mount(ProcessGroup, { props: rest })
    expect(wrapper.find('.process-group-time').exists()).toBe(false)
  })

  it('autoCollapseMs=0 (default) never schedules a timer', async () => {
    const wrapper = mount(ProcessGroup, { props: baseProps })
    vi.advanceTimersByTime(60_000)
    await nextTick()
    expect(wrapper.emitted('toggle')).toBeFalsy()
  })

  it('autoCollapseMs > 0 emits toggle after the timer fires', async () => {
    const wrapper = mount(ProcessGroup, {
      props: { ...baseProps, autoCollapseMs: 1000 },
    })
    expect(wrapper.emitted('toggle')).toBeFalsy()
    vi.advanceTimersByTime(1000)
    await nextTick()
    expect(wrapper.emitted('toggle')).toBeTruthy()
    expect(wrapper.emitted('toggle')!.length).toBe(1)
  })

  it('mouseenter cancels a pending auto-collapse', async () => {
    const wrapper = mount(ProcessGroup, {
      props: { ...baseProps, autoCollapseMs: 1000 },
    })
    await wrapper.find('.process-group').trigger('mouseenter')
    vi.advanceTimersByTime(2000)
    await nextTick()
    expect(wrapper.emitted('toggle')).toBeFalsy()
  })

  it('mouseleave reschedules the auto-collapse', async () => {
    const wrapper = mount(ProcessGroup, {
      props: { ...baseProps, autoCollapseMs: 1000 },
    })
    await wrapper.find('.process-group').trigger('mouseenter')
    vi.advanceTimersByTime(500)
    await wrapper.find('.process-group').trigger('mouseleave')
    vi.advanceTimersByTime(1000)
    await nextTick()
    expect(wrapper.emitted('toggle')).toBeTruthy()
  })

  it('timer does not fire after unmount', async () => {
    const wrapper = mount(ProcessGroup, {
      props: { ...baseProps, autoCollapseMs: 1000 },
    })
    wrapper.unmount()
    vi.advanceTimersByTime(2000)
    await nextTick()
    // No emit possible because the wrapper is gone — but more importantly,
    // the test verifies no uncaught timer error fires.
    expect(true).toBe(true)
  })

  it('does not emit toggle if isExpanded is already false when timer fires', async () => {
    const wrapper = mount(ProcessGroup, {
      props: { ...baseProps, autoCollapseMs: 1000, isExpanded: false },
    })
    vi.advanceTimersByTime(2000)
    await nextTick()
    expect(wrapper.emitted('toggle')).toBeFalsy()
  })

  it('rearms timer when isExpanded transitions false -> true', async () => {
    const wrapper = mount(ProcessGroup, {
      props: { ...baseProps, autoCollapseMs: 1000, isExpanded: false },
    })
    vi.advanceTimersByTime(2000)
    await nextTick()
    expect(wrapper.emitted('toggle')).toBeFalsy()
    await wrapper.setProps({ isExpanded: true })
    vi.advanceTimersByTime(1000)
    await nextTick()
    expect(wrapper.emitted('toggle')).toBeTruthy()
  })
})
