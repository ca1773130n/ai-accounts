import { describe, it, expect } from 'vitest'
import { useStreamingParser } from '../src/composables/useStreamingParser'

describe('useStreamingParser', () => {
  it('returns init, write, finalize, destroy', () => {
    const { init, write, finalize, destroy } = useStreamingParser()
    expect(typeof init).toBe('function')
    expect(typeof write).toBe('function')
    expect(typeof finalize).toBe('function')
    expect(typeof destroy).toBe('function')
  })

  it('write before init is a no-op', () => {
    const { write } = useStreamingParser()
    expect(() => write('hello')).not.toThrow()
  })

  it('finalize without init does not throw', () => {
    const { finalize } = useStreamingParser()
    expect(() => finalize()).not.toThrow()
  })

  it('init + write + finalize does not throw even without smd', () => {
    const { init, write, finalize } = useStreamingParser()
    const container = document.createElement('div')
    init(container)
    write('# Hello')
    finalize()
    expect(true).toBe(true)
  })

  it('init clears container textContent', () => {
    const { init } = useStreamingParser()
    const container = document.createElement('div')
    container.textContent = 'old content'
    init(container)
    expect(container.textContent).toBe('')
  })
})
