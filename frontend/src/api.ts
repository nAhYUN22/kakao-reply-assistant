import type { JobDetail, MessageOrigin, RuntimeState, StorageStatus } from './types';

let session: Promise<string> | undefined;

async function json<T>(path: string, init: RequestInit = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, { ...init, signal: AbortSignal.timeout(15000) });
  } catch {
    throw new Error('로컬 서버에 연결하지 못했습니다. 서버 실행 상태를 확인한 뒤 다시 시도해 주세요.');
  }
  if (!response.ok) {
    // Never echo raw response bodies or submitted conversation data in UI errors.
    if (response.status === 401 || response.status === 403) throw new Error('로컬 세션이 만료되었습니다. 연결을 다시 확인해 주세요.');
    if (response.status === 409) throw new Error('현재 상태에서는 실행할 수 없습니다. 상태를 새로 확인해 주세요.');
    if (response.status === 422) throw new Error('입력값을 확인해 주세요. 합성 메시지와 허용된 시간만 입력할 수 있습니다.');
    throw new Error('요청을 완료하지 못했습니다. 상태를 새로 확인한 뒤 다시 시도해 주세요.');
  }
  try {
    return await response.json() as T;
  } catch {
    throw new Error('서버 응답을 확인하지 못했습니다. 상태를 다시 확인해 주세요.');
  }
}

async function request<T>(path: string, body?: unknown, method?: 'DELETE'): Promise<T> {
  session ??= json<{ token: string }>('/api/session').then(value => value.token).catch(error => { session = undefined; throw error; });
  const token = await session;
  return json<T>(path, {
    method: method ?? (body === undefined ? 'GET' : 'POST'),
    headers: { 'X-Session-Token': token, ...(body === undefined ? {} : { 'Content-Type': 'application/json' }) },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
}

export const api = {
  state: () => request<RuntimeState>('/api/state'),
  storage: () => request<StorageStatus>('/api/storage'),
  deleteBody: (id: string) => request<RuntimeState>(`/api/jobs/${encodeURIComponent(id)}/body`, undefined, 'DELETE'),
  reconnect: () => { session = undefined; return request<RuntimeState>('/api/state'); },
  start: (mode: 'auto' | 'draft') => request<RuntimeState>('/api/simulator/start', { mode }),
  message: (text: string, origin: MessageOrigin) => request<RuntimeState>('/api/simulator/messages', { text, origin }),
  advance: (seconds: number) => request<RuntimeState>('/api/simulator/advance', { seconds }),
  pause: () => request<RuntimeState>('/api/runtime/pause', {}),
  detail: (id: string) => request<JobDetail>(`/api/jobs/${encodeURIComponent(id)}`),
};
