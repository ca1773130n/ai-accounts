export interface ChatSessionDTO {
  id: string;
  backend_id: string;
  model: string | null;
  title: string | null;
  created_at: string;
}

export interface ChatMessageDTO {
  id: string;
  role: 'system' | 'user' | 'assistant' | 'tool';
  content: string;
  created_at: string;
  model: string | null;
  tokens_in: number | null;
  tokens_out: number | null;
}

export interface ChatSessionDetailDTO extends ChatSessionDTO {
  messages: ChatMessageDTO[];
}

export interface ChatDelta {
  kind: 'token' | 'done' | 'error';
  text: string | null;
  finish_reason: string | null;
  model: string | null;
  tokens_in: number | null;
  tokens_out: number | null;
}
