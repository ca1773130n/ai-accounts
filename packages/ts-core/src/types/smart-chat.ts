export interface BackendResponse {
  backend: string;
  content: string;
  status: 'streaming' | 'complete' | 'error' | 'timeout';
  error?: string;
}

export interface SynthesisState {
  status: 'waiting' | 'streaming' | 'complete' | 'error';
  content: string;
  primaryBackend: string;
  backendsCollected: string[];
  error?: string;
}

export interface BackendOption {
  kind: string;
  displayName: string;
  accounts: string[];
  models: string[];
}

export type ProcessGroupType = 'tool_call' | 'reasoning' | 'code_execution';

export interface ToolCallDelta {
  id: string;
  name?: string;
  arguments?: string;
  group_type?: ProcessGroupType;
}

type _WithSeq<T> = T & { _seq?: number };

export type SmartChatEvent = _WithSeq<
  | { kind: 'token'; payload: string }
  | { kind: 'done'; payload: Record<string, unknown> }
  | { kind: 'error'; payload: string }
  | { kind: 'backend_delta'; backend: string; text: string }
  | { kind: 'backend_complete'; backend: string }
  | { kind: 'backend_error'; backend: string; error: string }
  | { kind: 'backend_timeout'; backend: string }
  | { kind: 'synthesis_start'; primary_backend: string; backends_collected: string[] }
  | { kind: 'synthesis_delta'; text: string }
  | { kind: 'synthesis_complete' }
  | { kind: 'synthesis_error'; error: string }
  | { kind: 'tool_call'; id: string; name?: string; arguments?: string; group_type?: ProcessGroupType }
>;

export type ChatMode = 'single' | 'all' | 'compound';

export interface SendChatRequest {
  session_id: string;
  content: string;
  mode?: ChatMode;
  backend_kind?: string;
  account_id?: string;
  model?: string;
}
