import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

beforeEach(() => { vi.resetModules(); });
afterEach(() => { vi.unstubAllGlobals(); });
const response = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

describe('로컬 API 경계', () => {
  it('세션 토큰을 메모리에 재사용하고 모든 상태 변경 요청 헤더에 보낸다', async () => {
    const store = vi.fn();
    vi.stubGlobal('localStorage', { setItem: store });
    vi.stubGlobal('sessionStorage', { setItem: store });
    const fetcher = vi.fn().mockResolvedValueOnce(response({ token: 'synthetic-session-token' })).mockResolvedValueOnce(response({ mode: 'off' })).mockResolvedValueOnce(response({ mode: 'auto' }));
    vi.stubGlobal('fetch', fetcher);
    const { api } = await import('./api');
    await api.state(); await api.start('auto');
    expect(fetcher).toHaveBeenCalledTimes(3);
    expect(fetcher.mock.calls[0][0]).toBe('/api/session');
    expect(fetcher.mock.calls[2][1]).toMatchObject({ method: 'POST', headers: { 'X-Session-Token': 'synthetic-session-token', 'Content-Type': 'application/json' }, body: '{"mode":"auto"}' });
    expect(store).not.toHaveBeenCalled();
  });

  it('오류 응답에 포함된 원문을 오류 메시지에 재출력하지 않는다', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(response({ token: 'synthetic-session-token' })).mockResolvedValueOnce(response({ detail: 'SYNTHETIC_PRIVATE_TEXT' }, 422)));
    const { api } = await import('./api');
    await expect(api.message('SYNTHETIC_PRIVATE_TEXT', 'partner')).rejects.toThrow('입력값을 확인해 주세요.');
  });

  it('잘못된 JSON 응답도 본문 없이 안내한다', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(new Response('SYNTHETIC_PRIVATE_TEXT', { status: 200 })));
    const { api } = await import('./api');
    await expect(api.state()).rejects.toThrow('서버 응답을 확인하지 못했습니다.');
  });

  it('실패한 세션 발급을 캐시에 고정하지 않아 다시 연결할 수 있다', async () => {
    const fetcher = vi.fn().mockRejectedValueOnce(new Error('network')).mockResolvedValueOnce(response({ token: 'synthetic-session-token' })).mockResolvedValueOnce(response({ mode: 'off' }));
    vi.stubGlobal('fetch', fetcher);
    const { api } = await import('./api');
    await expect(api.state()).rejects.toThrow('로컬 서버에 연결하지 못했습니다.');
    await expect(api.state()).resolves.toEqual({ mode: 'off' });
    expect(fetcher.mock.calls[1][0]).toBe('/api/session');
  });
});


describe('생성문 관리 API', () => {
  it('저장소 상태를 인증된 GET 요청으로 조회한다', async () => {
    const storage = { schema_version: 2, body_storage: 'aead', raw_retention_days: 7 };
    const fetcher = vi.fn().mockResolvedValueOnce(response({ token: 'synthetic-session-token' })).mockResolvedValueOnce(response(storage));
    vi.stubGlobal('fetch', fetcher);
    const { api } = await import('./api');
    await expect(api.storage()).resolves.toEqual(storage);
    expect(fetcher.mock.calls[1][0]).toBe('/api/storage');
    expect(fetcher.mock.calls[1][1]).toMatchObject({ method: 'GET', headers: { 'X-Session-Token': 'synthetic-session-token' } });
  });

  it('생성문 삭제는 토큰을 포함한 DELETE 요청이며 본문을 보내지 않는다', async () => {
    const fetcher = vi.fn().mockResolvedValueOnce(response({ token: 'synthetic-session-token' })).mockResolvedValueOnce(response({ mode: 'off' }));
    vi.stubGlobal('fetch', fetcher);
    const { api } = await import('./api');
    await api.deleteBody('synthetic/job');
    expect(fetcher.mock.calls[1][0]).toBe('/api/jobs/synthetic%2Fjob/body');
    expect(fetcher.mock.calls[1][1]).toMatchObject({ method: 'DELETE', headers: { 'X-Session-Token': 'synthetic-session-token' } });
    expect(fetcher.mock.calls[1][1].body).toBeUndefined();
    expect(fetcher.mock.calls[1][1].headers['Content-Type']).toBeUndefined();
  });
});

describe('카카오 읽기 진단 API', () => {
  it('인증된 목록·읽기 요청에만 긴 timeout과 명시적 1:1 확인을 적용한다', async () => {
    const timeout = vi.spyOn(AbortSignal, 'timeout');
    const fetcher = vi.fn().mockResolvedValueOnce(response({ token: 'synthetic-session-token' })).mockResolvedValueOnce(response({ installed: true })).mockResolvedValueOnce(response({ choices: [] })).mockResolvedValueOnce(response({ baseline_count: 0, new_count: 0, status: 'UNCHANGED' }));
    vi.stubGlobal('fetch', fetcher);
    const { api } = await import('./api');
    await api.kakaoStatus(); await api.kakaoCatalog(); await api.kakaoVerify('synthetic-room');
    expect(fetcher.mock.calls[1][0]).toBe('/api/kakao/status');
    expect(fetcher.mock.calls[1][1]).toMatchObject({ method: 'GET' });
    expect(fetcher.mock.calls[2][1]).toMatchObject({ method: 'POST', body: '{}' });
    expect(fetcher.mock.calls[3][1]).toMatchObject({ method: 'POST', headers: { 'X-Session-Token': 'synthetic-session-token' }, body: '{"id":"synthetic-room","one_to_one_confirmed":true,"allow_open_window":false}' });
    expect(timeout.mock.calls.map(call => call[0])).toEqual([15000, 15000, 120000, 120000]);
    timeout.mockRestore();
  });

  it.each([['PROBE_BUSY', '다른 읽기 진단이 진행 중'], ['BINARY_UNAVAILABLE', 'kmsg 실행 파일을 찾지 못했습니다'], ['AMBIGUOUS_TARGET', '대상을 명확하게 구분할 수 없습니다'], ['BINDING_CHANGED', '선택한 대화 정보가 변경되었습니다'], ['CATALOG_LIMIT_REACHED', '대화 목록 한도'], ['CATALOG_FAILED', '대화 목록을 읽지 못했습니다'], ['MCP_READ_FAILED', '대상 대화의 별도 창 표시'], ['READ_CHECK_FAILED', '대화 읽기 결과를 확인하지 못했습니다']])('공개 오류 코드 %s를 고정된 한국어 안내로 변환한다', async (code, expected) => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(response({ token: 'synthetic-session-token' })).mockResolvedValueOnce(response({ detail: code }, 409)));
    const { api } = await import('./api');
    await expect(api.kakaoVerify('synthetic-room')).rejects.toThrow(expected);
  });

  it('알 수 없는 오류 응답의 대화 이름이나 원문을 재출력하지 않는다', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(response({ token: 'synthetic-session-token' })).mockResolvedValueOnce(response({ detail: 'SYNTHETIC_PRIVATE_TITLE' }, 500)));
    const { api } = await import('./api');
    await expect(api.kakaoCatalog()).rejects.toThrow('요청을 완료하지 못했습니다. 상태를 새로 확인한 뒤 다시 시도해 주세요.');
  });
});


it('창 열기 허용은 명시적으로 true를 선택한 읽기 요청에만 전달한다', async () => {
  const fetcher = vi.fn().mockResolvedValueOnce(response({ token: 'synthetic-session-token' })).mockResolvedValueOnce(response({ baseline_count: 0, new_count: 0, status: 'UNCHANGED' }));
  vi.stubGlobal('fetch', fetcher);
  const { api } = await import('./api');
  await api.kakaoVerify('synthetic-room', true);
  expect(JSON.parse(fetcher.mock.calls[1][1].body)).toEqual({ id: 'synthetic-room', one_to_one_confirmed: true, allow_open_window: true });
});
