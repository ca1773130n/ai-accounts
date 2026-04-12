export type AiAccountsEvent =
  | { type: 'wizard.opened'; backendKind: string }
  | { type: 'wizard.step'; backendKind: string; step: string }
  | { type: 'wizard.account.created'; backendKind: string; accountId: string }
  | { type: 'wizard.closed'; backendKind: string; reason: 'done' | 'skip' | 'cancel' }
  | { type: 'login.started'; sessionId: string; backendKind: string; flow: string }
  | { type: 'login.prompt'; sessionId: string; promptKind: 'url' | 'text' | 'menu' }
  | { type: 'login.completed'; sessionId: string; accountId: string }
  | { type: 'login.failed'; sessionId: string; code: string; message: string }
  | { type: 'internal.handler_error'; error: string; original: AiAccountsEvent };

export type AiAccountsEventHandler = (event: AiAccountsEvent) => void;
