import { ref, type Ref } from 'vue'
import type { ProcessGroupType, ToolCallDelta } from '@ai-accounts/ts-core'

export interface ProcessGroup {
  id: string
  type: ProcessGroupType
  label: string
  content: string
  timestamp: string
  isExpanded: boolean
  autoCollapseMs: number
}

export interface UseProcessGroupsReturn {
  groups: Ref<Map<string, ProcessGroup>>
  addGroup: (group: Omit<ProcessGroup, 'isExpanded'>) => void
  removeGroup: (id: string) => void
  toggleGroup: (id: string) => void
  collapseGroup: (id: string) => void
  expandGroup: (id: string) => void
  updateGroupContent: (id: string, content: string) => void
  clearGroups: () => void
  processToolCallDelta: (delta: ToolCallDelta) => void
}

const AUTO_COLLAPSE_MS: Record<ProcessGroupType, number> = {
  tool_call: 4000,
  reasoning: 2000,
  code_execution: 2000,
}

export function useProcessGroups(): UseProcessGroupsReturn {
  const groups = ref<Map<string, ProcessGroup>>(new Map())

  function _triggerReactivity() {
    groups.value = new Map(groups.value)
  }

  function addGroup(group: Omit<ProcessGroup, 'isExpanded'>) {
    groups.value.set(group.id, { ...group, isExpanded: true })
    _triggerReactivity()
  }

  function removeGroup(id: string) {
    groups.value.delete(id)
    _triggerReactivity()
  }

  function toggleGroup(id: string) {
    const g = groups.value.get(id)
    if (g) {
      g.isExpanded = !g.isExpanded
      _triggerReactivity()
    }
  }

  function collapseGroup(id: string) {
    const g = groups.value.get(id)
    if (g) {
      g.isExpanded = false
      _triggerReactivity()
    }
  }

  function expandGroup(id: string) {
    const g = groups.value.get(id)
    if (g) {
      g.isExpanded = true
      _triggerReactivity()
    }
  }

  function updateGroupContent(id: string, content: string) {
    const g = groups.value.get(id)
    if (g) {
      g.content += content
      _triggerReactivity()
    }
  }

  function clearGroups() {
    groups.value.clear()
    _triggerReactivity()
  }

  function processToolCallDelta(delta: ToolCallDelta) {
    const existing = groups.value.get(delta.id)
    if (existing) {
      if (delta.arguments) {
        existing.content += delta.arguments
        _triggerReactivity()
      }
      return
    }
    const type = delta.group_type ?? 'tool_call'
    addGroup({
      id: delta.id,
      type,
      label: delta.name ?? delta.id,
      content: delta.arguments ?? '',
      timestamp: new Date().toISOString(),
      autoCollapseMs: AUTO_COLLAPSE_MS[type],
    })
  }

  return {
    groups,
    addGroup,
    removeGroup,
    toggleGroup,
    collapseGroup,
    expandGroup,
    updateGroupContent,
    clearGroups,
    processToolCallDelta,
  }
}
