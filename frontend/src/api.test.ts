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
