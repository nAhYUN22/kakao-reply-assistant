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
