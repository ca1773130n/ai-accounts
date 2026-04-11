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
export { createAccountWizard } from './machines/accountWizard';
export type {
  AccountWizard,
  WizardState,
  CreateAccountWizardOptions,
} from './machines/accountWizard';

export const version = '0.0.0';
