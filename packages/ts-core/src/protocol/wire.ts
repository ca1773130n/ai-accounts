// @generated from packages/core/src/ai_accounts_core/protocol/wire.py
// Do not edit directly. Run `just codegen` to regenerate.

export const WIRE_PROTOCOL_VERSION = 1;

export interface SessionStartEvent {
  type: "session_start";
  protocol_version: number;
  session_id: string;
  kind: "chat" | "pty";
  backend_id: string;
}

export interface SessionEndEvent {
  type: "session_end";
  protocol_version: number;
  session_id: string;
  reason: string | null;
}

export interface ChatTokenEvent {
  type: "chat_token";
  protocol_version: number;
  session_id: string;
  token: string;
  model: string | null;
}

export interface ChatToolCallEvent {
  type: "chat_tool_call";
  protocol_version: number;
  session_id: string;
  name: string;
  arguments: string;
}

export interface ChatDoneEvent {
  type: "chat_done";
  protocol_version: number;
  session_id: string;
  tokens_in: number | null;
  tokens_out: number | null;
}

export interface PtyOutputEvent {
  type: "pty_output";
  protocol_version: number;
  session_id: string;
  data: Uint8Array;
}

export interface PtyResizeEvent {
  type: "pty_resize";
  protocol_version: number;
  session_id: string;
  cols: number;
  rows: number;
}

export interface PtyExitEvent {
  type: "pty_exit";
  protocol_version: number;
  session_id: string;
  exit_code: number;
}

export interface ErrorEvent {
  type: "error";
  protocol_version: number;
  code: string;
  message: string;
  session_id: string | null;
}

export type WireEvent =
  | SessionStartEvent
  | SessionEndEvent
  | ChatTokenEvent
  | ChatToolCallEvent
  | ChatDoneEvent
  | PtyOutputEvent
  | PtyResizeEvent
  | PtyExitEvent
  | ErrorEvent;
