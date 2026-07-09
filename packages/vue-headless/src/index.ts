export { useAccountWizard } from './useAccountWizard';
export type { UseAccountWizardOptions, UseAccountWizardReturn } from './useAccountWizard';
export { useOnboarding } from './useOnboarding';
export type { UseOnboardingOptions, UseOnboardingReturn } from './useOnboarding';

export { aiAccountsPlugin, type AiAccountsPluginOptions } from './plugin';
export { aiAccountsKey, type AiAccountsContext } from './injection-keys';
export { useAiAccounts } from './composables/useAiAccounts';
export { useBackendRegistry } from './composables/useBackendRegistry';
export {
  useLoginSession,
  type UseLoginSession,
  type LoginStatus,
} from './composables/useLoginSession';
export { useConversation } from './composables/useConversation';
export type { UseConversationReturn } from './composables/useConversation';
export { useSmartChat } from './composables/useSmartChat';
export type { UseSmartChatReturn, BackendResponseState, SynthesisStateRef } from './composables/useSmartChat';
export { useSmartScroll } from './composables/useSmartScroll';
export type { UseSmartScrollReturn } from './composables/useSmartScroll';
export { useProcessGroups } from './composables/useProcessGroups';
export type { ProcessGroup, UseProcessGroupsReturn } from './composables/useProcessGroups';
export { useStreamingParser } from './composables/useStreamingParser';
export type {
  UseStreamingParserOptions,
  UseStreamingParserReturn,
} from './composables/useStreamingParser';

export const version = '0.4.3';
