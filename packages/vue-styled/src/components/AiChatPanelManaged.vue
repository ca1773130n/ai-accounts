<script setup lang="ts">
/**
 * AiChatPanelManaged — caller-managed sibling to {@link AiChatPanel}.
 *
 * AiChatPanel (self-managed) drives chat state internally via useSmartChat.
 * AiChatPanelManaged (this component) requires the caller to own messages,
 * streamingContent, inputMessage, conversationId, and the
 * backend/account/model selection. Use this when your application has its
 * own conversation state machine and just wants the styled chat shell.
 *
 * Back-migrated from Agented (b2ee00d~1, restored Agented v0.5.5,
 * extracted upstream Agented v0.5.7).
 */
import { ref, watch, nextTick, computed } from 'vue';
import type { ChatMode, ProcessGroupType } from '@ai-accounts/ts-core';
import type { BackendResponseState, SynthesisStateRef } from '@ai-accounts/vue-headless';
import AiChatSelector from './AiChatSelector.vue';
import AllModeResponses from './AllModeResponses.vue';
import CompoundSynthesis from './CompoundSynthesis.vue';
import ChatBubble from './ChatBubble.vue';
import MessageActions from './MessageActions.vue';
import ProcessGroup from './ProcessGroup.vue';
import { backendDisplayName } from '../utils/assistantLabel';

/**
 * Loose message shape — accepts any caller's message representation.
 * Required: role, content. Optional: backend, timestamp.
 */
interface MessageLike {
  role: 'user' | 'assistant' | 'system' | 'tool' | string;
  content: string;
  backend?: string | null;
  model?: string | null;
  timestamp?: string | null;
}

/**
 * Inline process-group entry shape used by callers that own their own
 * group state (back-migrated from Agented `useProcessGroups`). Mirrors
 * the upstream `ProcessGroup.vue` per-row props plus the inline
 * `content` body that gets slotted into the expandable panel.
 */
interface ProcessGroupEntry {
  type: ProcessGroupType;
  label: string;
  content: string;
  timestamp?: string;
  isExpanded?: boolean;
}

const props = withDefaults(
  defineProps<{
    /** Caller-owned conversation messages. */
    messages?: MessageLike[];
    /** Whether the assistant is currently producing a response. */
    isProcessing?: boolean;
    /** Streaming text for the in-flight assistant bubble (single mode). */
    streamingContent?: string;
    /** Bound input value. */
    inputMessage?: string;
    /** Caller's conversation id (used by the welcome screen heading). */
    conversationId?: string | null;
    /** When true, render the FinalizationBanner. */
    canFinalize?: boolean;
    /** Disables the FinalizationBanner button while finalize is in flight. */
    isFinalizing?: boolean;
    /** SVG path(s) for the assistant avatar icon (welcome screen + thinking). */
    assistantIconPaths?: string[];
    /** Placeholder text for the input textarea. */
    inputPlaceholder?: string;
    /** Entity label for the welcome message, e.g. "hook", "command". */
    entityLabel?: string;
    /** Banner title when config is ready, e.g. "Hook Ready to Create!" */
    bannerTitle?: string;
    /** Banner button label, e.g. "Create Hook Now". */
    bannerButtonLabel?: string;
    /** Name of the detected entity for the banner, e.g. "my-custom-hook". */
    detectedEntityName?: string;
    /** Toggle the AiChatSelector bar above the chat. */
    showBackendSelector?: boolean;
    /** Current backend selection (kind, e.g. "auto" / "claude"). */
    selectedBackend?: string;
    /** Current account selection (BackendDTO id, or null for auto-pick). */
    selectedAccountId?: string | null;
    /** Current model selection. */
    selectedModel?: string | null;
    /** Hides input area when true. */
    readOnly?: boolean;
    /** Enable smart auto-scroll (preserve position when user scrolls up). */
    useSmartScroll?: boolean;
    /** Active process groups (tool calls, reasoning blocks) to display inline. */
    processGroups?: Map<string, ProcessGroupEntry>;
    /** Current chat mode (single/all/compound). */
    chatMode?: ChatMode;
    /** Per-backend responses for All/Compound mode. */
    backendResponses?: Map<string, BackendResponseState>;
    /** Synthesis state for Compound mode. */
    synthesisState?: SynthesisStateRef | null;
    /** Whether All/Compound mode is actively streaming. */
    isAllModeActive?: boolean;
    /**
     * When ``true``, render a toggle that signals "use the host app's
     * autonomous CLI runner" instead of CLIProxyAPI. The panel emits
     * ``update:useCliRunner`` when the user flips it; routing is the
     * caller's responsibility — the panel itself stays generic.
     *
     * Default ``false`` so panels embedded in CLIProxy-driven flows
     * (the original use case) keep their pure-token behavior unless a
     * host explicitly opts in.
     */
    useCliRunner?: boolean;
    /**
     * When ``true``, hide the CLI-runner toggle entirely. Use this for
     * read-only panels or contexts where the host doesn't support the
     * CLI runner path. Implies ``useCliRunner=false``.
     */
    hideCliRunnerToggle?: boolean;
  }>(),
  {
    messages: () => [],
    isProcessing: false,
    streamingContent: '',
    inputMessage: '',
    conversationId: null,
    canFinalize: false,
    isFinalizing: false,
    assistantIconPaths: () => [],
    inputPlaceholder: 'Type a message...',
    entityLabel: '',
    bannerTitle: '',
    bannerButtonLabel: '',
    detectedEntityName: '',
    showBackendSelector: false,
    selectedBackend: 'auto',
    selectedAccountId: null,
    selectedModel: null,
    readOnly: false,
    useSmartScroll: false,
    chatMode: 'single',
    synthesisState: null,
    isAllModeActive: false,
    useCliRunner: false,
    hideCliRunnerToggle: false,
  },
);

const emit = defineEmits<{
  (e: 'update:inputMessage', value: string): void;
  (e: 'send'): void;
  (e: 'keydown', event: KeyboardEvent): void;
  (e: 'finalize'): void;
  (e: 'update:selectedBackend', value: string): void;
  (e: 'update:selectedAccountId', value: string | null): void;
  (e: 'update:selectedModel', value: string | null): void;
  (e: 'update:chatMode', mode: ChatMode): void;
  (e: 'update:useCliRunner', value: boolean): void;
}>();

const chatContainer = ref<HTMLElement | null>(null);

/** Display name for the currently selected backend, used for the welcome
 *  screen + streaming / thinking indicators. Falls back to a generic
 *  "Assistant" while the backend is still 'auto' / unresolved (never "AI").
 *  Per-message bubbles derive their own name from `msg.backend` inside
 *  ChatBubble, so this is only the live-selection label. */
const assistantName = computed(() => backendDisplayName(props.selectedBackend) || 'Assistant');

/** Non-undefined view of `messages` for template iteration — withDefaults
 *  resolves the prop type with `| undefined` under exactOptionalPropertyTypes. */
const messagesArr = computed<MessageLike[]>(() => props.messages ?? []);

/** Non-undefined view of `inputMessage` for the textarea v-bind. */
const inputValue = computed<string>(() => props.inputMessage ?? '');

/** Non-undefined view of `assistantIconPaths` — `withDefaults` widens to
 *  `string[] | undefined` under `exactOptionalPropertyTypes`. */
const iconPaths = computed<string[]>(() => props.assistantIconPaths ?? []);

/**
 * Adapter for MessageActions, whose `allMessages` prop uses an
 * internally-defined `MessageLike` with `timestamp?: string` (no
 * `null`). Build the row without `timestamp` when ours is null/missing
 * so we satisfy `exactOptionalPropertyTypes`.
 */
const actionsMessages = computed(() =>
  messagesArr.value.map((m) => {
    const row: { role: string; content: string; timestamp?: string } = {
      role: m.role,
      content: m.content,
    };
    if (m.timestamp) row.timestamp = m.timestamp;
    return row;
  }),
);

/** Track whether user is near the bottom of the chat (for smart scroll). */
const isNearBottomState = ref(true);
const TOLERANCE_PX = 32; // ~2rem

function checkIsNearBottom(): boolean {
  const el = chatContainer.value;
  if (!el) return true;
  const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
  return distanceFromBottom <= TOLERANCE_PX;
}

function onChatScroll() {
  if (props.useSmartScroll) {
    isNearBottomState.value = checkIsNearBottom();
  }
}

function scrollToBottom() {
  nextTick(() => {
    if (chatContainer.value) {
      if (props.useSmartScroll && !isNearBottomState.value) return;
      chatContainer.value.scrollTop = chatContainer.value.scrollHeight;
    }
  });
}

function forceScrollToBottom() {
  isNearBottomState.value = true;
  nextTick(() => {
    if (chatContainer.value) {
      chatContainer.value.scrollTo({ top: chatContainer.value.scrollHeight, behavior: 'instant' });
    }
  });
}

/** Whether to show the "scroll to bottom" floating button. */
const showScrollButton = computed(() => props.useSmartScroll && !isNearBottomState.value);

// Auto-scroll when messages change. ChatBubble handles its own copy-code
// handler, so no attachCodeCopyHandlers wiring is needed here.
watch(() => messagesArr.value.length, scrollToBottom);

// Auto-scroll when streaming content updates
watch(() => props.streamingContent, scrollToBottom);

// Auto-scroll when processing starts (thinking indicator appears)
watch(
  () => props.isProcessing,
  (val) => {
    if (val) scrollToBottom();
  },
);

// Auto-scroll when all/compound mode backend responses update
watch(
  () => {
    if (!props.backendResponses) return 0;
    let total = 0;
    for (const r of props.backendResponses.values()) {
      total += r.content.length;
    }
    return total;
  },
  scrollToBottom,
);

// Auto-scroll when synthesis content updates (compound mode)
watch(() => props.synthesisState?.content?.length ?? 0, scrollToBottom);

function onInput(event: Event) {
  const textarea = event.target as HTMLTextAreaElement;
  emit('update:inputMessage', textarea.value);
  textarea.style.height = 'auto';
  textarea.style.height = Math.min(textarea.scrollHeight, 120) + 'px';
}

/** Compute the processGroups entries as an array for v-for iteration. */
const processGroupEntries = computed(() => {
  if (!props.processGroups) return [];
  return Array.from(props.processGroups.entries());
});
</script>

<template>
  <div class="chat-panel">
    <AiChatSelector
      v-if="showBackendSelector"
      :backend="selectedBackend ?? 'auto'"
      :account-id="selectedAccountId ?? null"
      :model="selectedModel ?? null"
      :chat-mode="chatMode ?? 'single'"
      @update:backend="emit('update:selectedBackend', $event)"
      @update:account-id="emit('update:selectedAccountId', $event)"
      @update:model="emit('update:selectedModel', $event)"
      @update:chat-mode="emit('update:chatMode', $event)"
    >
      <template #trailing>
        <slot name="selector-trailing" />
      </template>
    </AiChatSelector>

    <slot name="header-extra" />

    <!-- CLI runner toggle. Default off → caller routes through
         CLIProxyAPI (or whatever the host's pure-chat path is). When
         flipped on, the host should route the next send through its
         autonomous CLI runner so agents can use tools. The panel
         itself does no routing — it just exposes the flag.

         The pill is hidden entirely when ``hideCliRunnerToggle`` is
         set so panels in read-only or CLIProxy-only contexts don't
         confuse the user with a non-functional control. -->
    <div v-if="!hideCliRunnerToggle" class="cli-runner-toggle">
      <button
        type="button"
        class="cli-runner-toggle__btn"
        :class="{ 'cli-runner-toggle__btn--active': useCliRunner }"
        :aria-pressed="useCliRunner ? 'true' : 'false'"
        :title="useCliRunner
          ? 'CLI runner mode — agent uses tools (filesystem, shell, edits) in the project worktree'
          : 'CLIProxy mode — pure token chat, no tool use'"
        @click="emit('update:useCliRunner', !useCliRunner)"
      >
        <span class="cli-runner-toggle__dot" />
        <span class="cli-runner-toggle__label">
          {{ useCliRunner ? 'CLI runner' : 'CLIProxy' }}
        </span>
      </button>
    </div>

    <div class="chat-container" ref="chatContainer" @scroll="onChatScroll">
      <slot name="welcome">
        <div v-if="messagesArr.length === 0 && !isProcessing" class="chat-welcome">
          <div class="welcome-icon" :class="{ connecting: !conversationId }">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
              <path v-for="(d, i) in iconPaths" :key="i" :d="d" />
            </svg>
          </div>
          <h2>{{ conversationId ? 'Ready to chat' : `Connecting to ${assistantName}...` }}</h2>
          <p>{{ assistantName }} will guide you through designing your {{ entityLabel }}</p>
        </div>
      </slot>

      <!-- Message rendering — ChatBubble owns its own markdown + copy. -->
      <div
        v-for="(msg, index) in messagesArr"
        :key="index"
        class="message-wrapper"
        :class="msg.role"
      >
        <ChatBubble
          :role="(msg.role as 'user' | 'assistant' | 'system' | 'tool')"
          :content="msg.content"
          :timestamp="msg.timestamp ?? null"
          :backend="msg.backend ?? null"
          :model="msg.model ?? null"
          :avatar-paths="iconPaths"
          :skip-transition="messagesArr.length > 10 && index < messagesArr.length - 5"
        />
        <MessageActions
          v-if="!isProcessing || index < messagesArr.length - 1"
          :content="msg.content"
          :all-messages="index === messagesArr.length - 1 ? actionsMessages : []"
        />
      </div>

      <!-- Streaming indicator (single mode only) — uses ChatBubble. -->
      <ChatBubble
        v-if="
          isProcessing && (chatMode === 'single' || !chatMode) && streamingContent
        "
        role="assistant"
        :content="streamingContent ?? ''"
        :backend="selectedBackend ?? null"
        :model="selectedModel ?? null"
        :avatar-paths="iconPaths"
        :streaming="true"
      />

      <!-- All/Compound mode: tabbed multi-backend response display -->
      <AllModeResponses
        v-if="
          (chatMode === 'all' || chatMode === 'compound') &&
          backendResponses &&
          backendResponses.size > 0
        "
        :responses="backendResponses"
        :collapsible="chatMode === 'compound'"
      />

      <!-- Compound mode: synthesis result bubble -->
      <CompoundSynthesis
        v-if="synthesisState && synthesisState.status !== 'waiting'"
        :state="synthesisState"
      />

      <!-- Process groups (tool calls, reasoning, code execution) -->
      <template v-if="processGroupEntries.length > 0">
        <ProcessGroup
          v-for="[groupId, group] in processGroupEntries"
          :key="groupId"
          :id="groupId"
          :type="group.type"
          :label="group.label"
          :timestamp="group.timestamp ?? ''"
          :auto-collapse-ms="group.type === 'tool_call' ? 4000 : 2000"
        >
          <pre class="process-group-content">{{ group.content }}</pre>
        </ProcessGroup>
      </template>

      <!-- Pre-streaming "thinking" indicator -->
      <div v-if="isProcessing && !streamingContent" class="processing-indicator">
        <div class="dots">
          <span></span>
          <span></span>
          <span></span>
        </div>
        <span>{{ assistantName }} is thinking...</span>
      </div>

      <!-- Scroll-to-bottom button (only when useSmartScroll and user scrolled up) -->
      <button
        v-if="showScrollButton"
        class="scroll-to-bottom-btn"
        @click="forceScrollToBottom"
        title="Scroll to bottom"
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <polyline points="6 9 12 15 18 9" />
        </svg>
      </button>
    </div>

    <div v-if="canFinalize" class="convert-banner">
      <div class="banner-icon">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path v-for="(d, i) in iconPaths" :key="i" :d="d" />
          <path d="M20 6L9 17l-5-5" stroke-width="2.5" />
        </svg>
      </div>
      <div class="banner-content">
        <h3>{{ bannerTitle }}</h3>
        <p>
          {{ assistantName }} has designed your
          {{ entityLabel }}{{ detectedEntityName ? ': ' + detectedEntityName : '' }}. Click
          the button to finalize.
        </p>
      </div>
      <button
        class="btn btn-primary btn-convert"
        :disabled="isFinalizing"
        @click="emit('finalize')"
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M20 6L9 17l-5-5" />
        </svg>
        {{ isFinalizing ? 'Creating...' : bannerButtonLabel }}
      </button>
    </div>

    <div v-if="!readOnly" class="input-area">
      <div class="input-wrapper">
        <textarea
          :value="inputValue"
          @input="onInput($event)"
          :placeholder="inputPlaceholder"
          :disabled="isProcessing"
          @keydown="emit('keydown', $event)"
          rows="1"
        ></textarea>
        <button
          class="btn-send"
          :disabled="!inputValue.trim() || isProcessing"
          @click="emit('send')"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M22 2L11 13M22 2l-7 20-4-9-9-4 20-7z" />
          </svg>
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.chat-panel {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  min-width: 0;
  position: relative;
}

/* CLI-runner / CLIProxy mode pill. Sits above the chat container so
   the user always knows whether the agent has tool privileges. */
.cli-runner-toggle {
  display: flex;
  justify-content: flex-end;
  padding: 4px 12px 0;
}
.cli-runner-toggle__btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 10px;
  border-radius: 999px;
  border: 1px solid var(--aia-border, #27272a);
  background: var(--aia-bg-elevated, #141414);
  color: var(--aia-fg-muted, #a1a1aa);
  font-size: var(--aia-text-xs, 12px);
  font-weight: 500;
  cursor: pointer;
  transition: background 120ms ease, color 120ms ease, border-color 120ms ease;
}
.cli-runner-toggle__btn:hover {
  background: var(--aia-bg-hover, #1f1f1f);
  color: var(--aia-fg, #fafafa);
}
.cli-runner-toggle__btn--active {
  border-color: var(--aia-warning, #f59e0b);
  color: var(--aia-warning, #f59e0b);
  background: rgba(245, 158, 11, 0.08);
}
.cli-runner-toggle__btn--active:hover {
  background: rgba(245, 158, 11, 0.14);
}
.cli-runner-toggle__dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
  opacity: 0.6;
}
.cli-runner-toggle__btn--active .cli-runner-toggle__dot {
  opacity: 1;
  box-shadow: 0 0 6px currentColor;
}
.cli-runner-toggle__label {
  font-family: var(--aia-font-mono, ui-monospace, monospace);
  letter-spacing: 0.02em;
}

.chat-container {
  flex: 1;
  overflow-y: auto;
  padding: 24px;
  display: flex;
  flex-direction: column;
  gap: 16px;
  position: relative;
}

.chat-welcome {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 60px 20px;
  text-align: center;
}

.welcome-icon {
  width: 80px;
  height: 80px;
  background: var(--aia-bg-tertiary, var(--bg-tertiary, #1f1f1f));
  border-radius: 16px;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 24px;
}

.welcome-icon.connecting {
  animation: aia-managed-connect-pulse 1.5s infinite ease-in-out;
}

@keyframes aia-managed-connect-pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.6; transform: scale(0.95); }
}

.welcome-icon svg {
  width: 40px;
  height: 40px;
  color: var(--aia-violet, var(--accent-violet, #8855ff));
}

.chat-welcome h2 {
  margin: 0 0 8px 0;
  color: var(--aia-fg, var(--text-primary, #fafafa));
}

.chat-welcome p {
  margin: 0;
  color: var(--aia-fg-muted, var(--text-secondary, #a1a1aa));
}

.message-wrapper {
  position: relative;
  display: flex;
  flex-direction: column;
}

.message-wrapper.user {
  align-items: flex-end;
}

.message-wrapper.assistant {
  align-items: flex-start;
}

.message-wrapper:hover :deep(.message-actions) {
  opacity: 1;
  pointer-events: auto;
}

.process-group-content {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: var(--aia-font-mono, var(--font-mono, monospace));
  font-size: 12px;
  line-height: 1.4;
  color: var(--aia-fg-muted, var(--text-secondary, #a1a1aa));
}

.processing-indicator {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  background: var(--aia-bg-tertiary, var(--bg-tertiary, #1f1f1f));
  border-radius: 12px;
  align-self: flex-start;
  color: var(--aia-fg-muted, var(--text-secondary, #a1a1aa));
  font-size: 14px;
}

.dots {
  display: flex;
  gap: 4px;
}

.dots span {
  width: 8px;
  height: 8px;
  background: var(--aia-violet, var(--accent-violet, #8855ff));
  border-radius: 50%;
  animation: aia-managed-bounce 1.4s infinite ease-in-out both;
}

.dots span:nth-child(1) { animation-delay: -0.32s; }
.dots span:nth-child(2) { animation-delay: -0.16s; }

@keyframes aia-managed-bounce {
  0%, 80%, 100% { transform: scale(0); }
  40% { transform: scale(1); }
}

.scroll-to-bottom-btn {
  position: sticky;
  bottom: 8px;
  align-self: flex-end;
  width: 36px;
  height: 36px;
  border-radius: 50%;
  background: var(--aia-bg-secondary, var(--bg-secondary, #141414));
  border: 1px solid var(--aia-border, var(--border-default, #2a2a2a));
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: all 0.15s;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.2);
  z-index: 10;
}

.scroll-to-bottom-btn:hover {
  background: var(--aia-bg-tertiary, var(--bg-tertiary, #1f1f1f));
  border-color: var(--aia-violet, var(--accent-violet, #8855ff));
}

.scroll-to-bottom-btn svg {
  width: 18px;
  height: 18px;
  color: var(--aia-fg-muted, var(--text-secondary, #a1a1aa));
}

.convert-banner {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 16px 24px;
  background: linear-gradient(
    135deg,
    rgba(136, 85, 255, 0.1) 0%,
    rgba(0, 212, 255, 0.1) 100%
  );
  border-top: 1px solid var(--aia-violet, var(--accent-violet, #8855ff));
  animation: aia-managed-slide-in 0.3s ease;
}

@keyframes aia-managed-slide-in {
  from { opacity: 0; transform: translateY(10px); }
  to { opacity: 1; transform: translateY(0); }
}

.banner-icon {
  width: 48px;
  height: 48px;
  background: var(--aia-violet, var(--accent-violet, #8855ff));
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.banner-icon svg {
  width: 28px;
  height: 28px;
  color: #fff;
}

.banner-content {
  flex: 1;
}

.banner-content h3 {
  margin: 0 0 4px 0;
  font-size: 16px;
  font-weight: 600;
  color: var(--aia-fg, var(--text-primary, #fafafa));
}

.banner-content p {
  margin: 0;
  font-size: 13px;
  color: var(--aia-fg-muted, var(--text-secondary, #a1a1aa));
}

.btn-convert {
  padding: 12px 24px;
  font-size: 15px;
  font-weight: 600;
  background: linear-gradient(
    135deg,
    var(--aia-violet, var(--accent-violet, #8855ff)) 0%,
    var(--aia-cyan, var(--accent-cyan, #22d3ee)) 100%
  );
  border: none;
  color: #fff;
  border-radius: 8px;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  box-shadow: 0 4px 12px rgba(136, 85, 255, 0.3);
}

.btn-convert:hover:not(:disabled) {
  transform: translateY(-2px);
  box-shadow: 0 6px 16px rgba(136, 85, 255, 0.4);
}

.btn-convert:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-convert svg {
  width: 18px;
  height: 18px;
}

.input-area {
  padding: 16px 24px;
  border-top: 1px solid var(--aia-border, var(--border-default, #2a2a2a));
  background: var(--aia-bg-secondary, var(--bg-secondary, #141414));
}

.input-wrapper {
  display: flex;
  gap: 12px;
  background: var(--aia-bg-tertiary, var(--bg-tertiary, #1f1f1f));
  border: 1px solid var(--aia-border, var(--border-default, #2a2a2a));
  border-radius: 12px;
  padding: 12px 16px;
  transition: border-color 0.15s;
}

.input-wrapper:focus-within {
  border-color: var(--aia-violet, var(--accent-violet, #8855ff));
}

.input-wrapper textarea {
  flex: 1;
  background: transparent;
  border: none;
  color: var(--aia-fg, var(--text-primary, #fafafa));
  font-size: 14px;
  line-height: 1.5;
  resize: none;
  outline: none;
  min-height: 24px;
  max-height: 120px;
  font-family: inherit;
}

.input-wrapper textarea::placeholder {
  color: var(--aia-fg-subtle, var(--text-tertiary, #71717a));
}

.btn-send {
  width: 40px;
  height: 40px;
  background: var(--aia-violet, var(--accent-violet, #8855ff));
  border: none;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: all 0.15s;
  flex-shrink: 0;
}

.btn-send:hover:not(:disabled) {
  filter: brightness(1.1);
}

.btn-send:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-send svg {
  width: 20px;
  height: 20px;
  color: #fff;
}
</style>
