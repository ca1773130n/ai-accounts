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
import { ref, computed, watch, nextTick, onMounted, onBeforeUnmount, onUnmounted, inject } from 'vue';
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
    // Collapsed 3-phase indicator labels (Setup / Login / Finish).
    'accountWizard.phaseSetup': 'Setup',
    'accountWizard.phaseLogin': 'Login',
    'accountWizard.phaseFinish': 'Finish',
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
    'accountWizard.noCliRequired': 'No CLI required',
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
    'accountWizard.tour.proxy.install.message': 'Click Install to set up CLIProxyAPI. It lets other tools reach this account through an OpenAI-compatible endpoint. Or click Skip below if you don\'t need it.',
    'accountWizard.tour.proxy.start.title': 'Register with the proxy',
    'accountWizard.tour.proxy.start.message': 'Click Start proxy registration to begin — a browser tab opens for the proxy OAuth. Don\'t need the proxy? Click Skip below to jump to step 5.',
    'accountWizard.tour.proxy.callback.title': 'Paste the callback URL',
    'accountWizard.tour.proxy.callback.message': 'Copy the full localhost callback URL from your browser\'s address bar and paste it here, then click Submit. The redirect page may show "connection refused" — that\'s expected.',
    'accountWizard.tour.proxy.continue.title': 'Proxy registered',
    'accountWizard.tour.proxy.continue.message': 'Registration succeeded. Click Continue below to move to step 5.',
    'accountWizard.tour.plan.review.title': 'Review',
    'accountWizard.tour.plan.review.message': 'Check the values you entered. If anything looks wrong, click Back to fix it.',
    'accountWizard.tour.plan.pick.title': 'Pick a plan',
    'accountWizard.tour.plan.pick.message': 'Pro, Max, or API. The CLI told us which subscription it found in step 3 — override here if needed.',
    'accountWizard.tour.plan.default.title': 'Make it the default? (optional)',
    'accountWizard.tour.plan.default.message': 'Tick to mark this account as the backend\'s default.',
    'accountWizard.tour.plan.save.title': 'Save the account',
    'accountWizard.tour.plan.save.message': 'Click Save to persist the account and move to the Done screen. Tip: tick "Set as default" above first if this should be the backend\'s default account.',
    'accountWizard.tour.done.add.title': 'Add another account?',
    'accountWizard.tour.done.add.message': 'Click here to add another account on the same backend (e.g. a second Claude account).',
    'accountWizard.tour.done.nextBackend.title': 'Move to the next backend',
    'accountWizard.tour.done.nextBackend.message': 'Click here to advance the tour to the next backend (Codex / Antigravity / OpenCode).',
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
const PROXY_SUPPORTED_KINDS = ['claude', 'codex', 'antigravity', 'kimi'] as const;
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

// Displayed step indicator — collapse the internal steps into 3 phases so
// the indicator fits narrow-mobile breakpoints. The internal STEP_ORDER /
// VISIBLE_STEPS / goNext / goPrev navigation is untouched; only the dots the
// user sees are deduped down to Setup / Login / Finish.
type DisplayPhase = 'setup' | 'login' | 'finish';
const DISPLAY_PHASES: Record<WizardStep, DisplayPhase> = {
  subscription: 'setup',
  cli: 'setup',
  login: 'login',
  proxy: 'login',
  plan: 'finish',
  done: 'finish',
};
const PHASE_ORDER: DisplayPhase[] = ['setup', 'login', 'finish'];
const phaseLabels = computed<Record<DisplayPhase, string>>(() => ({
  setup: t('accountWizard.phaseSetup'),
  login: t('accountWizard.phaseLogin'),
  finish: t('accountWizard.phaseFinish'),
}));
// The phase the user is currently on — drives the active dot.
const currentPhase = computed<DisplayPhase>(() => DISPLAY_PHASES[currentStep.value]);
const currentPhaseIndex = computed(() => PHASE_ORDER.indexOf(currentPhase.value));

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
  // ``antigravity`` kind is unchanged internally — only the user-facing label
  // is "Antigravity". The config dir stays ~/.antigravity (no DB/config migration).
  antigravity: '.antigravity',
  opencode: '.opencode',
  openrouter: '.openrouter',
  openai_compat: '.openai_compat',
  kimi: '.kimi',
  // Goose stores its config under ~/.config/goose (XDG). Aider/Crush fall back
  // to the generic ~/.<kind> default — their isolation is via HOME / CRUSH_GLOBAL_*.
  goose: '.config/goose',
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
    antigravity: 'GOOGLE',
    opencode: 'OPENCODE',
    openrouter: 'OPENROUTER',
    openai_compat: 'OPENAI',
    kimi: 'KIMI',
    deepseek: 'DEEPSEEK',
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
// Keyless / no-CLI kinds. These backends authenticate via an API key (or, for
// Antigravity, a native cliproxy OAuth flow) — there's no terminal CLI to
// install, so the cli step shows a "No CLI required" badge instead of an
// install check. ``antigravity`` is included because Antigravity needs no CLI.
const NO_CLI_KINDS = ['openrouter', 'openai_compat', 'antigravity', 'kimi', 'deepseek'] as const;
const requiresNoCli = computed(() =>
  NO_CLI_KINDS.includes(
    (backendKind.value ?? '') as (typeof NO_CLI_KINDS)[number]
  )
);

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

// Pre-existing claude accounts on macOS share one Keychain entry — if the
// user is about to add a 2nd one, surface a one-line warning so they don't
// think they have two independent accounts. The Claude CLI's storage scheme
// is global per macOS user (service "Claude Safe Storage"), so adding a
// new account silently replaces the previous credential.
const existingClaudeCount = ref(0);
const isMacOS = computed(() => {
  if (typeof navigator === 'undefined') return false;
  return /Mac|iPhone|iPad|iPod/i.test(navigator.platform || '');
});
const showClaudeKeychainWarning = computed(() =>
  backendKind.value === 'claude' && isMacOS.value && existingClaudeCount.value >= 1,
);

async function refreshExistingClaudeCount() {
  try {
    const res = await client.listBackends();
    existingClaudeCount.value = (res.items || []).filter(b => b.kind === 'claude').length;
  } catch {
    existingClaudeCount.value = 0;
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
  busEmit({ type: 'wizard.opened', backendKind: backendKind.value });
  // Kick off a CLIProxyAPI status check so the proxy step can render
  // install/register UI without a spinner lag.
  checkCliproxyStatus();
  // For the macOS Claude keychain warning — refresh the count once so we
  // know whether the user is about to clobber an existing credential.
  void refreshExistingClaudeCount();
  // Broadcast the FIRST substep — the activeTourSubstep watcher only fires
  // on changes, so without this the host tour overlay would keep showing the
  // parent tour-machine step's title/guide ("AI Backend Accounts: click Add
  // Account") even after the wizard is open. Wait a tick so the wizard's
  // root anchor is in the DOM before broadcasting.
  void nextTick().then(() => {
    if (isUnmounted.value) return;
    if (activeTourSubstep.value) {
      void broadcastSubstep(activeTourSubstep.value);
    } else {
      setTourTarget(`[data-tour="wiz-${currentStep.value}"]`);
      setTourGuide(null);
      setTourTitle(null);
    }
  });
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
// terminal-state transitions. Antigravity-specific direct OAuth, PTY SSE, and
// per-kind option/question UI are replaced by the unified login protocol.
// ---------------------------------------------------------------------------
const draftAccountId = ref<string>(''); // backend row id once created

watch(currentStep, async (_step) => {
  // The substep-reset and the spotlight pushes live in the dedicated
  // tour-spotlight wiring further down (after every ref the predicates
  // close over). Here we only auto-start login.
  if (currentStep.value === 'login' && loginSession.status.value === 'idle') {
    // When the backend advertises multiple login flows (e.g. antigravity's
    // api_key + cli_browser), don't auto-start — show the method picker
    // first so the user explicitly chooses. Single-flow backends still
    // auto-start as before. The user's pick (selectedFlow) overrides
    // pickLoginFlow's default.
    const meta = backendMeta.value;
    if (meta && meta.login_flows.length > 1 && selectedFlow.value === null) {
      return;
    }
    await startUnifiedLogin();
  }
}, { immediate: true });

// v0.6.4: surface login-start failures to the UI. The previous
// implementation only console.warn'd, leaving the wizard stuck on
// the "Starting login…" spinner forever when the sidecar /begin
// call failed (network, malformed metadata, missing backend kind,
// etc.). Now we set a local error ref that the login step renders.
const loginStartError = ref<string | null>(null);

// Selected login flow override. When null, pickLoginFlow's default order
// applies. The flow-switcher UI in the login step writes here so the user
// can bail to a different flow (e.g. api_key) when OAuth is broken on
// Google's side.
const selectedFlow = ref<LoginFlowKind | null>(null);

async function startUnifiedLogin() {
  const meta = backendMeta.value;
  if (!meta) {
    loginStartError.value = (
      'Cannot start login: backend metadata is not loaded yet. ' +
      'Refresh the page and try again.'
    );
    return;
  }
  loginStartError.value = null;
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
    // Honour the user's flow override first; otherwise fall back to the
    // default (cli_browser > oauth_device > api_key).
    const flow = selectedFlow.value ?? pickLoginFlow(meta);
    busEmit({
      type: 'wizard.step',
      backendKind: meta.kind,
      step: 'login.start',
    });
    await loginSession.start(draftAccountId.value, flow, collectInputs(meta));
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e);
    console.warn('[AccountWizard] login failed:', e);
    loginStartError.value = (
      `Could not start the login flow: ${msg}. ` +
      `Check that the sidecar is running on :20001 and that ` +
      `the ${meta.kind} backend metadata is reachable.`
    );
  }
}

function pickLoginFlow(meta: BackendMetadata): LoginFlowKind {
  const available = meta.login_flows.map((f) => f.kind);
  if (available.includes('cli_browser')) return 'cli_browser';
  if (available.includes('oauth_device')) return 'oauth_device';
  return 'api_key';
}

/** The flow currently in use — explicit selection if set, else the auto-pick. */
const activeFlow = computed<LoginFlowKind>(() => {
  return selectedFlow.value
    ?? (backendMeta.value ? pickLoginFlow(backendMeta.value) : 'cli_browser');
});

/** True when the backend advertises >1 flow — only then does the switcher
 *  add value (a single-flow backend has nothing to choose). */
const hasMultipleFlows = computed(() =>
  (backendMeta.value?.login_flows.length ?? 0) > 1,
);

/** Cancel the current session, override the flow, restart fresh. Used
 *  when the user is stuck mid-flow (e.g. Google's OAuth consent gate is
 *  broken) and wants to try a different flow without leaving the wizard. */
async function switchLoginFlow(kind: LoginFlowKind) {
  // Only early-return on a true no-op switch — when the user has ALREADY
  // picked a flow and is clicking the same one again. On the first pick
  // (`selectedFlow.value === null`), we always proceed even if `kind`
  // matches `pickLoginFlow`'s default — otherwise clicking the highlighted
  // option in the method-picker silently no-ops because `activeFlow`
  // already reflects that default. Bug surfaced for Claude where
  // `pickLoginFlow → 'cli_browser'`, so clicking "Sign in with browser"
  // matched the default and nothing happened.
  if (selectedFlow.value !== null && kind === activeFlow.value) return;
  // Best-effort cancel — the session may already be terminal.
  try {
    await loginSession.cancel();
  } catch {
    /* ignore */
  }
  loginSession.reset();
  selectedFlow.value = kind;
  // Re-arm the auto-advance gate (only fires after a fresh 'running' state).
  autoAdvanceOnLoginComplete.value = false;
  await startUnifiedLogin();
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

// Only auto-advance from login → next step if THIS account's login actually
// went through a 'running' state for the user we're currently helping. Without
// this gate, a stale 'complete' from a prior account (or a fast-resolving
// cached-auth path) can fire goNext() before the user has even seen the OAuth
// flow — the second-account "skipped registering step" bug. Armed when start
// is called, disarmed on every currentStep change.
const autoAdvanceOnLoginComplete = ref(false);

// Set true in onUnmounted; every in-flight async tour broadcast checks this
// before calling setTourTarget/Guide/Title so a delayed broadcast after the
// wizard closes can never push a stale wiz-* selector to the host (which
// would leave the next page's tour overlay stuck on a spinner because it's
// hunting for a wizard element that no longer exists).
const isUnmounted = ref(false);

watch(currentStep, () => {
  autoAdvanceOnLoginComplete.value = false;
});

watch(
  () => loginSession.status.value,
  (status) => {
    if (status === 'running') {
      // Real session actually started for the current login step — arm the
      // auto-advance now (and only now).
      if (currentStep.value === 'login') {
        autoAdvanceOnLoginComplete.value = true;
      }
      return;
    }
    if (
      status === 'complete' &&
      currentStep.value === 'login' &&
      autoAdvanceOnLoginComplete.value
    ) {
      autoAdvanceOnLoginComplete.value = false;
      goNext();
    }
  }
);

// Set the abort flag in onBeforeUnmount (runs before Vue tears down child
// reactivity) so any async tour broadcast in flight bails out before it
// can call setTourTarget/Guide/Title with a now-stale wiz-* selector.
onBeforeUnmount(() => {
  isUnmounted.value = true;
});

onUnmounted(() => {
  setTourGuide(null);
  setTourTarget(null);
  setTourTitle(null);
  if (loginSession.status.value === 'running') {
    loginSession.cancel().catch(() => {});
  }
  stopProxyPoll();
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
      // Skip when "No, skip" is selected (input isn't rendered) OR the
      // user typed something. Optional field, so empty is a valid end state —
      // they can still advance via the Continue button at the bottom.
      done: () =>
        hasSubscription.value === 'no' || accountName.value.trim().length > 0,
    },
    {
      selector: '#wiz-email',
      titleKey: 'accountWizard.tour.sub.email.title',
      messageKey: 'accountWizard.tour.sub.email.message',
      // Same as name — skip when "No, skip" path or user filled in an email.
      done: () =>
        hasSubscription.value === 'no' || /.+@.+/.test(email.value),
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
      // Install message also tells the user they can Skip below if they
      // don't need the proxy — same screen, no need for a separate substep.
      messageKey: 'accountWizard.tour.proxy.install.message',
      done: () => cliproxyStatusChecked.value && cliproxyInstalled.value,
    },
    {
      selector: '[data-tour="wiz-proxy-start"]',
      titleKey: 'accountWizard.tour.proxy.start.title',
      // Start message bundles the skip option so users always know they can
      // bypass the proxy without us pointing at the Skip button after the
      // button's label has already changed to "Continue".
      messageKey: 'accountWizard.tour.proxy.start.message',
      done: () => proxyLoginStatus.value !== 'idle',
    },
    {
      selector: '[data-tour="wiz-proxy-callback"]',
      titleKey: 'accountWizard.tour.proxy.callback.title',
      messageKey: 'accountWizard.tour.proxy.callback.message',
      // Stay on this substep through 'running' / 'device_auth'. Done only on
      // terminal state — after success we advance to the Continue substep,
      // after error/skipped we likewise advance (the user will use Back/Skip
      // to recover, both still rendered).
      done: () =>
        proxyLoginStatus.value === 'success' ||
        proxyLoginStatus.value === 'skipped' ||
        proxyLoginStatus.value === 'error',
    },
    {
      // The Skip button's label flips to "Continue" once registration
      // succeeds (template line ~1396). Only spotlight it on success — the
      // earlier path (idle → click Skip) is covered by the Start substep's
      // bundled "click Skip" hint, so we never point at a button whose
      // label doesn't match what we're saying.
      selector: '[data-tour="wiz-proxy-skip"]',
      titleKey: 'accountWizard.tour.proxy.continue.title',
      messageKey: 'accountWizard.tour.proxy.continue.message',
      done: () => false,
    },
  ],
  plan: [
    // Plan dropdown first — the only meaningful choice on this step.
    {
      selector: '#wiz-plan',
      titleKey: 'accountWizard.tour.plan.pick.title',
      messageKey: 'accountWizard.tour.plan.pick.message',
      done: () => planOptions.value.length === 0 || selectedPlan.value !== '',
    },
    // Save button — final action. We mention the optional "set as default"
    // checkbox in the same guide so the tour doesn't stagnate on a no-op
    // (the standalone default substep had no done predicate, so it would
    // sit there forever waiting for an action that may never come).
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
// Resolve the current substep, skipping ones whose done() predicate is
// already true so we land on the next not-yet-completed substep. The
// activeTourSubstep watcher then handles missing-DOM-element gracefully
// (anchors on the step root and shows the substep's guide text) instead of
// surfacing a "not found" error.
const activeTourSubstep = computed<TourSubstep | null>(() => {
  const list = TOUR_SUBSTEPS[currentStep.value] ?? [];
  let i = tourSubstepIndex.value;
  while (i < list.length - 1 && list[i]?.done?.() === true) {
    i++;
  }
  return list[i] ?? null;
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
    // Cascade: skip past every consecutive done substep so we never land on
    // a substep whose UI element isn't rendered (e.g. wiz-proxy-install when
    // CLIProxyAPI is already installed → "...설치을(를) 찾을 수 없어요").
    while (
      tourSubstepIndex.value < list.length - 1 &&
      list[tourSubstepIndex.value]?.done?.() === true
    ) {
      tourSubstepIndex.value++;
    }
  },
);


// True while the wizard is mid-transition between steps — set the moment
// currentStep changes, cleared after the next step's root anchor is mounted.
// Suppresses tour-substep updates so we never push a target for a step whose
// DOM isn't on screen yet (which would surface "...찾을 수 없어요" 3 s later).
const stepLanding = ref(false);

// Sync-flush watcher so stepLanding flips BEFORE any other watcher (in
// particular the activeTourSubstep watcher below) can fire on the same
// currentStep change. Without this, that watcher would broadcast e.g.
// wiz-proxy-install for an instant before the async transition handler
// runs, and the overlay would surface a not-found fallback.
watch(currentStep, () => {
  stepLanding.value = true;
}, { flush: 'sync' });

// Broadcast a substep with a graceful fallback: if the substep's selector
// doesn't resolve to a live element after a short wait, anchor the spotlight
// on the step root instead — the user still sees the substep's guide text,
// no spinner, no "not found" race. Re-runs whenever the activeTourSubstep
// or the relevant proxy state changes.
async function broadcastSubstep(sub: TourSubstep | null): Promise<void> {
  if (isUnmounted.value) return;
  if (!sub) {
    setTourTarget(`[data-tour="wiz-${currentStep.value}"]`);
    setTourGuide(null);
    setTourTitle(null);
    return;
  }
  // Capture the substep at call time to bail if it changes mid-wait.
  const expected = sub;
  // Poll briefly for the element. Conditionally-rendered targets (e.g.
  // wiz-proxy-callback during device_auth) need a few ticks to mount.
  let el: Element | null = null;
  for (let i = 0; i < 20; i++) {
    if (isUnmounted.value || activeTourSubstep.value !== expected) return;
    el = typeof document !== 'undefined'
      ? document.querySelector(sub.selector)
      : null;
    if (el && (el as HTMLElement).getBoundingClientRect().width > 0) break;
    await new Promise((r) => setTimeout(r, 50));
  }
  if (isUnmounted.value || activeTourSubstep.value !== expected) return;
  if (el) {
    setTourTarget(sub.selector);
  } else {
    // Element never materialised — keep the spotlight on the step root
    // (always mounted) so the overlay never shows a not-found fallback.
    setTourTarget(`[data-tour="wiz-${currentStep.value}"]`);
  }
  setTourGuide(t(sub.messageKey));
  setTourTitle(sub.titleKey ? t(sub.titleKey) : null);
}

watch(activeTourSubstep, (sub) => {
  if (stepLanding.value) return;
  void broadcastSubstep(sub);
});

// Wait for the wizard step's root anchor to be in the DOM before resuming
// tour updates. Polls every 50 ms up to 3 s. Returns the moment the anchor
// is found (typical case: 1–2 nextTicks).
async function waitForStepLanded(stepName: WizardStep): Promise<void> {
  const sel = `[data-tour="wiz-${stepName}"]`;
  for (let i = 0; i < 60; i++) {
    if (isUnmounted.value) return;
    if (typeof document !== 'undefined' && document.querySelector(sel)) return;
    await new Promise((r) => setTimeout(r, 50));
  }
}

// On wizard step change: blank the tour overrides immediately so no stale
// target from the previous step is broadcast, then wait for the new step's
// DOM to land before letting the activeTourSubstep watcher push updates again.
watch(currentStep, async (newStep) => {
  if (isUnmounted.value) return;
  stepLanding.value = true;
  // Anchor on the wizard container during the transition — that element is
  // always in the DOM while the wizard is open, so the overlay neither shows
  // a loading spinner nor a "not found" fallback while the old step is
  // unmounting and the new step is settling. Title/guide cleared so the
  // tooltip itself stays neutral until we know which substep to land on.
  setTourTarget('[data-tour="account-wizard"]');
  setTourGuide(null);
  setTourTitle(null);
  tourSubstepIndex.value = 0;
  returnedFromOAuthTab.value = false;

  await waitForStepLanded(newStep);
  if (isUnmounted.value || currentStep.value !== newStep) return;
  // Allow any conditional sub-blocks to mount.
  await nextTick();
  if (isUnmounted.value || currentStep.value !== newStep) return;

  stepLanding.value = false;

  // Manually fire the substep update now that the DOM is fully ready.
  const list = TOUR_SUBSTEPS[newStep] ?? [];
  while (
    tourSubstepIndex.value < list.length - 1 &&
    list[tourSubstepIndex.value]?.done?.() === true
  ) {
    tourSubstepIndex.value++;
  }
  void broadcastSubstep(activeTourSubstep.value);
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
const proxySessionId = ref<string | null>(null);
let proxyPollHandle: ReturnType<typeof setInterval> | null = null;

function stopProxyPoll() {
  if (proxyPollHandle !== null) {
    clearInterval(proxyPollHandle);
    proxyPollHandle = null;
  }
}

function startProxyPoll() {
  stopProxyPoll();
  if (!proxySessionId.value) return;
  const id = proxySessionId.value;
  proxyPollHandle = setInterval(async () => {
    try {
      const s = await client.cliproxyLoginStatus(id);
      if (s.state === 'completed') {
        proxyLoginStatus.value = 'success';
        proxyLoginMessage.value = s.message || 'API proxy login completed';
        stopProxyPoll();
      } else if (s.state === 'failed' || s.state === 'timeout') {
        proxyLoginStatus.value = 'error';
        proxyLoginMessage.value = s.message;
        stopProxyPoll();
      }
      // 'running' / 'unknown' → keep polling
    } catch (e: unknown) {
      // Transient errors shouldn't kill the poll; log once and keep going.
      console.warn('[AccountWizard] cliproxy login status poll failed:', e);
    }
  }, 2000);
}

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
  stopProxyPoll();
  proxyLoginStatus.value = 'idle';
  proxyLoginMessage.value = '';
  proxyOauthUrl.value = '';
  proxyDeviceCode.value = '';
  proxyCallbackUrl.value = '';
  proxyCallbackError.value = '';
  proxySessionId.value = null;
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
      proxySessionId.value = res.session_id ?? null;
      // Auto-open the OAuth URL in the user's browser
      window.open(res.oauth_url, '_blank', 'noopener');
      if (res.device_code) {
        proxyLoginMessage.value = `Open the URL and enter code ${res.device_code}. We'll detect completion automatically.`;
      } else {
        proxyLoginMessage.value =
          'Complete OAuth in the browser; paste the callback URL below if it fails to redirect';
      }
      // Device-code flow has no browser callback — cliproxyapi polls the
      // OAuth provider server-side. Poll the session for completion.
      if (proxySessionId.value) {
        startProxyPoll();
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
  // Disarm the login auto-advance so the next account's login step won't
  // honour a stale 'complete' status from the first account.
  autoAdvanceOnLoginComplete.value = false;
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

    <!-- Step indicators (+ optional macOS Claude keychain warning above) -->
    <template v-else-if="currentStep !== 'done'">
      <!-- The Claude CLI on darwin stores its OAuth credential in a single
           "Claude Safe Storage" / "Claude Key" Keychain entry that is NOT
           scoped by CLAUDE_CONFIG_DIR. Adding a 2nd Claude account replaces
           the first — the user gets two rows in the playground but only one
           credential is actually live. -->
      <div v-if="showClaudeKeychainWarning" class="wizard-warning" role="alert">
        <svg
          viewBox="0 0 24 24" fill="none" stroke="currentColor"
          stroke-width="2" stroke-linecap="round" stroke-linejoin="round"
          width="18" height="18" aria-hidden="true"
        >
          <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0Z" />
          <line x1="12" y1="9" x2="12" y2="13" />
          <line x1="12" y1="17" x2="12.01" y2="17" />
        </svg>
        <div>
          <strong>macOS Keychain limitation:</strong>
          Claude CLI on macOS stores its credential in a single shared Keychain
          entry, so logging in here will replace your existing Claude credential
          ({{ existingClaudeCount }} account{{ existingClaudeCount === 1 ? '' : 's' }}
          registered). The previous account row will appear "ready" but actually
          point at this new login.
        </div>
      </div>
      <!-- Collapsed indicator: 3 deduped phases (Setup / Login / Finish).
           The active dot follows the phase of the internal currentStep; the
           full 5-step navigation underneath is unchanged. -->
      <div class="wizard-steps">
      <div
        v-for="(phase, idx) in PHASE_ORDER"
        :key="phase"
        class="step-indicator"
        :class="{
          active: currentPhase === phase,
          completed: currentPhaseIndex > idx,
        }"
      >
        <span class="step-number">
          <template v-if="currentPhaseIndex > idx">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" width="12" height="12">
              <polyline points="20 6 9 17 4 12"/>
            </svg>
          </template>
          <template v-else>{{ idx + 1 }}</template>
        </span>
        <span class="step-label">{{ phaseLabels[phase] }}</span>
      </div>
      </div>
    </template>

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
        <!-- One-line CLI status badge. For keyless kinds (OpenRouter,
             generic OpenAI-compatible) and Antigravity there's nothing to
             install, so the badge reads "No CLI required". The config dir is
             still auto-generated silently (see suggestConfigPath) and exposed
             behind the Advanced toggle below for power users. -->
        <div
          v-if="requiresNoCli"
          class="status-card status-ok"
          data-tour="wiz-cli-status"
        >
          <div class="status-icon">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="20" height="20">
              <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/>
              <polyline points="22 4 12 14.01 9 11.01"/>
            </svg>
          </div>
          <div class="status-info">
            <span class="status-title">{{ backendName }}</span>
            <span class="status-detail">{{ t('accountWizard.noCliRequired') }}</span>
          </div>
        </div>
        <div
          v-else
          class="status-card"
          :class="cliInstalled ? 'status-ok' : 'status-warn'"
          data-tour="wiz-cli-status"
        >
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

        <!-- Advanced: per-account config dir override. Hidden by default —
             the path is auto-generated and the server creates the dir on
             login. Power users can expand this to set a custom path. -->
        <details v-if="configPath" class="config-advanced">
          <summary>{{ t('accountWizard.customizePath') }}</summary>
          <div class="config-dir-section">
            <div class="config-dir-label">{{ t('accountWizard.configPath') }}</div>
            <div class="form-group compact">
              <input
                v-model="configPath"
                type="text"
                :placeholder="`e.g., ~/.${backendKind}-personal`"
                @input="configPathManuallyEdited = true"
              />
            </div>
            <div v-if="dirError" class="error-text">{{ dirError }}</div>
          </div>
        </details>
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
        <!-- Method picker: shown when the backend advertises >1 login
             flow AND the user hasn't picked one yet. The login step's
             auto-start is gated until a pick happens, so we mirror the
             claude-style "choose how to log in" menu UX rather than
             silently committing the user to a flow they'd then have to
             switch out of. -->
        <div
          v-if="hasMultipleFlows && backendMeta && selectedFlow === null && loginStatus === 'idle'"
          class="login-method-picker"
        >
          <h4 class="login-method-picker__heading">Choose a login method</h4>
          <p class="login-method-picker__hint">
            Pick how you want to authenticate {{ backendName }}. You can switch
            later if your first choice doesn't work.
          </p>
          <div class="login-method-picker__options">
            <button
              v-for="f in backendMeta.login_flows"
              :key="f.kind"
              type="button"
              class="login-method-picker__btn"
              @click="switchLoginFlow(f.kind as LoginFlowKind)"
            >
              <strong class="login-method-picker__title">{{ f.display_name }}</strong>
              <span v-if="f.description" class="login-method-picker__desc">{{ f.description }}</span>
            </button>
          </div>
        </div>

        <!-- Compact flow switcher: shown once a method is chosen so the
             user can switch mid-flow without leaving the wizard. -->
        <div
          v-if="hasMultipleFlows && backendMeta && (selectedFlow !== null || loginStatus !== 'idle')"
          class="login-flow-switcher"
        >
          <span class="login-flow-switcher__label">Login method:</span>
          <div class="login-flow-switcher__options">
            <button
              v-for="f in backendMeta.login_flows"
              :key="f.kind"
              type="button"
              class="login-flow-switcher__btn"
              :class="{ 'login-flow-switcher__btn--active': activeFlow === f.kind }"
              :disabled="loginStatus === 'completed'"
              :title="f.description"
              @click="switchLoginFlow(f.kind as LoginFlowKind)"
            >{{ f.display_name }}</button>
          </div>
        </div>

        <!-- v0.6.4: surface login-start failures so the user isn't stuck
             on a spinner when the /begin call fails. Includes a Retry
             button so they don't have to leave the wizard. -->
        <div v-if="loginStartError" class="login-status login-error">
          <strong>Login could not start.</strong>
          <p>{{ loginStartError }}</p>
          <button class="btn btn-secondary" @click="startUnifiedLogin">
            Retry
          </button>
        </div>

        <!-- Idle / Connecting — only render the spinner when we've actually
             dispatched a login (single-flow backend OR user picked a method).
             Without this gate the multi-flow case showed "Starting login…"
             forever because we'd never call startUnifiedLogin. -->
        <template
          v-else-if="(loginStatus === 'idle' || loginStatus === 'connecting') &&
                     !(hasMultipleFlows && selectedFlow === null)"
        >
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
              <span v-if="proxyDeviceCode">
                Open the URL below, sign in, and enter the device code. We'll detect completion automatically.
              </span>
              <span v-else>
                A browser window should have opened. Sign in, then the page will redirect to <code>localhost</code> — that redirect will fail (this is normal). Copy the full URL from the browser address bar and paste it below.
              </span>
            </div>
            <a v-if="proxyOauthUrl" :href="proxyOauthUrl" target="_blank" rel="noopener" class="proxy-oauth-link">
              {{ proxyOauthUrl }}
            </a>
            <div v-if="proxyDeviceCode" class="proxy-device-code-card">
              <span class="proxy-device-code-label">Your device code:</span>
              <code class="proxy-device-code-value">{{ proxyDeviceCode }}</code>
            </div>
            <div v-if="proxyDeviceCode" class="proxy-waiting" data-tour="wiz-proxy-callback">
              <div class="spinner-sm"></div>
              <span>Waiting for you to enter the code…</span>
            </div>
            <div v-else class="proxy-callback-section" data-tour="wiz-proxy-callback">
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

.proxy-waiting {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem 0.75rem;
  font-size: 0.85rem;
  color: var(--text-secondary);
  background: var(--bg-tertiary, rgba(0, 0, 0, 0.3));
  border-radius: 6px;
  margin-top: 0.25rem;
}

.login-method-picker {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  padding: 1rem;
  border: 1px solid var(--border-default);
  border-radius: 8px;
  background: var(--bg-tertiary, rgba(0, 0, 0, 0.2));
}
.login-method-picker__heading {
  margin: 0;
  font-size: 0.95rem;
  color: var(--text-primary);
  font-weight: 600;
}
.login-method-picker__hint {
  margin: 0 0 0.25rem;
  font-size: 0.8125rem;
  color: var(--text-secondary);
  line-height: 1.45;
}
.login-method-picker__options {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}
.login-method-picker__btn {
  appearance: none;
  text-align: left;
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  padding: 0.75rem 0.875rem;
  border: 1px solid var(--border-default);
  border-radius: 6px;
  background: var(--bg-secondary);
  color: var(--text-primary);
  font: inherit;
  cursor: pointer;
  transition: border-color 120ms ease, background 120ms ease;
}
.login-method-picker__btn:hover {
  border-color: var(--primary-color);
  background: var(--bg-hover);
}
.login-method-picker__title {
  font-size: 0.9rem;
  font-weight: 600;
}
.login-method-picker__desc {
  font-size: 0.8125rem;
  color: var(--text-secondary);
  line-height: 1.45;
}

.login-flow-switcher {
  display: flex;
  align-items: center;
  gap: 0.625rem;
  margin: 0 0 0.875rem;
  padding: 0.5rem 0.75rem;
  border: 1px solid var(--border-default);
  border-radius: 6px;
  background: var(--bg-tertiary, rgba(0, 0, 0, 0.2));
  font-size: 0.8125rem;
}
.login-flow-switcher__label {
  color: var(--text-secondary);
  font-weight: 500;
  flex-shrink: 0;
}
.login-flow-switcher__options {
  display: flex;
  gap: 0.25rem;
  flex-wrap: wrap;
}
.login-flow-switcher__btn {
  appearance: none;
  background: transparent;
  border: 1px solid transparent;
  color: var(--text-secondary);
  padding: 0.25rem 0.625rem;
  border-radius: 4px;
  font: inherit;
  cursor: pointer;
  transition: background 120ms ease, color 120ms ease, border-color 120ms ease;
}
.login-flow-switcher__btn:hover:not(:disabled) {
  background: var(--bg-hover);
  color: var(--text-primary);
}
.login-flow-switcher__btn--active {
  background: var(--primary-color);
  border-color: var(--primary-color);
  color: var(--text-on-accent);
  font-weight: 600;
}
.login-flow-switcher__btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.wizard-warning {
  display: flex;
  align-items: flex-start;
  gap: 0.625rem;
  padding: 0.75rem 0.875rem;
  margin: 0 1rem 0.75rem;
  font-size: 0.85rem;
  line-height: 1.45;
  color: var(--text-primary);
  background: rgba(245, 158, 11, 0.08);
  border: 1px solid rgba(245, 158, 11, 0.35);
  border-left: 3px solid var(--accent-amber, #f59e0b);
  border-radius: 6px;
}
.wizard-warning svg {
  color: var(--accent-amber, #f59e0b);
  flex-shrink: 0;
  margin-top: 1px;
}
.wizard-warning strong { color: var(--accent-amber, #f59e0b); }

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
