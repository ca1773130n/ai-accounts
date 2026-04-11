export { WIRE_PROTOCOL_VERSION } from './protocol/wire';
export type * from './protocol/wire';
export { AiAccountsClient } from './client';
export type { ClientOptions, ApiError, BackendDTO, DetectResultDTO } from './client';
export type { paths as AiAccountsApiPaths } from './client/generated';

export const version = '0.0.0';
