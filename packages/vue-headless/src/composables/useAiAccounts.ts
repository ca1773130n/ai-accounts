import { inject } from 'vue';
import { aiAccountsKey, type AiAccountsContext } from '../injection-keys';

export function useAiAccounts(): AiAccountsContext {
  const ctx = inject(aiAccountsKey);
  if (!ctx) {
    throw new Error(
      'useAiAccounts() called outside an app that installed aiAccountsPlugin'
    );
  }
  return ctx;
}
