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

export type SmartChatEvent =
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
  | { kind: 'synthesis_error'; error: string };

export type ChatMode = 'single' | 'all' | 'compound';

export interface SendChatRequest {
  session_id: string;
  content: string;
  mode?: ChatMode;
  backend_kind?: string;
  account_id?: string;
  model?: string;
}
