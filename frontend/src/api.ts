import type { JobDetail, MessageOrigin, RuntimeState, StorageStatus, KakaoStatus, KakaoChoice, KakaoReadResult, KakaoDirectReadResult, KakaoReplyDraft, KakaoReplyAttempt } from './types';

let session: Promise<string> | undefined;

const diagnosticErrors: Record<string, string> = {
  DRAFT_EXPIRED: '초안이 만료되었습니다. 최근 대화로 답장을 다시 만들어 주세요.',
  CONTEXT_CHANGED: '대화가 달라져 발송을 취소했습니다. 마지막 메시지를 다시 확인해 주세요.',
  LAST_NOT_PARTNER: '마지막 메시지가 상대의 말로 확인되지 않아 답장을 만들 수 없습니다.',
  EMPTY_CONTEXT: '최근에 읽을 수 있는 대화가 없습니다.',
  MODEL_UNAVAILABLE: '로컬 Ollama 모델에 연결할 수 없습니다. Ollama 실행 상태와 서버에 설정한 모델 이름을 확인해 주세요.',
  MODEL_INVALID_RESPONSE: '로컬 모델이 사용할 수 있는 답장 형식을 반환하지 않아 생성을 보류했습니다.',
  GENERATION_UNSUPPORTED: '기본 생성 규칙에서 지원하지 않는 대화입니다. 자유로운 대화를 처리하려면 설치된 로컬 Ollama 모델을 서버에 설정해 주세요.',
  STALE_INPUT: '마지막 메시지 시각을 확인할 수 없거나 최근 30분 이내의 메시지가 아니어서 발송을 보류했습니다.',
  ATTEMPT_NOT_FOUND: '해당 발송 시도를 찾을 수 없습니다. 이력을 다시 열어 주세요.',
  GENERATION_HOLD: '최근 대화에서 답장에 필요한 근거를 확인하지 못해 생성을 보류했습니다.',
  DELIVERY_UNKNOWN: '발송 결과를 확인할 수 없습니다. 카카오톡 대화창을 확인한 뒤 아래 이력에 확인을 기록해 주세요.',
  ALREADY_ATTEMPTED: '이 메시지에 대한 발송 시도가 이미 있습니다. 카카오톡 대화창에서 결과를 확인해 주세요.',
  AMBIGUOUS_AUTHOR: '최근 메시지를 누가 썼는지 확인할 수 없어 답장을 보류했습니다.',
  UNSUPPORTED_CONTENT: '최근 대화에 처리할 수 없는 메시지가 있어 답장을 보류했습니다.',
  LIVE_SEND_UNAVAILABLE: '이 환경에서는 대상과 전송 경로를 검증할 수 없어 실제 발송을 사용할 수 없습니다.',
  STOPPED: '중지 요청으로 초안을 폐기했습니다.',
  REPLY_BUSY: '다른 답장 요청을 처리하고 있습니다. 완료 후 다시 확인해 주세요.',
  DIRECT_READ_TIMEOUT: '이름으로 읽기 요청 시간이 초과되었습니다. 읽기 결과를 확인하지 못했습니다.',
  DIRECT_READ_FAILED: '이름으로 대화를 읽지 못했습니다. 원인은 확인되지 않았습니다. 이름과 카카오톡 상태를 확인해 주세요.',
  TITLE_MISMATCH: 'kmsg가 반환한 대화 제목이 입력한 이름과 달라 읽기 결과를 버렸습니다. 정확한 대화 이름을 확인해 주세요.',
  INVALID_CHAT_NAME: '대화 이름이 비어 있거나 허용되지 않는 형식입니다. 카카오톡에 표시된 이름을 입력해 주세요.',
  PROBE_BUSY: '다른 읽기 진단이 진행 중입니다. 잠시 후 다시 시도해 주세요.',
  BINARY_UNAVAILABLE: 'kmsg 실행 파일을 찾지 못했습니다. 설치 후 서버에서 실행 파일을 찾을 수 있는지 확인해 주세요.',
  AMBIGUOUS_TARGET: '대상을 명확하게 구분할 수 없습니다. 대화 목록과 원하는 1:1 대상을 다시 확인해 주세요.',
  BINDING_CHANGED: '선택한 대화 정보가 변경되었습니다. 목록을 다시 조회하고 대상을 확인해 주세요.',
  CATALOG_LIMIT_REACHED: '조회 가능한 대화 목록 한도를 넘었습니다. 대상 선택을 확정하지 못했습니다.',
  CATALOG_TIMEOUT: '대화 목록 조회 시간이 초과되었습니다. 이름 일치 여부는 확인하지 못했습니다. 잠시 후 다시 조회해 주세요.',
  CATALOG_TOO_LARGE: '대화 목록 응답이 허용된 크기를 넘었습니다. 전체 목록을 확인하지 못해 검색을 진행하지 않았습니다.',
  INVALID_CATALOG: '대화 목록 응답이 불완전하거나 올바르지 않아 검색을 진행하지 못했습니다. 목록을 다시 조회해 주세요.',
  CATALOG_FAILED: '대화 목록 조회에 실패했습니다. 원인은 확인되지 않았습니다. 카카오톡 상태를 확인한 뒤 다시 조회해 주세요.',
  MCP_READ_FAILED: '카카오톡 읽기를 완료하지 못했습니다. kmsg 권한과 대상 대화의 별도 창 표시를 확인해 주세요.',
  READ_CHECK_FAILED: '대화 읽기 결과를 확인하지 못했습니다. 대상과 권한을 확인한 뒤 다시 시도해 주세요.',
};

const uncertainSend = '발송 결과를 확인할 수 없습니다. 카카오톡 대화창에서 직접 확인해 주세요.';

async function json<T>(path: string, init: RequestInit = {}, timeoutMs = 15000): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, { ...init, signal: AbortSignal.timeout(timeoutMs) });
  } catch {
    if (path === '/api/kakao/reply/send') throw new Error(uncertainSend);
    throw new Error('로컬 서버에 연결하지 못했습니다. 서버 실행 상태를 확인한 뒤 다시 시도해 주세요.');
  }
  if (!response.ok) {
    if (path === '/api/kakao/read-by-name' && (response.status === 404 || response.status === 405)) throw new Error('이름으로 바로 읽기 API가 없는 서버입니다. 현재 서버를 시작한 터미널에서 재시작해 주세요.');
    // Only fixed, recognized reason codes become UI text; never echo raw response data.
    if (path.startsWith('/api/kakao/')) {
      let detail: unknown;
      try { detail = (await response.json())?.detail; } catch { /* Fall through to generic status. */ }
      if (typeof detail === 'string' && Object.hasOwn(diagnosticErrors, detail)) throw new Error(diagnosticErrors[detail]);
      if (path.startsWith('/api/kakao/reply/') && (response.status === 404 || response.status === 405)) throw new Error('답장 기능을 찾지 못했습니다. 현재 서버를 시작한 터미널에서 재시작해 주세요.');
      if (path === '/api/kakao/reply/send' && response.status >= 500) throw new Error(uncertainSend);
    }
    if (response.status === 401 || response.status === 403) throw new Error('로컬 세션이 만료되었습니다. 연결을 다시 확인해 주세요.');
    if (response.status === 409) throw new Error('현재 상태에서는 실행할 수 없습니다. 상태를 새로 확인해 주세요.');
    if (response.status === 422) throw new Error('입력값을 확인해 주세요. 합성 메시지와 허용된 시간만 입력할 수 있습니다.');
    throw new Error('요청을 완료하지 못했습니다. 상태를 새로 확인한 뒤 다시 시도해 주세요.');
  }
  try {
    return await response.json() as T;
  } catch {
    if (path === '/api/kakao/reply/send') throw new Error(uncertainSend);
    throw new Error('서버 응답을 확인하지 못했습니다. 상태를 다시 확인해 주세요.');
  }
}

async function request<T>(path: string, body?: unknown, method?: 'DELETE', timeoutMs = 15000): Promise<T> {
  session ??= json<{ token: string }>('/api/session').then(value => value.token).catch(error => { session = undefined; throw error; });
  const token = await session;
  return json<T>(path, {
    method: method ?? (body === undefined ? 'GET' : 'POST'),
    headers: { 'X-Session-Token': token, ...(body === undefined ? {} : { 'Content-Type': 'application/json' }) },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  }, timeoutMs);
}

export const api = {
  kakaoStatus: () => request<KakaoStatus>('/api/kakao/status'),
  kakaoReadByName: (name: string) => request<KakaoDirectReadResult>('/api/kakao/read-by-name', { name, one_to_one_confirmed: true }, undefined, 120000),
  kakaoPrepareReply: (name: string) => request<KakaoReplyDraft>('/api/kakao/reply/prepare', { name, one_to_one_confirmed: true }, undefined, 120000),
  kakaoReplyHistory: () => request<{ attempts: KakaoReplyAttempt[] }>('/api/kakao/reply/history'),
  kakaoReviewAttempt: (id: string) => request<unknown>('/api/kakao/reply/review', { attempt_id: id, confirmed: true }),
  kakaoSendReply: (draftId: string) => request<{ status: 'CONFIRMED_LOCAL' }>('/api/kakao/reply/send', { draft_id: draftId, confirmed: true }, undefined, 120000),
  kakaoCatalog: () => request<{ choices: KakaoChoice[] }>('/api/kakao/catalog', {}, undefined, 120000),
  kakaoVerify: (id: string, allowOpenWindow = false) => request<KakaoReadResult>('/api/kakao/verify', { id, one_to_one_confirmed: true, allow_open_window: allowOpenWindow }, undefined, 120000),
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
