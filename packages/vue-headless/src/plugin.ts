import type { App } from 'vue';
import type {
  AiAccountsClient,
  AiAccountsEvent,
  AiAccountsEventHandler,
} from '@ai-accounts/ts-core';
import { aiAccountsKey, type AiAccountsContext } from './injection-keys';

export type AiAccountsPluginOptions = {
  client: AiAccountsClient;
  onEvent?: AiAccountsEventHandler;
};

export const aiAccountsPlugin = {
  install(app: App, options: AiAccountsPluginOptions) {
    const onEvent = options.onEvent ?? (() => {});

    const emit = (event: AiAccountsEvent) => {
      try {
        onEvent(event);
      } catch (err) {
        try {
          onEvent({
            type: 'internal.handler_error',
            error: err instanceof Error ? err.message : String(err),
            original: event,
          });
        } catch {
          // swallow — event bus must never propagate
        }
      }
    };

    const ctx: AiAccountsContext = { client: options.client, emit };
    app.provide(aiAccountsKey, ctx);
  },
};
