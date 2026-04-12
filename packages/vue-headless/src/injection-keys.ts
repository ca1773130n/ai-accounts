import type { InjectionKey } from 'vue';
import type { AiAccountsClient, AiAccountsEvent } from '@ai-accounts/ts-core';

export type AiAccountsContext = {
  client: AiAccountsClient;
  emit: (event: AiAccountsEvent) => void;
};

export const aiAccountsKey: InjectionKey<AiAccountsContext> = Symbol('aiAccounts');
