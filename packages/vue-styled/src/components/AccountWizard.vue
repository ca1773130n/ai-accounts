<script setup lang="ts">
/**
 * AccountWizard -- Step-by-step account registration flow.
 *
 * Ported to @ai-accounts/vue-styled (0.3.0-alpha.1). Uses plugin composables
 * (`useAiAccounts`, `useBackendRegistry`, `useLoginSession`) instead of
 * Agented-specific stores/APIs.
 *
 * Steps:
 *   1) Subscription check (has account? or skip)
 *   2) CLI & Config Setup (detect CLI, surface config path)
 *   3) Login (cli_browser / api_key / oauth_device via useLoginSession)
 *   4) Plan & Save (choose plan, set default, createBackend)
 *   5) Done
 */
import { ref, computed, watch, onMounted, onUnmounted, inject } from 'vue';
import type {
  LoginFlowKind,
  BackendMetadata,
  InstallResult,
  CliproxyInstallResult,
} from '@ai-accounts/ts-core';
import {
  useAiAccounts,
  useBackendRegistry,
  useLoginSession,
} from '@ai-accounts/vue-headless';
import LoginStream from './LoginStream.vue';
import BackendPicker from './BackendPicker.vue';

// ---------------------------------------------------------------------------
// Simple i18n stub — vue-styled is router/i18n-agnostic. Hosts can pass a
// `translate` prop to supply their own translator (e.g. wrapping vue-i18n).
// Falls back to hard-coded English when no translator is provided.
// ---------------------------------------------------------------------------
type Translator = (key: string, params?: Record<string, unknown>) => string;

const defaultT = (_key: string, fallback?: string | Record<string, unknown>): string => {
  if (typeof fallback === 'string') return fallback;
  if (fallback && typeof fallback === 'object') {
    return '';
  }
  const map: Record<string, string> = {
    'accountWizard.addAccount': 'Add Account',
    'accountWizard.stepSubscription': 'Subscription',
    'accountWizard.stepCliSetup': 'CLI Setup',
    'accountWizard.stepLogin': 'Login',
    'accountWizard.stepPlanSave': 'Plan & Save',
    'accountWizard.stepDone': 'Done',
    'accountWizard.yesHaveAccount': 'Yes, I have an account',
    'accountWizard.yesHaveAccountDesc': 'I already have a subscription for this backend',
    'accountWizard.noSkip': 'Skip for now',
    'accountWizard.noSkipDesc': 'I will set this up later',
    'accountWizard.accountName': 'Account name',
    'accountWizard.accountNamePlaceholder': 'e.g., Personal, Work',
    'accountWizard.accountNameHint':
      '(optional — leave blank to use the default config directory)',
    'accountWizard.copyForIncognito': 'Copy for Incognito',
    'accountWizard.copiedLabel': 'Copied!',
    'accountWizard.incognitoHint':
      'Press \u2318\u21E7N (Mac) or Ctrl+Shift+N (Windows/Linux) to open an incognito window, then paste the URL.',
    'accountWizard.email': 'Email',
    'accountWizard.emailPlaceholder': 'name@example.com',
    'accountWizard.emailHelp': 'Optional — used to tag the account',
    'accountWizard.cliInstalled': 'CLI detected',
    'accountWizard.cliNotInstalled': 'CLI not detected',
    'accountWizard.installCli': 'Install CLI',
    'accountWizard.configPath': 'Config path',
    'accountWizard.createDir': 'Create',
    'accountWizard.creating': 'Creating...',
    'accountWizard.configCreated': 'Created',
    'accountWizard.customizePath': 'Customize path',
    'accountWizard.apiKeyEnv': 'API key env var',
    'accountWizard.startingLogin': 'Starting login session...',
    'accountWizard.loginCompleted': 'Login completed',
    'accountWizard.tryAgain': 'Try again',
    'accountWizard.connectionLost': 'Connection lost',
    'accountWizard.send': 'Send',
    'accountWizard.waitingForResponse': 'Waiting for response...',
    'accountWizard.plan': 'Plan',
    'accountWizard.selectPlan': 'Select a plan',
    'accountWizard.setDefault': 'Set as default account',
    'accountWizard.saving': 'Saving...',
    'accountWizard.saveAccount': 'Save account',
    'accountWizard.accountCreated': 'Account created!',
    'accountWizard.addAnother': 'Add another',
    'accountWizard.doneNextBackend': 'Done',
    'accountWizard.continueBtn': 'Continue',
    'common.cancel': 'Cancel',
    'common.back': 'Back',
    'common.skip': 'Skip',
    // Tour spotlight copy — kept here as English fallbacks. Hosts that
    // pass a ``translate`` prop (e.g. Agented's vue-i18n bridge) get
    // localized versions from their own locale files.
    'accountWizard.tour.sub.yesno.title': 'Do you have an account?',
    'accountWizard.tour.sub.yesno.message': 'Pick whether you already have an account on this backend.',
    'accountWizard.tour.sub.name.title': 'Name this account',
    'accountWizard.tour.sub.name.message': 'Type a label so you can tell accounts apart later (e.g. "Personal", "Work"). Optional — leave blank to use a default.',
    'accountWizard.tour.sub.email.title': 'Account email',
    'accountWizard.tour.sub.email.message': 'Type the email tied to the account. We pass it as a login_hint on the sign-in page.',
    'accountWizard.tour.sub.next.title': 'Continue to CLI check',
    'accountWizard.tour.sub.next.message': 'Click Continue — we verify the CLI is installed and move to step 2.',
    'accountWizard.tour.cli.status.title': 'CLI install check',
    'accountWizard.tour.cli.status.message': 'Confirm the CLI is installed. If it isn\'t, the "Install" button will fetch it for you.',
    'accountWizard.tour.cli.path.title': 'Confirm the config directory',
    'accountWizard.tour.cli.path.message': 'This is the per-account config dir. We auto-create it on the next step. Click "Customize" if you need a different path.',
    'accountWizard.tour.cli.next.title': 'Launch the CLI',
    'accountWizard.tour.cli.next.message': 'Click Continue — we launch the CLI behind the scenes and move to step 3 (Sign in).',
    'accountWizard.tour.login.booting.title': 'Starting the CLI — pick your account type',
    'accountWizard.tour.login.booting.message': 'The CLI is booting in the background. While it starts, decide which login type fits your account: Pro / Max / Team subscription → pick "subscription". API usage billing (sk-ant-… / sk-… key) → pick "API key". 3rd-party platform (Bedrock / Foundry / Vertex AI) → pick "3rd-party". A menu appears in a moment with these options.',
    'accountWizard.tour.login.pickMethod.title': 'Pick how you sign in',
    'accountWizard.tour.login.pickMethod.message': 'Click the option that matches your account: option 1 = subscription (Pro / Max / Team), option 2 = API key billing, option 3 = 3rd-party platform. The browser will open right after.',
    'accountWizard.tour.login.authorize.title': 'Authorize in your browser',
    'accountWizard.tour.login.authorize.message': 'A browser tab has opened. Sign in with the email from step 1 and click Authorize. If the tab didn\'t open, click this URL.',
    'accountWizard.tour.login.paste.title': 'Paste the authorization code',
    'accountWizard.tour.login.paste.message': 'Copy the code from the redirect page and paste it here, then click Send. We verify it for ~5–10 s.',
    'accountWizard.tour.proxy.install.title': 'Install CLIProxyAPI',
    'accountWizard.tour.proxy.install.message': 'If the proxy isn\'t installed yet, click Install and wait. The proxy lets other tools reach this account through an OpenAI-compatible endpoint.',
    'accountWizard.tour.proxy.start.title': 'Register with the proxy',
    'accountWizard.tour.proxy.start.message': 'Click Start proxy registration to begin. A browser tab opens for the proxy OAuth.',
    'accountWizard.tour.proxy.callback.title': 'Paste the callback URL',
    'accountWizard.tour.proxy.callback.message': 'Copy the full localhost callback URL from your browser\'s address bar and paste it here, then click Submit. The redirect page may show "connection refused" — that\'s expected.',
    'accountWizard.tour.proxy.skip.title': 'Skip the proxy',
    'accountWizard.tour.proxy.skip.message': 'If you don\'t need the proxy, click Skip to jump to step 5.',
    'accountWizard.tour.plan.review.title': 'Review',
    'accountWizard.tour.plan.review.message': 'Check the values you entered. If anything looks wrong, click Back to fix it.',
    'accountWizard.tour.plan.pick.title': 'Pick a plan',
    'accountWizard.tour.plan.pick.message': 'Pro, Max, or API. The CLI told us which subscription it found in step 3 — override here if needed.',
    'accountWizard.tour.plan.default.title': 'Make it the default? (optional)',
    'accountWizard.tour.plan.default.message': 'Tick to mark this account as the backend\'s default.',
    'accountWizard.tour.plan.save.title': 'Save the account',
    'accountWizard.tour.plan.save.message': 'Click Save — the account is persisted and we move to the Done screen.',
    'accountWizard.tour.done.add.title': 'Add another account?',
    'accountWizard.tour.done.add.message': 'Click here to add another account on the same backend (e.g. a second Claude account).',
    'accountWizard.tour.done.nextBackend.title': 'Move to the next backend',
    'accountWizard.tour.done.nextBackend.message': 'Click here to advance the tour to the next backend (Codex / Gemini / OpenCode).',
  };
  return map[_key] ?? _key;
};

const props = defineProps<{
  /** If set, skip the backend picker and start directly with this kind. */
  initialBackendKind?: string;
  /** Display name override; defaults to registry metadata's display_name. */
  backendName?: string;
  /** Allow showing a "skip" button on the subscription step. */
  allowSkip?: boolean;
  /**
   * Optional translator. Receives a dotted key like `accountWizard.addAccount`
   * and an optional params object for interpolation. If not provided, falls
   * back to hard-coded English strings.
   */
  translate?: Translator;
}>();

const t: Translator = (key, params) => {
  if (props.translate) return props.translate(key, params);
  return defaultT(key, params as string | Record<string, unknown>);
};

const emit = defineEmits<{
  close: [];
  saved: [];
  skip: [];
  addAnother: [];
  done: [payload: { accountId: string }];
}>();

// ---------------------------------------------------------------------------
// Plugin composables
// ---------------------------------------------------------------------------
const { client, emit: busEmit } = useAiAccounts();
const backendRegistry = useBackendRegistry();
const loginSession = useLoginSession();

const backendKind = ref<string>(props.initialBackendKind ?? '');
const backendMeta = computed<BackendMetadata | undefined>(() =>
  backendKind.value ? backendRegistry.get(backendKind.value) : undefined
);
const backendName = computed<string>(
  () => props.backendName || backendMeta.value?.display_name || backendKind.value || 'Backend'
);

// Tour bridging: the host app (Agented) provides ``setTourTarget`` /
// ``setTourGuide`` via Vue ``provide()`` so the wizard can drive the
// tour spotlight per-substep ("highlight the Continue button on the
// CLI step" / "highlight the paste-code form on the Login step" / …).
// When the wizard is mounted standalone (no host), inject() falls back
// to no-op so the wizard still renders and works.
const setTourTarget = inject<(selector: string | null) => void>(
  'setTourTarget',
  () => {},
);
const setTourGuide = inject<(msg: string | null) => void>(
  'setTourGuide',
  () => {},
);
const setTourTitle = inject<(title: string | null) => void>(
  'setTourTitle',
  () => {},
);

/** A single substep — the spotlight anchors to ``selector`` and shows
 *  ``message`` in the tooltip balloon. ``done`` is a reactive predicate;
 *  when it becomes true, the spotlight advances automatically to the
 *  next substep. The actual TOUR_SUBSTEPS table + watchers are wired up
 *  AFTER every ref the predicates close over (see "Tour spotlight
 *  wiring" later in this file) — registering watchers up here would
 *  evaluate the source against refs that are still in the temporal
 *  dead zone, which surfaces as "Cannot read properties of undefined
 *  (reading 'el')" out of Vue's renderer downstream. */
interface TourSubstep {
  selector: string;
  /** Translator key for the tooltip header (e.g. ``accountWizard.tour.sub.yesno.title``).
   *  Resolved through the wizard's ``t()`` so it picks up the host
   *  app's locale. The default-translator map below ships English
   *  fallbacks so the wizard still works standalone. */
  titleKey?: string;
  /** Translator key for the tooltip body. */
  messageKey: string;
  done?: () => boolean;
}

// ---------------------------------------------------------------------------
// Wizard step management
// ---------------------------------------------------------------------------
type WizardStep = 'subscription' | 'cli' | 'login' | 'proxy' | 'plan' | 'done';
const STEP_ORDER: WizardStep[] = ['subscription', 'cli', 'login', 'proxy', 'plan', 'done'];
const currentStep = ref<WizardStep>('subscription');

// Backends that the CLIProxyAPI supports registering. Other backends skip
// the proxy step entirely.
const PROXY_SUPPORTED_KINDS = ['claude', 'codex', 'gemini'] as const;
const supportsProxy = computed(() =>
  PROXY_SUPPORTED_KINDS.includes(
    (backendKind.value ?? '') as (typeof PROXY_SUPPORTED_KINDS)[number]
  )
);

const VISIBLE_STEPS = computed<WizardStep[]>(() => {
  const base: WizardStep[] = ['subscription', 'cli', 'login'];
  if (supportsProxy.value) base.push('proxy');
  base.push('plan');
  return base;
});

const currentStepIndex = computed(() =>
  VISIBLE_STEPS.value.indexOf(currentStep.value)
);

const stepLabels = computed<Record<WizardStep, string>>(() => ({
  subscription: t('accountWizard.stepSubscription'),
  cli: t('accountWizard.stepCliSetup'),
  login: t('accountWizard.stepLogin'),
  proxy: 'API Proxy',
  plan: t('accountWizard.stepPlanSave'),
  done: t('accountWizard.stepDone'),
}));

function goNext() {
  const visible = VISIBLE_STEPS.value;
  const idx = visible.indexOf(currentStep.value);
  if (idx >= 0 && idx < visible.length - 1) {
    currentStep.value = visible[idx + 1]!;
  } else if (currentStep.value === visible[visible.length - 1]) {
    currentStep.value = 'done';
  }
}

function goPrev() {
  const visible = VISIBLE_STEPS.value;
  const idx = visible.indexOf(currentStep.value);
  if (idx > 0) {
    currentStep.value = visible[idx - 1]!;
  }
}

// ---------------------------------------------------------------------------
// Step 1: Subscription Check
// ---------------------------------------------------------------------------
const hasSubscription = ref<'yes' | 'no' | ''>('');
const accountName = ref('');
const email = ref('');

// Account name is OPTIONAL — if left blank, we derive a default at save time
// from the backend metadata's display_name. Do NOT gate goNext on name.
const subscriptionValid = computed(() => hasSubscription.value !== '');

function handleSubscriptionNext() {
  if (hasSubscription.value === 'no') {
    skipWizard();
    return;
  }
  goNext();
}

// ---------------------------------------------------------------------------
// Config path & env var auto-generation
// ---------------------------------------------------------------------------
const configPath = ref('');
const configPathManuallyEdited = ref(false);

function generateSlug(name: string): string {
  return name.toLowerCase().replace(/\s+/g, '').replace(/[^a-z0-9]/g, '');
}

const DEFAULT_CONFIG_DIR_MAP: Record<string, string> = {
  claude: '.claude',
  codex: '.codex',
  gemini: '.gemini',
  opencode: '.opencode',
};

/**
 * Returns the default per-kind config directory (e.g. ~/.claude) that is
 * used when the user leaves the account name blank. Exposed so callers/tests
 * can reuse the same mapping.
 */
function suggestDefaultConfigPath(kind: string | undefined): string {
  const k = kind || '';
  const base = DEFAULT_CONFIG_DIR_MAP[k] || (k ? `.${k}` : '.backend');
  return `~/${base}`;
}

function suggestConfigPath() {
  if (configPathManuallyEdited.value) return;
  const name = accountName.value.trim();
  if (!name) {
    // Blank account name → default config directory (~/.claude, ~/.codex, …).
    configPath.value = suggestDefaultConfigPath(backendKind.value);
    return;
  }
  const slug = generateSlug(name);
  const base =
    DEFAULT_CONFIG_DIR_MAP[backendKind.value || ''] ||
    (backendKind.value ? `.${backendKind.value}` : '.backend');
  configPath.value = `~/${base}-${slug}`;
}

/**
 * When the user leaves the account name blank we still need a non-empty
 * `display_name` for the DB row. We prefer the backend metadata's
 * `display_name` (e.g. "Claude Code"); if that's unavailable we fall back
 * to the literal string "default", matching Agented's behavior.
 */
function resolveDisplayName(fallback: string | undefined): string {
  const trimmed = accountName.value.trim();
  if (trimmed) return trimmed;
  return (fallback && fallback.trim()) || 'default';
}

// Kept for backward compat with the older review card / save flow that
// echoed the env-var name back to the user. New copy hides it
// completely; the api-key-vs-OAuth choice is decided by the CLI's
// own login-method menu in step 3, so pre-baking a var name here was
// confusing for OAuth-only flows. Still computed so any host that
// reaches into ``apiKeyEnv`` programmatically keeps working.
const apiKeyEnv = computed(() => {
  const name = accountName.value.trim();
  if (!name) return '';
  const envMap: Record<string, string> = {
    claude: 'ANTHROPIC',
    codex: 'OPENAI',
    gemini: 'GOOGLE',
    opencode: 'OPENCODE',
  };
  const kind = backendKind.value || '';
  const prefix = envMap[kind] || (kind ? kind.toUpperCase() : 'BACKEND');
  const suffix = generateSlug(name).replace(/-/g, '_').toUpperCase();
  return `${prefix}_API_KEY_${suffix}`;
});

// ---------------------------------------------------------------------------
// Step 2: CLI Setup — uses draft backend + detectBackend() for install check.
// Note: CLI *installation* and config directory *creation* are Agented-only
// operations (no equivalent in the ai-accounts API); those actions are
// intentionally omitted. The wizard still surfaces install status.
// ---------------------------------------------------------------------------
const cliInstalled = ref(false);
const cliVersion = ref('');
const isCheckingCli = ref(false);
const isInstallingCli = ref(false);
// Surface for backend-reported errors when the CLI can't materialise the
// config directory on launch (e.g. permission denied). Auto-create itself
// happens server-side as part of the login orchestrator startup.
const dirError = ref('');
const installError = ref('');

async function checkCli() {
  if (!backendKind.value) return;
  isCheckingCli.value = true;
  try {
    // In 0.3.0-alpha.1, detect is a per-backend-id call. Without a created
    // backend yet, read the install_check metadata to show expected command.
    // Full detection happens once the backend is created in saveAccount().
    const meta = backendRegistry.get(backendKind.value);
    cliInstalled.value = !!meta; // assume available if metadata known
    cliVersion.value = '';
  } catch (e: unknown) {
    console.warn('[AccountWizard] CLI check failed:', e);
  } finally {
    isCheckingCli.value = false;
  }
}

const installResult = ref<InstallResult | null>(null);

async function installCli() {
  if (!backendKind.value) return;
  isInstallingCli.value = true;
  installError.value = '';
  installResult.value = null;
  try {
    const res = await client.installBackendCli(backendKind.value);
    installResult.value = res;
    if (res.success) {
      cliInstalled.value = true;
      cliVersion.value = '';
    } else {
      installError.value = res.stderr || res.stdout || 'Installation failed';
    }
  } catch (e: unknown) {
    installError.value = e instanceof Error ? e.message : String(e);
    installResult.value = {
      kind: backendKind.value,
      success: false,
      display: 'install failed',
      stdout: '',
      stderr: installError.value,
      exit_code: -1,
      binary_path: null,
    };
  } finally {
    isInstallingCli.value = false;
  }
}

onMounted(async () => {
  if (!backendRegistry.loaded.value) {
    await backendRegistry.load();
  }
  checkCli();
  // Pre-fill the default config path so it's visible even before the user
  // types an account name. Ported from Agented f52c55a.
  suggestConfigPath();
  setTourTarget('[data-tour="account-wizard"]');
  busEmit({ type: 'wizard.opened', backendKind: backendKind.value });
  // Kick off a CLIProxyAPI status check so the proxy step can render
  // install/register UI without a spinner lag.
  checkCliproxyStatus();
});

// Re-suggest the default path whenever the selected backend changes
// (e.g. user picks a kind on the BackendPicker step).
watch(backendKind, () => {
  if (!configPathManuallyEdited.value) suggestConfigPath();
});

// Clear stale dir-error when config path changes — the next CLI launch
// will rediscover whether the new path is materialisable.
watch(configPath, () => {
  dirError.value = '';
});

// ---------------------------------------------------------------------------
// Step 3: Login — delegates to useLoginSession + <LoginStream>.
// The login session machine handles URL prompts, text prompts, stdout, and
// terminal-state transitions. Gemini-specific direct OAuth, PTY SSE, and
// per-kind option/question UI are replaced by the unified login protocol.
// ---------------------------------------------------------------------------
const draftAccountId = ref<string>(''); // backend row id once created

watch(currentStep, async (_step) => {
  // The substep-reset and the spotlight pushes live in the dedicated
  // tour-spotlight wiring further down (after every ref the predicates
  // close over). Here we only auto-start login.
  if (currentStep.value === 'login' && loginSession.status.value === 'idle') {
    await startUnifiedLogin();
  }
}, { immediate: true });

async function startUnifiedLogin() {
  const meta = backendMeta.value;
  if (!meta) return;
  try {
    // Ensure a draft backend row exists so login can attach to it.
    if (!draftAccountId.value) {
      const created = await client.createBackend({
        kind: meta.kind,
        display_name: resolveDisplayName(meta.display_name),
        config: buildDraftConfig(),
      });
      draftAccountId.value = created.id;
    }
    // Pick the first available login flow (cli_browser > oauth_device > api_key).
    const flow = pickLoginFlow(meta);
    busEmit({
      type: 'wizard.step',
      backendKind: meta.kind,
      step: 'login.start',
    });
    await loginSession.start(draftAccountId.value, flow, collectInputs(meta));
  } catch (e: unknown) {
    console.warn('[AccountWizard] login failed:', e);
  }
}

function pickLoginFlow(meta: BackendMetadata): LoginFlowKind {
  const available = meta.login_flows.map((f) => f.kind);
  if (available.includes('cli_browser')) return 'cli_browser';
  if (available.includes('oauth_device')) return 'oauth_device';
  return 'api_key';
}

function collectInputs(_meta: BackendMetadata): Record<string, string> {
  // For cli_browser / oauth_device, no inputs are required. For api_key, the
  // user would be prompted via textPrompt in the stream. We keep this empty
  // and let useLoginSession surface prompts.
  return {};
}

function buildDraftConfig(): Record<string, unknown> {
  // ``api_key_env`` is intentionally NOT pre-populated here. The
  // api-key-vs-OAuth distinction is decided in step 3 by the CLI's
  // own login-method menu (Claude Pro/Max → OAuth, "API Usage Billing"
  // → API key). If the user picks the API-key flow, the login flow
  // captures the credential into the vault directly and surfaces it
  // through ``backend.config`` from the sidecar — pre-baking an env
  // var name here only confused users who never wanted a key flow.
  return {
    email: email.value.trim() || undefined,
    config_path: configPath.value.trim() || undefined,
  };
}

watch(
  () => loginSession.status.value,
  (status) => {
    if (status === 'complete' && currentStep.value === 'login') {
      goNext();
    }
  }
);

onUnmounted(() => {
  setTourGuide(null);
  setTourTarget(null);
  if (loginSession.status.value === 'running') {
    loginSession.cancel().catch(() => {});
  }
});

// Convenience aliases so the template's existing bindings keep working.
// The unified `loginSession` composable is the source of truth; these refs
// reflect its state in the legacy template shape.
const loginStatus = computed<'idle' | 'connecting' | 'streaming' | 'completed' | 'error'>(() => {
  switch (loginSession.status.value) {
    case 'running': {
      const hasAnyPrompt =
        loginSession.urlPrompt.value ||
        loginSession.textPrompt.value ||
        loginSession.menuPrompt.value ||
        loginSession.stdoutLines.value.length > 0;
      return hasAnyPrompt ? 'streaming' : 'connecting';
    }
    case 'complete':
      return 'completed';
    case 'failed':
    case 'cancelled':
      return 'error';
    default:
      return 'idle';
  }
});
const loginError = computed(() => loginSession.errorMessage.value || '');

function cleanupLogin() {
  if (loginSession.status.value === 'running') {
    loginSession.cancel().catch(() => {});
  }
}

// ---------------------------------------------------------------------------
// Step 4: Plan & Save
// ---------------------------------------------------------------------------
const planOptions = computed(() => backendMeta.value?.plan_options ?? []);
const selectedPlan = ref('');
const isDefault = ref(false);
const isSaving = ref(false);
const saveError = ref('');

// ---------------------------------------------------------------------------
// Tour spotlight wiring — declared HERE, after every ref the predicates
// reference (hasSubscription, accountName, email, cliInstalled,
// selectedPlan, currentStep). Putting this earlier in the file evaluates
// the watch source while those refs are in their temporal dead zone, and
// the resulting TDZ access surfaces as a Vue renderer crash
// ("Cannot read properties of undefined (reading 'el')") rather than a
// readable ReferenceError, because Vue catches the throw inside its own
// errorHandler and continues patching against an undefined VNode.
// ---------------------------------------------------------------------------
const TOUR_SUBSTEPS: Record<WizardStep, TourSubstep[]> = {
  subscription: [
    {
      selector: '[data-tour="wiz-sub-yesno"]',
      titleKey: 'accountWizard.tour.sub.yesno.title',
      messageKey: 'accountWizard.tour.sub.yesno.message',
      done: () => hasSubscription.value !== '',
    },
    {
      selector: '#wiz-name',
      titleKey: 'accountWizard.tour.sub.name.title',
      messageKey: 'accountWizard.tour.sub.name.message',
      done: () => accountName.value.trim().length > 0,
    },
    {
      selector: '#wiz-email',
      titleKey: 'accountWizard.tour.sub.email.title',
      messageKey: 'accountWizard.tour.sub.email.message',
      done: () => /.+@.+/.test(email.value),
    },
    {
      selector: '[data-tour="wiz-sub-next"]',
      titleKey: 'accountWizard.tour.sub.next.title',
      messageKey: 'accountWizard.tour.sub.next.message',
    },
  ],
  cli: [
    {
      selector: '[data-tour="wiz-cli-status"]',
      titleKey: 'accountWizard.tour.cli.status.title',
      messageKey: 'accountWizard.tour.cli.status.message',
      done: () => cliInstalled.value,
    },
    {
      selector: '[data-tour="wiz-cli-path"]',
      titleKey: 'accountWizard.tour.cli.path.title',
      messageKey: 'accountWizard.tour.cli.path.message',
    },
    {
      selector: '[data-tour="wiz-cli-next"]',
      titleKey: 'accountWizard.tour.cli.next.title',
      messageKey: 'accountWizard.tour.cli.next.message',
    },
  ],
  login: [
    // 1) CLI is booting + the user needs to know which option to pick
    //    when its login-method menu appears. The "browser opens" hint
    //    is intentionally NOT here — it would be a lie until urlPrompt
    //    actually fires, which is several seconds later.
    {
      selector: '[data-tour="wiz-login-stream"]',
      titleKey: 'accountWizard.tour.login.booting.title',
      messageKey: 'accountWizard.tour.login.booting.message',
      // Advance as soon as the CLI emits its login-method menu (so the
      // user gets the more specific "Pick the option" tooltip) OR
      // straight to URL if the menu was bypassed.
      done: () =>
        !!loginSession.menuPrompt.value || !!loginSession.urlPrompt.value,
    },
    // 2) Login-method menu visible — point at the menu and re-state
    //    the choice in concrete terms ("subscription = 1, API key = 2").
    {
      selector: '[data-tour="wiz-login-stream"]',
      titleKey: 'accountWizard.tour.login.pickMethod.title',
      messageKey: 'accountWizard.tour.login.pickMethod.message',
      done: () => !!loginSession.urlPrompt.value,
    },
    // 3) URL has been shown; the browser opened (or the user can click
    //    the URL). Now we mention the browser explicitly.
    {
      selector: '[data-tour="wiz-login-url"]',
      titleKey: 'accountWizard.tour.login.authorize.title',
      messageKey: 'accountWizard.tour.login.authorize.message',
      done: () =>
        !!loginSession.textPrompt.value || returnedFromOAuthTab.value,
    },
    // 4) User returned from the OAuth tab (or the CLI emitted its own
    //    paste prompt). Spotlight on the paste form.
    {
      selector: '[data-tour="wiz-login-paste"]',
      titleKey: 'accountWizard.tour.login.paste.title',
      messageKey: 'accountWizard.tour.login.paste.message',
    },
  ],
  proxy: [
    {
      selector: '[data-tour="wiz-proxy-install"]',
      titleKey: 'accountWizard.tour.proxy.install.title',
      messageKey: 'accountWizard.tour.proxy.install.message',
    },
    {
      selector: '[data-tour="wiz-proxy-start"]',
      titleKey: 'accountWizard.tour.proxy.start.title',
      messageKey: 'accountWizard.tour.proxy.start.message',
    },
    {
      selector: '[data-tour="wiz-proxy-callback"]',
      titleKey: 'accountWizard.tour.proxy.callback.title',
      messageKey: 'accountWizard.tour.proxy.callback.message',
    },
    {
      selector: '[data-tour="wiz-proxy-skip"]',
      titleKey: 'accountWizard.tour.proxy.skip.title',
      messageKey: 'accountWizard.tour.proxy.skip.message',
    },
  ],
  plan: [
    {
      selector: '[data-tour="wiz-plan-review"]',
      titleKey: 'accountWizard.tour.plan.review.title',
      messageKey: 'accountWizard.tour.plan.review.message',
    },
    {
      selector: '#wiz-plan',
      titleKey: 'accountWizard.tour.plan.pick.title',
      messageKey: 'accountWizard.tour.plan.pick.message',
      done: () => selectedPlan.value !== '',
    },
    {
      selector: '[data-tour="wiz-plan-default"]',
      titleKey: 'accountWizard.tour.plan.default.title',
      messageKey: 'accountWizard.tour.plan.default.message',
    },
    {
      selector: '[data-tour="wiz-plan-save"]',
      titleKey: 'accountWizard.tour.plan.save.title',
      messageKey: 'accountWizard.tour.plan.save.message',
    },
  ],
  done: [
    {
      selector: '[data-tour="wiz-done-add"]',
      titleKey: 'accountWizard.tour.done.add.title',
      messageKey: 'accountWizard.tour.done.add.message',
    },
    {
      selector: '[data-tour="wiz-done-next-backend"]',
      titleKey: 'accountWizard.tour.done.nextBackend.title',
      messageKey: 'accountWizard.tour.done.nextBackend.message',
    },
  ],
};

const tourSubstepIndex = ref(0);
const activeTourSubstep = computed<TourSubstep | null>(() => {
  const list = TOUR_SUBSTEPS[currentStep.value] ?? [];
  return list[tourSubstepIndex.value] ?? null;
});

// Heuristic for "user opened the OAuth tab and came back": flips true
// the next time this tab regains visibility AFTER the OAuth URL has
// been shown. Used to advance the login spotlight from the URL substep
// to the paste-code substep without waiting for the CLI's slower
// "Paste code here >" prompt to appear.
const returnedFromOAuthTab = ref(false);
let lastDocumentHidden = false;
function _trackVisibility() {
  if (typeof document === 'undefined') return;
  if (document.visibilityState === 'hidden') {
    lastDocumentHidden = true;
  } else if (document.visibilityState === 'visible' && lastDocumentHidden) {
    if (currentStep.value === 'login' && loginSession.urlPrompt.value) {
      returnedFromOAuthTab.value = true;
    }
    lastDocumentHidden = false;
  }
}
if (typeof document !== 'undefined') {
  document.addEventListener('visibilitychange', _trackVisibility);
}
onUnmounted(() => {
  if (typeof document !== 'undefined') {
    document.removeEventListener('visibilitychange', _trackVisibility);
  }
});

watch(
  () => activeTourSubstep.value?.done?.() ?? false,
  (isDone) => {
    if (!isDone) return;
    const list = TOUR_SUBSTEPS[currentStep.value] ?? [];
    if (tourSubstepIndex.value < list.length - 1) {
      tourSubstepIndex.value++;
    }
  },
);

watch(activeTourSubstep, (sub) => {
  if (sub) {
    setTourTarget(sub.selector);
    setTourGuide(t(sub.messageKey));
    setTourTitle(sub.titleKey ? t(sub.titleKey) : null);
  } else {
    setTourTarget(`[data-tour="wiz-${currentStep.value}"]`);
    setTourGuide(null);
    setTourTitle(null);
  }
});

// Reset substep index whenever the wizard advances to a new step so the
// spotlight starts at the first element of the new step. Also reset the
// OAuth-tab return heuristic so an old visibility flip from a previous
// session doesn't leak into a new login.
watch(currentStep, () => {
  tourSubstepIndex.value = 0;
  returnedFromOAuthTab.value = false;
});

// ---------------------------------------------------------------------------
// CLIProxyAPI registration step (Step 3.5) — optional register-with-proxy
// flow backed by POST /api/v1/cliproxy/login/begin and /callback-forward.
// ---------------------------------------------------------------------------
type ProxyLoginStatus =
  | 'idle'
  | 'running'
  | 'device_auth'
  | 'success'
  | 'skipped'
  | 'error';

const proxyLoginStatus = ref<ProxyLoginStatus>('idle');
const proxyLoginMessage = ref('');
const proxyOauthUrl = ref('');
const proxyDeviceCode = ref('');
const proxyCallbackUrl = ref('');
const proxyCallbackError = ref('');

const cliproxyInstalled = ref(false);
const cliproxyInstalling = ref(false);
const cliproxyInstallResult = ref<CliproxyInstallResult | null>(null);
const cliproxyStatusChecked = ref(false);

async function checkCliproxyStatus() {
  try {
    const s = await client.cliproxyStatus();
    cliproxyInstalled.value = s.installed;
  } catch (e: unknown) {
    console.warn('[AccountWizard] cliproxy status check failed:', e);
    cliproxyInstalled.value = false;
  } finally {
    cliproxyStatusChecked.value = true;
  }
}

async function installCliproxy() {
  cliproxyInstalling.value = true;
  cliproxyInstallResult.value = null;
  try {
    const res = await client.cliproxyInstall();
    cliproxyInstallResult.value = res;
    if (res.success) {
      cliproxyInstalled.value = true;
    }
  } catch (e: unknown) {
    cliproxyInstallResult.value = {
      success: false,
      display: 'install failed',
      stdout: '',
      stderr: e instanceof Error ? e.message : String(e),
      binary_path: null,
    };
  } finally {
    cliproxyInstalling.value = false;
  }
}

function resetProxyLogin() {
  proxyLoginStatus.value = 'idle';
  proxyLoginMessage.value = '';
  proxyOauthUrl.value = '';
  proxyDeviceCode.value = '';
  proxyCallbackUrl.value = '';
  proxyCallbackError.value = '';
}

async function runProxyLogin() {
  if (!backendKind.value) return;
  proxyLoginStatus.value = 'running';
  proxyLoginMessage.value = `Registering ${backendName.value} account with API proxy…`;
  proxyCallbackError.value = '';

  try {
    const res = await client.cliproxyLoginBegin(
      backendKind.value,
      configPath.value?.trim() || undefined
    );
    proxyLoginMessage.value = res.message;
    if (res.status === 'imported') {
      proxyLoginStatus.value = 'success';
    } else if (res.status === 'started' && res.oauth_url) {
      proxyLoginStatus.value = 'device_auth';
      proxyOauthUrl.value = res.oauth_url;
      proxyDeviceCode.value = res.device_code ?? '';
      // Auto-open the OAuth URL in the user's browser
      window.open(res.oauth_url, '_blank', 'noopener');
      if (res.device_code) {
        proxyLoginMessage.value = `Open the URL and enter code ${res.device_code}`;
      } else {
        proxyLoginMessage.value =
          'Complete OAuth in the browser; paste the callback URL below if it fails to redirect';
      }
    } else if (res.status === 'skipped') {
      proxyLoginStatus.value = 'skipped';
    } else {
      proxyLoginStatus.value = 'error';
    }
  } catch (e: unknown) {
    proxyLoginStatus.value = 'error';
    proxyLoginMessage.value = e instanceof Error ? e.message : String(e);
  }
}

async function submitProxyCallback() {
  if (!proxyCallbackUrl.value.trim()) return;
  proxyCallbackError.value = '';
  try {
    const res = await client.cliproxyCallbackForward(
      proxyCallbackUrl.value.trim()
    );
    if (res.status === 'completed') {
      proxyLoginStatus.value = 'success';
      proxyLoginMessage.value = 'API proxy login completed';
    } else {
      proxyCallbackError.value = res.message;
    }
  } catch (e: unknown) {
    proxyCallbackError.value = e instanceof Error ? e.message : String(e);
  }
}

async function saveAccount() {
  isSaving.value = true;
  saveError.value = '';
  try {
    // If login already created/attached the backend, update metadata.
    // Otherwise create a fresh backend row.
    const meta = backendMeta.value;
    if (!meta) throw new Error('No backend metadata available');

    const config = {
      ...buildDraftConfig(),
      plan: selectedPlan.value || undefined,
      is_default: isDefault.value,
    };

    if (draftAccountId.value) {
      await client.updateBackend(draftAccountId.value, {
        display_name: resolveDisplayName(meta.display_name),
        config,
      });
    } else {
      const created = await client.createBackend({
        kind: meta.kind,
        display_name: resolveDisplayName(meta.display_name),
        config,
      });
      draftAccountId.value = created.id;
    }

    currentStep.value = 'done';
    emit('saved');
    busEmit({
      type: 'wizard.account.created',
      backendKind: meta.kind,
      accountId: draftAccountId.value,
    });
    busEmit({
      type: 'wizard.step',
      backendKind: meta.kind,
      step: 'done',
    });
  } catch (e: unknown) {
    saveError.value = e instanceof Error ? e.message : 'Failed to save account';
  } finally {
    isSaving.value = false;
  }
}

function addAnotherAccount() {
  // Reset form
  hasSubscription.value = '';
  accountName.value = '';
  email.value = '';
  configPath.value = '';
  configPathManuallyEdited.value = false;
  selectedPlan.value = '';
  isDefault.value = false;
  cleanupLogin();
  loginSession.reset();
  resetProxyLogin();
  draftAccountId.value = '';
  dirError.value = '';
  currentStep.value = 'subscription';
  // Re-apply the default config dir so the hint is visible immediately
  // for the next account (mirrors Agented f52c55a addAnotherAccount reset).
  suggestConfigPath();
  emit('addAnother');
  if (backendKind.value) {
    busEmit({ type: 'wizard.step', backendKind: backendKind.value, step: 'add-another' });
  }
}

function closeWizard() {
  if (backendKind.value) {
    busEmit({ type: 'wizard.closed', backendKind: backendKind.value, reason: 'cancel' });
  }
  emit('close');
}

function doneWizard() {
  if (backendKind.value) {
    busEmit({ type: 'wizard.closed', backendKind: backendKind.value, reason: 'done' });
  }
  emit('done', { accountId: draftAccountId.value });
}

function skipWizard() {
  if (backendKind.value) {
    busEmit({ type: 'wizard.closed', backendKind: backendKind.value, reason: 'skip' });
  }
  emit('skip');
}
</script>

<template>
  <div class="wizard-container" data-tour="account-wizard">
    <div class="wizard-header">
      <h3>{{ t('accountWizard.addAccount') }}</h3>
      <button class="wizard-close" @click="closeWizard">&times;</button>
    </div>

    <!-- Step 0: Backend picker (if no initialBackendKind was provided) -->
    <div v-if="!backendKind" class="wizard-step">
      <div class="step-body">
        <p class="step-question">Select a backend to connect:</p>
        <BackendPicker @pick="(k: string) => { backendKind = k; checkCli(); }" />
      </div>
      <div class="step-actions">
        <button class="btn btn-secondary" @click="closeWizard">{{ t('common.cancel') }}</button>
      </div>
    </div>

    <!-- Step indicators -->
    <div v-else-if="currentStep !== 'done'" class="wizard-steps">
      <div
        v-for="(step, idx) in VISIBLE_STEPS"
        :key="step"
        class="step-indicator"
        :class="{
          active: currentStep === step,
          completed: currentStepIndex > idx,
          clickable: idx < currentStepIndex,
        }"
        @click="idx < currentStepIndex ? (currentStep = step) : undefined"
      >
        <span class="step-number">
          <template v-if="currentStepIndex > idx">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" width="12" height="12">
              <polyline points="20 6 9 17 4 12"/>
            </svg>
          </template>
          <template v-else>{{ idx + 1 }}</template>
        </span>
        <span class="step-label">{{ stepLabels[step] }}</span>
      </div>
    </div>

    <!-- Step 1: Subscription -->
    <div v-if="backendKind && currentStep === 'subscription'" class="wizard-step" data-tour="wiz-subscription">
      <div class="step-body">
        <p class="step-question">Do you already have a {{ backendName }} account?</p>

        <div class="radio-group" data-tour="wiz-sub-yesno">
          <label class="radio-card" :class="{ selected: hasSubscription === 'yes' }">
            <input type="radio" v-model="hasSubscription" value="yes" />
            <div class="radio-card-content">
              <span class="radio-card-title">{{ t('accountWizard.yesHaveAccount') }}</span>
              <span class="radio-card-desc">{{ t('accountWizard.yesHaveAccountDesc') }}</span>
            </div>
          </label>
          <label class="radio-card" :class="{ selected: hasSubscription === 'no' }">
            <input type="radio" v-model="hasSubscription" value="no" />
            <div class="radio-card-content">
              <span class="radio-card-title">{{ t('accountWizard.noSkip') }}</span>
              <span class="radio-card-desc">{{ t('accountWizard.noSkipDesc') }}</span>
            </div>
          </label>
        </div>

        <!-- Show account fields when "yes" is selected -->
        <Transition name="slide-down">
          <div v-if="hasSubscription === 'yes'" class="account-fields">
            <div class="form-group">
              <label for="wiz-name">{{ t('accountWizard.accountName') }} <span class="optional">(optional)</span></label>
              <input
                id="wiz-name"
                v-model="accountName"
                type="text"
                :placeholder="t('accountWizard.accountNamePlaceholder')"
                autofocus
                @input="suggestConfigPath"
              />
              <small class="account-name-hint">{{ t('accountWizard.accountNameHint') }}</small>
            </div>
            <div class="form-group">
              <label for="wiz-email">{{ t('accountWizard.email') }}</label>
              <input
                id="wiz-email"
                v-model="email"
                type="email"
                :placeholder="t('accountWizard.emailPlaceholder')"
              />
              <small>{{ t('accountWizard.emailHelp') }}</small>
            </div>
          </div>
        </Transition>
      </div>
      <div class="step-actions">
        <button class="btn btn-secondary" @click="closeWizard">{{ t('common.cancel') }}</button>
        <button
          class="btn"
          :class="hasSubscription === 'no' ? 'btn-outline' : 'btn-primary'"
          :disabled="!subscriptionValid"
          data-tour="wiz-sub-next"
          @click="handleSubscriptionNext"
        >
          {{ hasSubscription === 'no' ? t('accountWizard.noSkip') : t('accountWizard.continueBtn') }}
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14">
            <polyline points="9 18 15 12 9 6"/>
          </svg>
        </button>
      </div>
    </div>

    <!-- Step 2: CLI Setup -->
    <div v-if="backendKind && currentStep === 'cli'" class="wizard-step" data-tour="wiz-cli">
      <div class="step-body">
        <!-- CLI status -->
        <div class="status-card" :class="cliInstalled ? 'status-ok' : 'status-warn'" data-tour="wiz-cli-status">
          <div class="status-icon">
            <template v-if="isCheckingCli">
              <div class="spinner-sm"></div>
            </template>
            <template v-else-if="cliInstalled">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="20" height="20">
                <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/>
                <polyline points="22 4 12 14.01 9 11.01"/>
              </svg>
            </template>
            <template v-else>
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="20" height="20">
                <circle cx="12" cy="12" r="10"/>
                <line x1="12" y1="8" x2="12" y2="12"/>
                <line x1="12" y1="16" x2="12.01" y2="16"/>
              </svg>
            </template>
          </div>
          <div class="status-info">
            <span class="status-title">{{ backendName }} CLI</span>
            <span v-if="cliInstalled" class="status-detail">
              {{ t('accountWizard.cliInstalled') }}{{ cliVersion ? ` (${cliVersion})` : '' }}
            </span>
            <span v-else class="status-detail">{{ t('accountWizard.cliNotInstalled') }}</span>
          </div>
          <button
            v-if="!cliInstalled && !isInstallingCli"
            class="btn btn-primary btn-sm"
            @click="installCli"
          >
            {{ t('accountWizard.installCli') }}
          </button>
          <div v-if="isInstallingCli" class="spinner-sm"></div>
        </div>
        <div v-if="installError" class="error-text">{{ installError }}</div>
        <div v-if="installResult && installResult.success" class="install-success-text">
          Installed{{ installResult.binary_path ? ` at ${installResult.binary_path}` : '' }}
        </div>
        <pre v-if="installResult && !installResult.success && installResult.stderr" class="install-stderr">{{ installResult.stderr }}</pre>

        <!-- Config directory — read-only confirm. The directory is
             created on demand by the CLI launch in step 3, so we don't
             need a manual "Create directory" button anymore. -->
        <div v-if="configPath" class="config-dir-section" data-tour="wiz-cli-path">
          <div class="config-dir-label">{{ t('accountWizard.configPath') }}</div>
          <div class="config-dir-path">
            <code>{{ configPath }}</code>
          </div>
          <div v-if="dirError" class="error-text">{{ dirError }}</div>

          <div class="config-path-edit">
            <button class="btn-link-sm" @click="configPathManuallyEdited = true" v-if="!configPathManuallyEdited">
              {{ t('accountWizard.customizePath') }}
            </button>
            <div v-if="configPathManuallyEdited" class="form-group compact">
              <input
                v-model="configPath"
                type="text"
                :placeholder="`e.g., ~/.${backendKind}-personal`"
              />
            </div>
          </div>
        </div>
      </div>
      <div class="step-actions">
        <button class="btn btn-secondary" @click="goPrev">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14">
            <polyline points="15 18 9 12 15 6"/>
          </svg>
          {{ t('common.back') }}
        </button>
        <button class="btn btn-primary" data-tour="wiz-cli-next" @click="goNext">
          {{ t('accountWizard.continueBtn') }}
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14">
            <polyline points="9 18 15 12 9 6"/>
          </svg>
        </button>
      </div>
    </div>

    <!-- Step 3: Login -->
    <div v-if="backendKind && currentStep === 'login'" class="wizard-step" data-tour="wiz-login">
      <div class="step-body">
        <!-- Idle / Connecting -->
        <template v-if="loginStatus === 'idle' || loginStatus === 'connecting'">
          <div class="login-status login-connecting">
            <div class="spinner-sm"></div>
            <span>{{ t('accountWizard.startingLogin') }}</span>
          </div>
        </template>

        <!-- Streaming — delegate to <LoginStream> (handles url/text prompts + stdout). -->
        <template v-else-if="loginStatus === 'streaming'">
          <LoginStream
            :session="loginSession"
            :backend-kind="backendKind"
            :email="email"
          />
        </template>

        <!-- Completed -->
        <template v-else-if="loginStatus === 'completed'">
          <div class="login-status login-completed">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="20" height="20">
              <polyline points="20 6 9 17 4 12"/>
            </svg>
            <span>{{ t('accountWizard.loginCompleted') }}</span>
          </div>
        </template>

        <!-- Error -->
        <template v-else-if="loginStatus === 'error'">
          <div class="login-status login-error">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16">
              <circle cx="12" cy="12" r="10"/>
              <line x1="15" y1="9" x2="9" y2="15"/>
              <line x1="9" y1="9" x2="15" y2="15"/>
            </svg>
            <span>{{ loginError }}</span>
          </div>
          <button class="btn btn-secondary" style="margin-top: 12px;" @click="startUnifiedLogin">{{ t('accountWizard.tryAgain') }}</button>
        </template>
      </div>
      <div class="step-actions">
        <button class="btn btn-secondary" @click="goPrev">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14">
            <polyline points="15 18 9 12 15 6"/>
          </svg>
          {{ t('common.back') }}
        </button>
        <button class="btn btn-primary" @click="goNext">
          {{ loginStatus === 'idle' ? t('common.skip') : t('accountWizard.continueBtn') }}
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14">
            <polyline points="9 18 15 12 9 6"/>
          </svg>
        </button>
      </div>
    </div>

    <!-- Step 3.5: CLIProxyAPI registration (optional) -->
    <div v-if="backendKind && currentStep === 'proxy'" class="wizard-step" data-tour="wiz-proxy">
      <div class="step-body">
        <!-- CLIProxyAPI not installed — offer auto-install -->
        <div v-if="cliproxyStatusChecked && !cliproxyInstalled" class="cliproxy-install-block">
          <p class="step-description">
            CLIProxyAPI is not installed. Install it to expose this account
            through an OpenAI-compatible endpoint for other tools.
          </p>
          <button
            class="btn btn-primary"
            data-tour="wiz-proxy-install"
            :disabled="cliproxyInstalling"
            @click="installCliproxy"
          >
            <div v-if="cliproxyInstalling" class="spinner-sm"></div>
            {{ cliproxyInstalling ? 'Installing cliproxyapi…' : 'Install CLIProxyAPI' }}
          </button>
          <div v-if="cliproxyInstallResult">
            <p v-if="cliproxyInstallResult.success" class="install-success-text">
              Installed{{ cliproxyInstallResult.binary_path ? ` at ${cliproxyInstallResult.binary_path}` : '' }}
            </p>
            <div v-else>
              <p class="error-text">Install failed</p>
              <pre v-if="cliproxyInstallResult.stderr" class="install-stderr">{{ cliproxyInstallResult.stderr }}</pre>
            </div>
          </div>
        </div>

        <!-- CLIProxyAPI is installed — show registration flow -->
        <div v-else-if="cliproxyInstalled" class="proxy-step-body">
          <h4 class="proxy-heading">Register with API proxy</h4>
          <p class="step-description">
            Optional: register this account with CLIProxyAPI so other tools
            can reach it through an OpenAI-compatible endpoint.
          </p>

          <button
            v-if="proxyLoginStatus === 'idle'"
            class="btn btn-primary"
            data-tour="wiz-proxy-start"
            @click="runProxyLogin"
          >
            Start proxy registration
          </button>

          <div v-if="proxyLoginStatus === 'running'" class="login-status login-started">
            <div class="spinner-sm"></div>
            <span>{{ proxyLoginMessage }}</span>
          </div>

          <div v-if="proxyLoginStatus === 'device_auth'" class="proxy-device-auth">
            <div class="proxy-url-badge">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16">
                <path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6" />
                <polyline points="15 3 21 3 21 9" />
                <line x1="10" y1="14" x2="21" y2="3" />
              </svg>
              <span>A browser window should have opened. Sign in, then the page will redirect to <code>localhost</code> — that redirect will fail (this is normal). Copy the full URL from the browser address bar and paste it below.</span>
            </div>
            <a v-if="proxyOauthUrl" :href="proxyOauthUrl" target="_blank" rel="noopener" class="proxy-oauth-link">
              {{ proxyOauthUrl }}
            </a>
            <div v-if="proxyDeviceCode" class="proxy-device-code-card">
              <span class="proxy-device-code-label">Your device code:</span>
              <code class="proxy-device-code-value">{{ proxyDeviceCode }}</code>
            </div>
            <div class="proxy-callback-section" data-tour="wiz-proxy-callback">
              <p class="proxy-callback-hint">If the redirect to localhost fails, paste the callback URL:</p>
              <div class="proxy-callback-row">
                <input
                  v-model="proxyCallbackUrl"
                  class="proxy-callback-input"
                  type="url"
                  placeholder="http://localhost:54545/callback?code=..."
                />
                <button class="btn btn-primary btn-sm" @click="submitProxyCallback" :disabled="!proxyCallbackUrl.trim()">
                  Submit
                </button>
              </div>
              <p v-if="proxyCallbackError" class="error-text">{{ proxyCallbackError }}</p>
            </div>
          </div>

          <div v-if="proxyLoginStatus === 'success'" class="login-status login-completed">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16">
              <polyline points="20 6 9 17 4 12"/>
            </svg>
            <span>{{ proxyLoginMessage || 'Registered successfully' }}</span>
          </div>

          <div v-if="proxyLoginStatus === 'skipped'" class="proxy-skipped">
            <p>{{ proxyLoginMessage }}</p>
            <button class="btn btn-outline btn-sm" @click="resetProxyLogin">Retry</button>
          </div>

          <div v-if="proxyLoginStatus === 'error'" class="proxy-error">
            <p class="error-text"><strong>Error:</strong> {{ proxyLoginMessage }}</p>
            <button class="btn btn-outline btn-sm" @click="resetProxyLogin">Retry</button>
          </div>
        </div>

        <!-- Status check still pending -->
        <div v-else class="proxy-loading">
          <div class="spinner-sm"></div>
          <span>Checking CLIProxyAPI status…</span>
        </div>
      </div>
      <div class="step-actions">
        <button class="btn btn-secondary" @click="goPrev">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14">
            <polyline points="15 18 9 12 15 6"/>
          </svg>
          {{ t('common.back') }}
        </button>
        <button class="btn btn-primary" data-tour="wiz-proxy-skip" @click="goNext">
          {{ proxyLoginStatus === 'success' ? t('accountWizard.continueBtn') : t('common.skip') }}
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14">
            <polyline points="9 18 15 12 9 6"/>
          </svg>
        </button>
      </div>
    </div>

    <!-- Step 4: Plan & Save -->
    <div v-if="backendKind && currentStep === 'plan'" class="wizard-step" data-tour="wiz-plan">
      <div class="step-body">
        <!-- Review card -->
        <div class="review-card" data-tour="wiz-plan-review">
          <div class="review-row">
            <span class="review-label">{{ t('accountWizard.accountName') }}</span>
            <span class="review-value">{{ accountName }}</span>
          </div>
          <div v-if="email" class="review-row">
            <span class="review-label">{{ t('accountWizard.email') }}</span>
            <span class="review-value">{{ email }}</span>
          </div>
          <div v-if="configPath" class="review-row">
            <span class="review-label">{{ t('accountWizard.configPath') }}</span>
            <code class="review-value">{{ configPath }}</code>
          </div>
        </div>

        <div v-if="planOptions.length > 0" class="form-group">
          <label for="wiz-plan">{{ t('accountWizard.plan') }}</label>
          <select id="wiz-plan" v-model="selectedPlan">
            <option value="">{{ t('accountWizard.selectPlan') }}</option>
            <option v-for="opt in planOptions" :key="opt.id" :value="opt.id">
              {{ opt.label }}
            </option>
          </select>
        </div>
        <div class="form-group checkbox" data-tour="wiz-plan-default">
          <label>
            <input type="checkbox" v-model="isDefault" />
            {{ t('accountWizard.setDefault') }}
          </label>
        </div>
        <div v-if="saveError" class="error-text">{{ saveError }}</div>
      </div>
      <div class="step-actions">
        <button class="btn btn-secondary" @click="goPrev">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14">
            <polyline points="15 18 9 12 15 6"/>
          </svg>
          {{ t('common.back') }}
        </button>
        <button class="btn btn-primary" data-tour="wiz-plan-save" :disabled="isSaving" @click="saveAccount">
          <div v-if="isSaving" class="spinner-sm"></div>
          {{ isSaving ? t('accountWizard.saving') : t('accountWizard.saveAccount') }}
        </button>
      </div>
    </div>

    <!-- Step 5: Done -->
    <div v-if="backendKind && currentStep === 'done'" class="wizard-step" data-tour="wiz-done">
      <div class="step-body done-body">
        <div class="done-icon">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="40" height="40">
            <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/>
            <polyline points="22 4 12 14.01 9 11.01"/>
          </svg>
        </div>
        <h4>{{ t('accountWizard.accountCreated') }}</h4>
        <p>{{ accountName }} has been added to {{ backendName }}.</p>

        <!-- Proxy login (CLIProxyAPI) step omitted — not in ai-accounts 0.3.0-alpha.1. -->

        <div class="done-actions">
          <button class="btn btn-outline" data-tour="wiz-done-add" @click="addAnotherAccount">
            {{ t('accountWizard.addAnother') }}
          </button>
          <button class="btn btn-primary" data-tour="wiz-done-next-backend" @click="doneWizard">
            {{ t('accountWizard.doneNextBackend') }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* The wizard's CSS references --primary-color / --primary-hover but we
 * don't ship a base stylesheet that defines them, and Agented (the
 * primary host) only defines accent-cyan / accent-violet etc. Without
 * a fallback, ``background: var(--primary-color)`` resolves to nothing
 * and every .btn-primary inside the wizard renders as flat invisible
 * text — exactly the "Start proxy registration looks like a link"
 * complaint. Anchor the cascade on .wizard-container so any host can
 * override by redefining these on a parent. */
.wizard-container {
  --primary-color: var(--accent-cyan, #00d4ff);
  --primary-hover: var(--accent-violet, #8855ff);
  background: var(--bg-tertiary);
  border: 1px solid var(--border-default);
  border-radius: 12px;
  padding: 1.5rem;
  margin-bottom: 1.5rem;
  animation: wizardIn 0.3s ease;
}

@keyframes wizardIn {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: translateY(0); }
}

.wizard-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 1.25rem;
}

.wizard-header h3 {
  margin: 0;
  font-size: 1.125rem;
  font-weight: 600;
  color: var(--text-primary);
}

.wizard-close {
  background: none;
  border: none;
  color: var(--text-secondary);
  font-size: 1.5rem;
  cursor: pointer;
  padding: 0 0.25rem;
  line-height: 1;
}

.wizard-close:hover {
  color: var(--text-primary);
}

/* Step indicators */
.wizard-steps {
  display: flex;
  gap: 0;
  margin-bottom: 1.5rem;
  border-bottom: 1px solid var(--border-default);
  padding-bottom: 1rem;
}

.step-indicator {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex: 1;
  padding: 0.5rem 0;
  position: relative;
}

.step-indicator.clickable {
  cursor: pointer;
}

.step-indicator::after {
  content: '';
  position: absolute;
  right: 0;
  top: 50%;
  transform: translateY(-50%);
  width: 24px;
  height: 1px;
  background: var(--border-default);
}

.step-indicator:last-child::after {
  display: none;
}

.step-number {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border-radius: 50%;
  font-size: 0.75rem;
  font-weight: 600;
  flex-shrink: 0;
  background: var(--bg-secondary);
  color: var(--text-secondary);
  border: 1px solid var(--border-default);
  transition: all 0.2s ease;
}

.step-indicator.active .step-number {
  background: var(--primary-color);
  color: white;
  border-color: var(--primary-color);
}

.step-indicator.completed .step-number {
  background: var(--accent-emerald);
  color: white;
  border-color: var(--accent-emerald);
}

.step-label {
  font-size: 0.8125rem;
  color: var(--text-tertiary);
  white-space: nowrap;
  transition: color 0.2s ease;
}

.step-indicator.active .step-label {
  color: var(--text-primary);
  font-weight: 500;
}

.step-indicator.completed .step-label {
  color: var(--text-secondary);
}

/* Step body */
.wizard-step {
  animation: stepIn 0.25s ease;
}

@keyframes stepIn {
  from { opacity: 0; transform: translateX(12px); }
  to { opacity: 1; transform: translateX(0); }
}

.step-body {
  min-height: 160px;
}

.step-question {
  font-size: 1rem;
  font-weight: 500;
  color: var(--text-primary);
  margin: 0 0 1.25rem 0;
}

.step-description {
  color: var(--text-secondary);
  font-size: 0.875rem;
  margin: 0 0 1rem 0;
}

/* Radio card group */
.radio-group {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  margin-bottom: 1.25rem;
}

.radio-card {
  display: flex;
  align-items: flex-start;
  gap: 0.75rem;
  padding: 1rem;
  background: var(--bg-secondary);
  border: 1.5px solid var(--border-default);
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.15s ease;
}

.radio-card:hover {
  border-color: var(--primary-color);
  background: var(--bg-hover, var(--bg-secondary));
}

.radio-card.selected {
  border-color: var(--primary-color);
  background: rgba(99, 102, 241, 0.06);
}

.radio-card input[type="radio"] {
  margin-top: 2px;
  accent-color: var(--primary-color);
  width: 16px;
  height: 16px;
  flex-shrink: 0;
}

.radio-card-content {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.radio-card-title {
  font-size: 0.875rem;
  font-weight: 600;
  color: var(--text-primary);
}

.radio-card-desc {
  font-size: 0.75rem;
  color: var(--text-secondary);
  line-height: 1.4;
}

/* Account fields transition */
.account-fields {
  padding-top: 0.25rem;
}

.slide-down-enter-active,
.slide-down-leave-active {
  transition: all 0.25s ease;
  overflow: hidden;
}

.slide-down-enter-from,
.slide-down-leave-to {
  opacity: 0;
  transform: translateY(-8px);
  max-height: 0;
}

.slide-down-enter-to,
.slide-down-leave-from {
  opacity: 1;
  transform: translateY(0);
  max-height: 300px;
}

/* Step actions */
.step-actions {
  display: flex;
  justify-content: space-between;
  gap: 0.75rem;
  margin-top: 1.5rem;
  padding-top: 1rem;
  border-top: 1px solid var(--border-default);
}

.step-actions .btn {
  display: inline-flex;
  align-items: center;
  gap: 0.375rem;
}

/* Form groups */
.form-group {
  margin-bottom: 1rem;
}

.form-group.compact {
  margin-bottom: 0;
  margin-top: 0.5rem;
}

.form-group label {
  display: block;
  margin-bottom: 0.375rem;
  font-size: 0.8125rem;
  font-weight: 500;
  color: var(--text-primary);
}

.required {
  color: var(--accent-crimson);
}

.form-group input[type="text"],
.form-group input[type="email"] {
  width: 100%;
  padding: 8px 12px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-default);
  border-radius: 6px;
  color: var(--text-primary);
  font-size: 14px;
  font-family: inherit;
}

.form-group input:focus,
.form-group select:focus {
  outline: none;
  border-color: var(--primary-color);
}

.form-group small {
  display: block;
  margin-top: 0.25rem;
  font-size: 0.75rem;
  color: var(--text-secondary);
}

.form-group select {
  width: 100%;
  padding: 8px 12px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-default);
  border-radius: 6px;
  color: var(--text-primary);
  font-size: 14px;
  font-family: inherit;
}

.form-group.checkbox label {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  cursor: pointer;
  font-weight: 400;
}

.form-group.checkbox input[type="checkbox"] {
  width: 16px;
  height: 16px;
}

/* Status card */
.status-card {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 1rem;
  border-radius: 8px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-default);
  margin-bottom: 1rem;
}

.status-card.status-ok {
  border-color: rgba(52, 211, 153, 0.3);
}

.status-card.status-warn {
  border-color: rgba(251, 191, 36, 0.3);
}

.status-icon {
  display: flex;
  align-items: center;
  flex-shrink: 0;
}

.status-card.status-ok .status-icon {
  color: var(--accent-emerald);
}

.status-card.status-warn .status-icon {
  color: var(--accent-amber, #fbbf24);
}

.status-info {
  display: flex;
  flex-direction: column;
  flex: 1;
}

.status-title {
  font-size: 0.875rem;
  font-weight: 600;
  color: var(--text-primary);
}

.status-detail {
  font-size: 0.75rem;
  color: var(--text-secondary);
}

/* Config dir section */
.config-dir-section {
  margin-bottom: 1rem;
}

.config-dir-label {
  font-size: 0.8125rem;
  font-weight: 500;
  color: var(--text-primary);
  margin-bottom: 0.375rem;
}

.config-dir-path {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.5rem 0.75rem;
  background: var(--bg-secondary);
  border: 1px solid var(--border-default);
  border-radius: 6px;
}

.config-dir-path code {
  font-family: var(--font-mono, monospace);
  font-size: 0.8125rem;
  color: var(--text-primary);
  flex: 1;
}

.dir-created-badge {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  font-size: 0.75rem;
  color: var(--accent-emerald);
  font-weight: 500;
}

.config-path-edit {
  margin-top: 0.375rem;
}

.btn-link-sm {
  background: none;
  border: none;
  color: var(--text-tertiary);
  font-size: 0.75rem;
  cursor: pointer;
  padding: 0;
  text-decoration: underline;
  font-family: inherit;
}

.btn-link-sm:hover {
  color: var(--text-secondary);
}

/* API key info */
.api-key-info {
  padding: 0.75rem;
  background: var(--bg-secondary);
  border: 1px solid var(--border-default);
  border-radius: 6px;
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.api-key-label {
  font-size: 0.75rem;
  font-weight: 500;
  color: var(--text-secondary);
}

.api-key-info code {
  font-family: var(--font-mono, monospace);
  font-size: 0.8125rem;
  color: var(--text-primary);
}

/* Login start button */
.login-start-btn {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 16px;
}

/* Login terminal */
.login-terminal {
  background: #0a0a0f;
  border: 1px solid var(--border-default);
  border-radius: 8px;
  overflow: hidden;
}

.login-terminal-output {
  padding: 12px 16px;
  font-family: 'Geist Mono', 'SF Mono', 'Monaco', monospace;
  font-size: 12px;
  line-height: 1.6;
  color: #a1a1aa;
  min-height: 120px;
  max-height: 250px;
  overflow-y: auto;
  white-space: pre-wrap;
  word-break: break-word;
}

.terminal-line {
  min-height: 1.2em;
}

.login-terminal-input {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 16px;
  border-top: 1px solid var(--border-default);
  background: rgba(255, 255, 255, 0.02);
}

.terminal-prompt {
  color: var(--accent-cyan);
  font-family: 'Geist Mono', monospace;
  font-weight: 600;
  flex-shrink: 0;
}

.terminal-input {
  flex: 1;
  background: transparent;
  border: none;
  color: var(--text-primary);
  font-family: 'Geist Mono', monospace;
  font-size: 12px;
  outline: none;
}

.terminal-input::placeholder {
  color: #52525b;
}

.login-connecting {
  color: var(--accent-cyan);
}

.login-terminal-waiting {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 16px;
  border-top: 1px solid var(--border-default);
  color: var(--text-tertiary);
  font-size: 12px;
}

/* Login interactive options — clickable buttons for CLI questions */
.login-options {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px 16px;
  border-top: 1px solid var(--border-default);
}

.login-question-text {
  margin: 0 0 8px 0;
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.4;
}

.login-option {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-default);
  border-radius: 8px;
  cursor: pointer;
  transition: border-color 0.15s ease, background 0.15s ease;
  text-align: left;
  font-family: inherit;
}

.login-option:hover {
  border-color: var(--accent-cyan);
  background: rgba(0, 207, 253, 0.05);
}

.login-option-number {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border-radius: 6px;
  background: var(--bg-tertiary);
  color: var(--text-secondary);
  font-size: 12px;
  font-weight: 600;
  flex-shrink: 0;
}

.login-option-label {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-primary);
}

.login-option-arrow {
  color: var(--text-tertiary);
  flex-shrink: 0;
}

/* Login status */
.login-status {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.75rem;
  border-radius: 6px;
  font-size: 0.8125rem;
  margin-bottom: 0.75rem;
}

.login-started {
  background: rgba(96, 165, 250, 0.1);
  color: var(--accent-cyan, #60a5fa);
  border: 1px solid rgba(96, 165, 250, 0.2);
}

.login-error {
  background: var(--accent-crimson-dim, rgba(239, 68, 68, 0.1));
  color: var(--accent-crimson);
  border: 1px solid rgba(239, 68, 68, 0.2);
}

.login-completed {
  background: var(--accent-emerald-dim, rgba(52, 211, 153, 0.1));
  color: var(--accent-emerald);
  border: 1px solid rgba(52, 211, 153, 0.2);
}

/* Device code */
.device-code-section {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.5rem;
  padding: 1rem;
  background: var(--bg-secondary);
  border: 1px solid var(--border-default);
  border-radius: 8px;
  margin-bottom: 0.75rem;
}

.device-code-label {
  font-size: 0.8125rem;
  color: var(--text-secondary);
}

.device-code {
  font-family: var(--font-mono, monospace);
  font-size: 1.5rem;
  font-weight: 700;
  color: var(--primary-color);
  letter-spacing: 0.1em;
  padding: 0.5rem 1rem;
  background: var(--bg-tertiary);
  border-radius: 6px;
}

.skip-note {
  font-size: 0.75rem;
  color: var(--text-tertiary);
  text-align: center;
  margin-top: 0.5rem;
}

/* Review card */
.review-card {
  background: var(--bg-secondary);
  border: 1px solid var(--border-default);
  border-radius: 8px;
  padding: 1rem;
  margin-bottom: 1rem;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.review-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 0.8125rem;
}

.review-label {
  color: var(--text-secondary);
}

.review-value {
  color: var(--text-primary);
  font-weight: 500;
}

code.review-value {
  font-family: var(--font-mono, monospace);
  font-weight: 400;
  font-size: 0.8125rem;
}

/* Done state */
.done-body {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  padding: 2rem 0;
}

.done-icon {
  color: var(--accent-emerald);
  margin-bottom: 1rem;
}

.done-body h4 {
  margin: 0 0 0.5rem 0;
  font-size: 1.125rem;
  font-weight: 600;
  color: var(--text-primary);
}

.done-body p {
  margin: 0 0 1.5rem 0;
  font-size: 0.875rem;
  color: var(--text-secondary);
}

.done-actions {
  display: flex;
  gap: 0.75rem;
}

/* Proxy login status */
.proxy-login-status {
  width: 100%;
  padding: 0.75rem 1rem;
  border-radius: 8px;
  margin-bottom: 1.25rem;
  font-size: 0.8125rem;
}

.proxy-status-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.proxy-running {
  background: rgba(59, 130, 246, 0.1);
  border: 1px solid rgba(59, 130, 246, 0.2);
  color: var(--text-secondary);
}

.proxy-success {
  background: rgba(34, 197, 94, 0.1);
  border: 1px solid rgba(34, 197, 94, 0.2);
  color: var(--accent-emerald);
}

.proxy-device_auth {
  background: rgba(59, 130, 246, 0.1);
  border: 1px solid rgba(59, 130, 246, 0.2);
  color: var(--text-secondary);
}

.proxy-device-auth {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.proxy-url-badge {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.625rem 0.875rem;
  background: rgba(96, 165, 250, 0.1);
  border: 1px solid rgba(96, 165, 250, 0.2);
  border-radius: 8px;
  font-size: 0.8125rem;
  color: var(--accent-cyan, #60a5fa);
}

.proxy-oauth-link {
  display: block;
  padding: 0.625rem 0.875rem;
  background: rgba(0, 0, 0, 0.3);
  border: 1px solid var(--border-default, #27272a);
  border-radius: 8px;
  font-family: 'SF Mono', 'Monaco', monospace;
  font-size: 0.75rem;
  color: var(--accent-cyan, #60a5fa);
  word-break: break-all;
  text-decoration: none;
  transition: border-color 0.15s;
}

.proxy-oauth-link:hover {
  border-color: var(--accent-cyan, #60a5fa);
}

.proxy-device-code-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.5rem;
  padding: 0.75rem;
  background: rgba(0, 0, 0, 0.3);
  border: 1px solid var(--border-default, #27272a);
  border-radius: 8px;
}

.proxy-device-code-label {
  font-size: 0.8125rem;
  color: var(--text-secondary);
}

.proxy-device-code-value {
  font-family: 'SF Mono', 'Monaco', 'Cascadia Code', monospace;
  font-size: 1.25rem;
  font-weight: 700;
  color: #e4e4e7;
  letter-spacing: 2px;
  padding: 0.375rem 1rem;
  background: var(--bg-tertiary, rgba(0, 0, 0, 0.4));
  border-radius: 6px;
}

.proxy-callback-section {
  width: 100%;
  margin-top: 0.25rem;
}

.proxy-callback-hint {
  margin: 0 0 0.5rem;
  font-size: 0.75rem;
  color: var(--text-tertiary);
  line-height: 1.4;
}

.proxy-callback-row {
  display: flex;
  gap: 0.5rem;
  align-items: center;
}

.proxy-callback-input {
  flex: 1;
  font-size: 0.75rem;
  padding: 0.5rem 0.75rem;
  background: rgba(0, 0, 0, 0.3);
  border: 1px solid var(--border-default, #27272a);
  border-radius: 6px;
  color: var(--text-primary);
  font-family: 'SF Mono', monospace;
  outline: none;
  transition: border-color 0.15s;
}

.proxy-callback-input:focus {
  border-color: var(--accent-cyan, #60a5fa);
}

.proxy-callback-input::placeholder {
  color: var(--text-tertiary, #52525b);
}

.proxy-skipped {
  background: rgba(234, 179, 8, 0.08);
  border: 1px solid rgba(234, 179, 8, 0.15);
  color: var(--text-tertiary);
}

.proxy-error {
  background: rgba(239, 68, 68, 0.08);
  border: 1px solid rgba(239, 68, 68, 0.15);
  color: var(--accent-red, #ef4444);
}

/* Error text */
.error-text {
  font-size: 0.8125rem;
  color: var(--accent-crimson);
  margin-top: 0.375rem;
}

/* Shared button styles */
.btn {
  display: inline-flex;
  align-items: center;
  gap: 0.375rem;
  padding: 0.5rem 1rem;
  border-radius: 6px;
  font-size: 0.875rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s ease;
  font-family: inherit;
  border: none;
}

.btn-sm {
  padding: 0.375rem 0.75rem;
  font-size: 0.8125rem;
}

.btn-primary {
  background: var(--primary-color);
  color: var(--text-on-accent, #0a0a0f);
  font-weight: 600;
  border: 1px solid transparent;
  box-shadow: 0 1px 0 rgba(0, 0, 0, 0.2), inset 0 1px 0 rgba(255, 255, 255, 0.08);
}

.btn-primary:hover:not(:disabled) {
  background: var(--primary-hover);
  color: white;
  transform: translateY(-1px);
  box-shadow: 0 2px 8px rgba(0, 212, 255, 0.25);
}

.btn-primary:active:not(:disabled) {
  transform: translateY(0);
}

.btn-primary:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.btn-secondary {
  background: var(--bg-secondary);
  color: var(--text-primary);
  border: 1px solid var(--border-default);
}

.btn-secondary:hover {
  background: var(--bg-hover, var(--bg-secondary));
}

.btn-outline {
  background: transparent;
  color: var(--text-secondary);
  border: 1px solid var(--border-default);
}

.btn-outline:hover {
  background: var(--bg-tertiary);
  color: var(--text-primary);
}

/* Spinner */
.spinner-sm {
  width: 14px;
  height: 14px;
  border: 2px solid rgba(255, 255, 255, 0.3);
  border-top-color: currentColor;
  border-radius: 50%;
  animation: spin 0.6s linear infinite;
  display: inline-block;
  flex-shrink: 0;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}
</style>
