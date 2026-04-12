export type UrlPrompt = {
  type: 'url_prompt';
  prompt_id: string;
  url: string;
  user_code?: string | null;
};

export type TextPrompt = {
  type: 'text_prompt';
  prompt_id: string;
  prompt: string;
  hidden: boolean;
};

export type MenuOptionDTO = {
  number: number;
  label: string;
  description?: string | null;
};

export type MenuPrompt = {
  type: 'menu_prompt';
  prompt_id: string;
  prompt: string;
  options: MenuOptionDTO[];
};

export type StdoutChunk = {
  type: 'stdout';
  text: string;
};

export type ProgressUpdate = {
  type: 'progress';
  label: string;
  percent?: number | null;
};

export type LoginComplete = {
  type: 'complete';
  account_id: string;
  backend_status: string;
};

export type LoginFailed = {
  type: 'failed';
  code: string;
  message: string;
};

export type LoginEvent =
  | UrlPrompt
  | TextPrompt
  | MenuPrompt
  | StdoutChunk
  | ProgressUpdate
  | LoginComplete
  | LoginFailed;

export type PromptAnswer = {
  prompt_id: string;
  answer: string;
};

export type LoginFlowKind = 'api_key' | 'oauth_device' | 'cli_browser';
