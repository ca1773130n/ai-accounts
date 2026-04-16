import { describe, it, expect } from 'vitest'
import type { SmartChatEvent, ProcessGroupType, ToolCallDelta } from '../types/smart-chat'

describe('SmartChatEvent', () => {
  it('accepts tool_call event', () => {
    const event: SmartChatEvent = {
      kind: 'tool_call',
      id: 'tc_1',
      name: 'read_file',
      arguments: '{"path": "/tmp/foo"}',
      group_type: 'tool_call',
    }
    expect(event.kind).toBe('tool_call')
  })

  it('accepts tool_call event with reasoning type', () => {
    const event: SmartChatEvent = {
      kind: 'tool_call',
      id: 'tc_2',
      group_type: 'reasoning',
    }
    expect(event.group_type).toBe('reasoning')
  })
})

describe('ProcessGroupType', () => {
  it('covers all three types', () => {
    const types: ProcessGroupType[] = ['tool_call', 'reasoning', 'code_execution']
    expect(types).toHaveLength(3)
  })
})

describe('ToolCallDelta', () => {
  it('allows minimal delta with only id', () => {
    const delta: ToolCallDelta = { id: 'tc_1' }
    expect(delta.id).toBe('tc_1')
  })
})
