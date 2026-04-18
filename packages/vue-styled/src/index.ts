import './styles/tokens.css';

export { default as AccountWizard } from './components/AccountWizard.vue';
export { default as OnboardingFlow } from './components/OnboardingFlow.vue';
export { default as LoginStream } from './components/LoginStream.vue';
export { default as BackendPicker } from './components/BackendPicker.vue';
export { default as AccountEditForm } from './components/AccountEditForm.vue';
// Legacy — kept for backward compat; prefer AiChatPanel
export { default as ChatPanel } from './components/ChatPanel.vue';
export { default as ChatMessage } from './components/ChatMessage.vue';

// Smart AI Chat Panel (v0.3)
export { default as AiChatPanel } from './components/AiChatPanel.vue';
export { default as ChatBubble } from './components/ChatBubble.vue';
export { default as ChatControls } from './components/ChatControls.vue';
export { default as ChatInput } from './components/ChatInput.vue';
export { default as AllModeResponses } from './components/AllModeResponses.vue';
export { default as CompoundSynthesis } from './components/CompoundSynthesis.vue';
export { default as ProcessGroup } from './components/ProcessGroup.vue';
export { default as MessageActions } from './components/MessageActions.vue';
export { default as FinalizationBanner } from './components/FinalizationBanner.vue';

// Helpers
export { forceFreshAccountPrompt } from './components/forceFreshAccountPrompt';

export const version = '0.3.3';

