export interface UsageWindowDTO {
  window_type: string;
  usage_percent: number;
  resets_at: string | null;
  tokens_used: number | null;
  tokens_limit: number | null;
}

export interface AccountHealthDTO {
  backend_id: string;
  kind: string;
  windows: UsageWindowDTO[];
  rate_limited_until: string | null;
  rate_limit_reason: string | null;
  last_used_at: string | null;
  last_polled_at: string | null;
}

export interface PickResultDTO {
  backend_id: string;
  kind: string;
  isolation_dir: string;
  retry_after: string | null;
}

export interface FallbackChainEntryDTO {
  backend_id: string;
  priority: number;
}
