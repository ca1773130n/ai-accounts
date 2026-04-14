import { describe, it, expect } from 'vitest'
import { useProcessGroups } from '../src/composables/useProcessGroups'

describe('useProcessGroups', () => {
  it('adds a group', () => {
    const { groups, addGroup } = useProcessGroups()
    addGroup({ id: 'tc_1', type: 'tool_call', label: 'read_file', content: '', timestamp: new Date().toISOString(), autoCollapseMs: 4000 })
    expect(groups.value.size).toBe(1)
    expect(groups.value.get('tc_1')?.label).toBe('read_file')
    expect(groups.value.get('tc_1')?.isExpanded).toBe(true)
  })

  it('updates group content', () => {
    const { groups, addGroup, updateGroupContent } = useProcessGroups()
    addGroup({ id: 'tc_1', type: 'tool_call', label: 'read_file', content: 'part1', timestamp: new Date().toISOString(), autoCollapseMs: 0 })
    updateGroupContent('tc_1', ' part2')
    expect(groups.value.get('tc_1')?.content).toBe('part1 part2')
  })

  it('processes tool call delta — creates new group', () => {
    const { groups, processToolCallDelta } = useProcessGroups()
    processToolCallDelta({ id: 'tc_1', name: 'search', group_type: 'tool_call' })
    expect(groups.value.size).toBe(1)
    expect(groups.value.get('tc_1')?.label).toBe('search')
    expect(groups.value.get('tc_1')?.type).toBe('tool_call')
  })

  it('processes tool call delta — appends arguments to existing group', () => {
    const { groups, processToolCallDelta } = useProcessGroups()
    processToolCallDelta({ id: 'tc_1', name: 'search' })
    processToolCallDelta({ id: 'tc_1', arguments: '{"query":' })
    processToolCallDelta({ id: 'tc_1', arguments: ' "hello"}' })
    expect(groups.value.get('tc_1')?.content).toBe('{"query": "hello"}')
  })

  it('clears all groups', () => {
    const { groups, addGroup, clearGroups } = useProcessGroups()
    addGroup({ id: 'tc_1', type: 'tool_call', label: 'a', content: '', timestamp: '', autoCollapseMs: 0 })
    addGroup({ id: 'tc_2', type: 'reasoning', label: 'b', content: '', timestamp: '', autoCollapseMs: 0 })
    clearGroups()
    expect(groups.value.size).toBe(0)
  })

  it('toggles group expansion', () => {
    const { groups, addGroup, toggleGroup } = useProcessGroups()
    addGroup({ id: 'tc_1', type: 'tool_call', label: 'a', content: '', timestamp: '', autoCollapseMs: 0 })
    expect(groups.value.get('tc_1')?.isExpanded).toBe(true)
    toggleGroup('tc_1')
    expect(groups.value.get('tc_1')?.isExpanded).toBe(false)
  })
})
