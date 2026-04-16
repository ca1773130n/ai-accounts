import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import FinalizationBanner from '../src/components/FinalizationBanner.vue'

describe('FinalizationBanner', () => {
  const baseProps = {
    title: 'Hook Ready!',
    buttonLabel: 'Create Hook',
    entityLabel: 'hook',
  }

  it('renders with title and button', () => {
    const wrapper = mount(FinalizationBanner, { props: baseProps })
    expect(wrapper.text()).toContain('Hook Ready!')
    expect(wrapper.find('button').text()).toContain('Create Hook')
  })

  it('shows entity name when provided', () => {
    const wrapper = mount(FinalizationBanner, {
      props: { ...baseProps, entityName: 'my-hook' },
    })
    expect(wrapper.text()).toContain('my-hook')
  })

  it('disables button when finalizing', () => {
    const wrapper = mount(FinalizationBanner, {
      props: { ...baseProps, isFinalizing: true },
    })
    const btn = wrapper.find('button')
    expect(btn.attributes('disabled')).toBeDefined()
    expect(btn.text()).toContain('Creating...')
  })

  it('emits finalize on button click', async () => {
    const wrapper = mount(FinalizationBanner, { props: baseProps })
    await wrapper.find('button').trigger('click')
    expect(wrapper.emitted('finalize')).toBeTruthy()
  })
})
