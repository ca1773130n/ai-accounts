export { WIRE_PROTOCOL_VERSION } from './protocol/wire';
export type * from './protocol/wire';
export { AiAccountsClient } from './client';
export type {
  ClientOptions,
  ApiError,
  BackendDTO,
  DetectResultDTO,
  LoginResponseDTO,
  OAuthDeviceLoginDTO,
  OnboardingStateDTO,
  DetectResultsDTO,
} from './client';
export type { paths as AiAccountsApiPaths } from './client/generated';
export type {
  LoginEvent,
  UrlPrompt,
  TextPrompt,
  StdoutChunk,
  ProgressUpdate,
  LoginComplete,
  LoginFailed,
  PromptAnswer,
  LoginFlowKind,
} from './types/login';
export type {
  BackendMetadata,
  InstallCheck,
  InputSpec,
  LoginFlowSpec,
  PlanOption,
} from './types/metadata';
export type {
  InstallResult,
  CliproxyStatus,
  CliproxyInstallResult,
  CliproxyLoginBeginResponse,
  CliproxyCallbackForwardResponse,
} from './types/install';
export type { AiAccountsEvent, AiAccountsEventHandler } from './events';
export type { PtySessionDTO, PtySpawnRequest } from './types/pty';
export { PtySocket } from './client/pty-socket';
export type { PtySocketOptions } from './client/pty-socket';
export type {
  ChatSessionDTO,
  ChatSessionDetailDTO,
  ChatMessageDTO,
  ChatDelta,
} from './types/chat';
export { createAccountWizard } from './machines/accountWizard';
export type {
  AccountWizard,
  WizardState,
  CreateAccountWizardOptions,
} from './machines/accountWizard';
export { createOnboardingFlow } from './machines/onboardingFlow';
export type {
  OnboardingFlowMachine,
  OnboardingMachineState,
  CreateOnboardingFlowOptions,
} from './machines/onboardingFlow';

export const version = '0.0.0';
