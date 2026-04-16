import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
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
