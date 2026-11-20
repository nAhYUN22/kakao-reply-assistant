export interface Job {
  job_id: string;
  state: string;
  reason_codes: string[];
  due_at: string | null;
  created_at: string;
  updated_at: string;
  incoming_count: number;
  attempt_count: number;
}

export interface RuntimeState {
  transport: 'mock';
  mode: 'off' | 'draft' | 'auto';
  live_send_enabled: false;
  now: string;
  binding_id: 'synthetic-partner';
  reply_delay: number;
  settle: number;
  human_cooldown: number;
  pending_due_at: string | null;
  paused_reason: string | null;
  simulated_send_count: number;
  jobs: Job[];
}

export interface JobDetail extends Job { reply_text: string | null }
export type MessageOrigin = 'partner' | 'owner' | 'unknown';

export interface StorageStatus {
  schema_version: 2;
  body_storage: 'aead' | 'memory_only';
  raw_retention_days: number;
}

export interface KakaoStatus { installed: boolean }
export interface KakaoChoice { id: string; title: string }
export interface KakaoReadResult {
  baseline_count: number;
  new_count: number;
  status: string;
}

export interface KakaoDirectReadResult { status: 'READ'; count: number }

export interface KakaoReplyDraft {
  draft_id: string;
  in_reply_to: string;
  text: string;
  context_count: number;
  expires_in_seconds: number;
}

export interface KakaoReplyAttempt {
  id: string;
  at: string;
  status: 'CONFIRMED_LOCAL' | 'DELIVERY_UNKNOWN';
  requires_review: boolean;
}
