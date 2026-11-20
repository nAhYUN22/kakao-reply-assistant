import { useEffect, useRef, useState, type FormEvent } from 'react';
import { api } from './api';
import { KakaoDiagnostics } from './KakaoDiagnostics';
import type { JobDetail, MessageOrigin, RuntimeState, StorageStatus } from './types';

const states: Record<string, string> = {
  PENDING: '답장 대기', GENERATING: '답장 생성 중', READY: '초안 준비', DISPATCHING: '모의 발송 중',
  CONFIRMED_LOCAL: '모의 발송 확인', CANCELED_HUMAN: '본인 답장으로 취소', CANCELED_STALE: '변경으로 취소',
  SKIPPED_POLICY: '정책에 따라 보류', FAILED_BEFORE_DISPATCH: '발송 전 실패', DELIVERY_UNKNOWN: '결과 확인 필요',
};
const reasons: Record<string, string> = {
  STORAGE_UNAVAILABLE: '생성문 저장소를 사용할 수 없음', BODY_DELETED: '로컬 생성문 삭제됨',
  ROUTINE_REPLY: '일상 대화', ACKNOWLEDGEMENT: '짧은 확인과 공감', MISSING_FACT: '확인된 정보 부족',
  CONFLICTING_FACTS: '정보 충돌', EXPIRED_FACT: '정보 만료', COMMITMENT_REQUEST: '본인의 약속 확인 필요',
  RELATIONSHIP_DECISION: '본인의 관계 판단 필요', MONEY_REQUEST: '금전 관련 확인 필요',
  URGENT_OWNER_ATTENTION: '본인의 빠른 확인 필요', UNSUPPORTED_CONTENT: '지원하지 않는 입력',
  UNTRUSTED_INSTRUCTION: '대화 속 제어 지시', NO_REPLY_NEEDED: '답장 불필요', INVALID_CONTEXT: '불완전한 문맥',
  OWNER_REPLIED: '본인이 먼저 답장함', STOPPED: '사용자가 중지함', CONTEXT_CHANGED: '대화 내용이 변경됨',
  PARTNER_STOPPED: '상대가 자동 답장 중지를 요청함', M1_MOCK_ONLY: '모의 연결만 사용할 수 있음',
  STALE_INPUT: '응답 가능한 시간이 지남', REPLY_LIMIT: '응답 횟수 한도',
  AMBIGUOUS_AUTHOR_OR_CONTEXT: '작성자나 문맥을 확인할 수 없음', WRONG_BINDING: '지정된 대화가 아님',
  UNVERIFIED_BINDING: '대상 대화 확인 필요', DELIVERY_UNKNOWN: '모의 발송 결과 확인 필요',
  DELIVERY_UNKNOWN_REQUIRES_REVIEW: '불명확한 발송 결과 검토 필요', RESTART_BASELINE_REQUIRED: '재시작 후 새 모의 세션 시작 필요',
  RECOVERY_UNCERTAIN: '복구된 발송 결과 확인 필요', BASELINE_OR_UNSUPPORTED_SOURCE: '과거 자료 또는 지원하지 않는 출처',
  ATTEMPT_ALREADY_EXISTS: '이미 발송을 시도한 작업', GENERATION_CANCELED: '답장 생성 취소',
  HUMAN_COOLDOWN: '본인 답장 뒤 대기 중', INVALID_FACT: '답장 근거 확인 실패', INVALID_MODE: '실행 모드 확인 필요',
  INVALID_OR_FAILED_GENERATION: '답장 생성 또는 형식 확인 실패', MODE_CHANGED: '실행 모드 변경',
  NOT_RUNNING: '작동 중이 아님', OUTSIDE_ACTIVE_WINDOW: '허용된 작동 시간이 아님',
};
const modes = { off: '중지됨', auto: '모의 자동 모드', draft: '초안 모드' };
const time = (value: string) => new Intl.DateTimeFormat('ko-KR', { timeZone: 'Asia/Seoul', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }).format(new Date(value));
const duration = (seconds: number) => seconds < 60 ? `${seconds}초` : `${Math.floor(seconds / 60)}분${seconds % 60 ? ` ${seconds % 60}초` : ''}`;

function Mark({ small = false }: { small?: boolean }) {
  return <span className={`brand-mark ${small ? 'small' : ''}`} aria-hidden="true"><svg viewBox="0 0 32 32" fill="none"><path d="M25 14.7c0 5-4 8.5-9.3 8.5H9l-4 3v-8.5C3.7 12.5 7.7 7 14.1 7h1.6" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"/><path d="m22 4 1.7 4.3L28 10l-4.3 1.7L22 16l-1.7-4.3L16 10l4.3-1.7L22 4Z" fill="currentColor"/></svg></span>;
}

export function App() {
  const [state, setState] = useState<RuntimeState | null>(null);
  const [busy, setBusy] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [stopVersion, setStopVersion] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState('');
  const [text, setText] = useState('오늘 하루 어땠어?');
  const [origin, setOrigin] = useState<MessageOrigin>('partner');
  const [detail, setDetail] = useState<JobDetail | null>(null);
  const [detailBusy, setDetailBusy] = useState<string | null>(null);
  const [storage, setStorage] = useState<StorageStatus | null>(null);
  const [deleteConfirm, setDeleteConfirm] = useState(false);
  const requestVersion = useRef(0);
  const detailVersion = useRef(0);

  useEffect(() => {
    let active = true;
    const version = ++requestVersion.current;
    Promise.allSettled([api.state(), api.storage()]).then(([runtime, status]) => {
      if (!active || version !== requestVersion.current) return;
      if (runtime.status === 'fulfilled') setState(runtime.value);
      if (status.status === 'fulfilled') setStorage(status.value);
      const failed = [runtime, status].find(result => result.status === 'rejected');
      if (failed?.status === 'rejected') setError(failed.reason instanceof Error ? failed.reason.message : '현재 상태를 확인하지 못했습니다.');
    });
    return () => { active = false; };
  }, []);

  async function act(run: () => Promise<RuntimeState>, success: string, isStop = false): Promise<boolean> {
    const version = ++requestVersion.current;
    ++detailVersion.current;
    if (isStop) setStopVersion(value => value + 1);
    setDetail(null); setDetailBusy(null); setDeleteConfirm(false); setBusy(true); setStopping(isStop); setError(null); setNotice('');
    try {
      const next = await run();
      if (version !== requestVersion.current) return false;
      setState(next); setNotice(success);
      return true;
    } catch (err) {
      if (version === requestVersion.current) setError(err instanceof Error ? err.message : '요청을 완료하지 못했습니다.');
      return false;
    } finally {
      if (version === requestVersion.current) { setBusy(false); setStopping(false); }
    }
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!text.trim() || busy || !state || state.mode === 'off') return;
    if (await act(() => api.message(text.trim(), origin), origin === 'owner' ? '본인 답장을 반영했습니다. 이전 대기 작업이 취소됩니다.' : '합성 메시지를 반영했습니다.')) setText('');
  }

  async function showDetail(id: string) {
    const version = ++detailVersion.current;
    setDetail(null); setDeleteConfirm(false); setDetailBusy(id); setError(null);
    try {
      const result = await api.detail(id);
      if (version === detailVersion.current) setDetail(result);
    } catch (err) {
      if (version === detailVersion.current) setError(err instanceof Error ? err.message : '상세 정보를 읽지 못했습니다.');
    } finally { if (version === detailVersion.current) setDetailBusy(null); }
  }

  async function reconnect(): Promise<RuntimeState> {
    const value = await api.reconnect();
    const status = await api.storage();
    setStorage(status);
    return value;
  }

  async function deleteBody() {
    if (!detail || !deleteConfirm || busy) return;
    const id = detail.job_id;
    const version = ++requestVersion.current;
    ++detailVersion.current;
    setBusy(true); setError(null); setNotice('');
    try {
      const next = await api.deleteBody(id);
      if (version !== requestVersion.current) return;
      setState(next);
      const updated = next.jobs.find(job => job.job_id === id);
      setDetail(updated ? { ...updated, reply_text: null } : null);
      setDeleteConfirm(false);
      setNotice('로컬 생성문을 삭제했습니다. 발송 시도와 처리 이력은 유지됩니다.');
    } catch (err) {
      if (version === requestVersion.current) setError(err instanceof Error ? err.message : '생성문을 삭제하지 못했습니다.');
    } finally {
      if (version === requestVersion.current) setBusy(false);
    }
  }

  const remaining = state?.pending_due_at ? Math.max(0, Math.ceil((Date.parse(state.pending_due_at) - Date.parse(state.now)) / 1000)) : null;
  const jobs = [...(state?.jobs ?? [])].reverse();
  const inactive = !state || state.mode === 'off';

  return <div className="app-shell">
    <aside className="sidebar">
      <a className="brand" href="#main"><Mark /><span>KakaoReply<span className="brand-caption">마음을 잇는 답장 도우미</span></span></a>
      <div className="workspace-label">내 작업 공간</div>
      <a className="nav-item selected" href="#main"><span aria-hidden="true">◈</span> 모의 대화 <span className="nav-dot" /></a>
      <a className="nav-item" href="#history"><span aria-hidden="true">◷</span> 답장 이력</a>
      <a className="nav-item" href="#kakao"><span aria-hidden="true">↗</span> 카카오톡 답장</a>
      <div className="sidebar-bottom"><span className="local-indicator" /> 내 Mac에서 실행<div>모의 대화 · 카카오톡 답장</div></div>
    </aside>
    <main id="main">
      <header className="topbar"><div className="breadcrumb">작업 공간 <span>/</span> <strong>모의 대화</strong></div><span className="connection"><span className={state && !error ? 'dot green' : 'dot'} />{state && !error ? '로컬 서버 연결됨' : error ? '연결 / 요청 확인 필요' : '서버 연결 중'}</span></header>
      <div className="content">
        <div className="page-heading"><div><div className="eyebrow">REPLY PLAYGROUND</div><h1>답장을 미리 경험해 보세요<span>.</span></h1><p>메시지 한 통에서 답장까지, 원하는 속도로 확인하세요.</p></div><button className="stop-button" disabled={!state || stopping} onClick={() => void act(api.pause, '중지했습니다. 아직 발송하지 않은 작업을 취소했습니다.', true)}><span aria-hidden="true">■</span> {stopping ? '중지 요청 중…' : '즉시 중지'}</button></div>
        <div className="simulation-banner"><span className="banner-icon" aria-hidden="true">✓</span><div><strong>시뮬레이터는 모의 연결입니다.</strong> 모의 대화는 실제 카카오톡이나 외부 AI에 접근하지 않습니다. 합성 문장만 입력해 주세요.</div><span className="tag">MOCK</span></div>
        {error && <div className="error-box" role="alert"><span>{error}</span><button disabled={busy} onClick={() => void act(reconnect, '현재 상태를 다시 확인했습니다.')}>연결 다시 확인</button></div>}
        <div className="notice" role="status" aria-live="polite">{busy ? '요청을 처리하고 있습니다…' : notice}</div>
        <section className="metrics" aria-label="현재 실행 상태">
          <div className="metric"><span className="metric-label">작동 상태</span><strong><span className={`dot ${state?.mode === 'auto' ? 'green' : ''}`} />{state ? modes[state.mode] : '연결 확인 중'}</strong><span>모의 대화에서만 작동</span></div>
          <div className="metric"><span className="metric-label">대상 대화</span><strong>합성 파트너 <span className="mini-tag">1:1</span></strong><span>고정된 테스트 대화</span></div>
          <div className="metric"><span className="metric-label">다음 답장까지</span><strong>{remaining === null ? '대기 중인 답장 없음' : remaining === 0 ? '답장 처리 시각' : duration(remaining)}</strong><span>{state ? `수신 후 ${duration(state.reply_delay)} 대기` : '정책 확인 중'}</span></div>
          <div className="metric"><span className="metric-label">모의 발송</span><strong><span className="number">{state?.simulated_send_count ?? 0}</span><span className="unit">회</span></strong><span>실제 발송 횟수가 아닙니다</span></div>
        </section>
        {state?.paused_reason && <div className="pause-note">자동 응답이 멈춰 있습니다. <strong>{reasons[state.paused_reason] ?? state.paused_reason}</strong></div>}
        <div className="work-grid">
          <section className="card compose-card" aria-labelledby="compose-title">
            <div className="card-header"><div><span className="step">01</span><h2 id="compose-title">합성 메시지 입력</h2></div><span className="muted">대화의 시작</span></div>
            <div className="card-body">
              <div className="session-controls"><button className={`button ${state?.mode === 'auto' ? 'active-mode' : 'primary'}`} disabled={busy || !state} onClick={() => void act(() => api.start('auto'), '모의 자동 모드를 시작했습니다.')}>모의 자동 시작</button><button className={`button ${state?.mode === 'draft' ? 'active-mode' : 'secondary'}`} disabled={busy || !state} onClick={() => void act(() => api.start('draft'), '초안 모드를 시작했습니다. 생성된 답장은 발송하지 않습니다.')}>초안만 생성</button></div>
              <form onSubmit={event => void submit(event)}>
                <label className="field-label" htmlFor="origin">누가 보낸 메시지인가요?</label>
                <select id="origin" value={origin} disabled={busy} onChange={event => setOrigin(event.target.value as MessageOrigin)}><option value="partner">상대방 · 답장 대기 시작</option><option value="owner">본인 · 이전 답장 대기 취소</option><option value="unknown">작성자 불명 · 발송 보류 확인</option></select>
                <label className="field-label" htmlFor="message">테스트 문장</label>
                <textarea id="message" rows={4} maxLength={10000} value={text} disabled={busy} onChange={event => setText(event.target.value)} placeholder="예: 오늘 하루 어땠어?" aria-describedby="message-help" />
                <div className="input-foot"><span id="message-help">실제 대화와 개인정보는 입력하지 마세요.</span><span>{Array.from(text).length.toLocaleString()} / 10,000</span></div>
                <button type="submit" className="button dark submit" disabled={busy || inactive || !text.trim()}>합성 메시지 넣기 <span aria-hidden="true">↗</span></button>
                {inactive && <p className="help-text">먼저 모의 자동 모드나 초안 모드를 시작해 주세요.</p>}
              </form>
            </div>
          </section>
          <section className="card clock-card" aria-labelledby="clock-title">
            <div className="card-header"><div><span className="step">02</span><h2 id="clock-title">시간을 앞으로</h2></div><span className="mini-tag">가상 시계</span></div>
            <div className="card-body">
              <div className="clock-face"><span>시뮬레이션 시각 · 서울</span><strong>{state ? time(state.now) : '— : — : —'}</strong><span>{state ? new Intl.DateTimeFormat('ko-KR', { timeZone: 'Asia/Seoul', dateStyle: 'long' }).format(new Date(state.now)) : '서버를 기다리고 있습니다'}</span></div>
              <p className="clock-description">실제 시간을 기다릴 필요 없어요.<br />시간을 이동하면 답장 조건을 확인합니다.</p>
              <div className="time-buttons"><button className="button secondary" disabled={busy || !state} onClick={() => void act(() => api.advance(20), '가상 시간을 20초 이동했습니다.')}>+20초</button><button className="button secondary" disabled={busy || !state} onClick={() => void act(() => api.advance(60), '가상 시간을 1분 이동했습니다.')}>+1분</button><button className="button secondary" disabled={busy || !state} onClick={() => void act(() => api.advance(600), '가상 시간을 10분 이동했습니다.')}>+10분</button></div>
              <button className="button clock-next" disabled={busy || remaining === null} onClick={() => void act(() => api.advance(remaining ?? 0), '다음 답장 시각까지 이동해 처리 결과를 확인했습니다.')}>다음 답장 시각까지 이동 <span aria-hidden="true">→</span></button>
              <div className="policy-note"><span aria-hidden="true">◷</span><span>추가 메시지는 {state?.settle ?? 20}초 동안 묶고,<br />본인이 답하면 {duration(state?.human_cooldown ?? 900)} 동안 기다립니다.</span></div>
            </div>
          </section>
        </div>
        <section id="history" className="card history-card" aria-labelledby="history-title">
          <div className="card-header"><div><span className="step">03</span><h2 id="history-title">답장 이력</h2><span className="count">{jobs.length}</span></div><button className="text-button" disabled={busy} onClick={() => void act(reconnect, '현재 상태를 새로 확인했습니다.')}>새로 확인 <span aria-hidden="true">↻</span></button></div>
          <p className="help-text" style={{ margin: '14px 24px' }}>{storage ? storage.body_storage === 'aead' ? `생성문 암호화 저장 · ${storage.raw_retention_days}일 보관` : '생성문은 이번 실행 동안 보관' : '생성문 보관 방식 확인 중'}</p>
          {jobs.length === 0 ? <div className="empty-state"><Mark small /><h3>첫 번째 답장을 기다리고 있어요</h3><p>모의 모드를 시작하고 합성 메시지를 넣어 보세요.<br />생성·취소·발송 결과가 여기에 쌓입니다.</p></div> : <div className="history-list">{jobs.map(job => <div className="history-row" key={job.job_id}><span className={`history-symbol ${job.state === 'CONFIRMED_LOCAL' ? 'confirmed' : ''}`} aria-hidden="true">{job.state === 'CONFIRMED_LOCAL' ? '✓' : job.state.startsWith('CANCELED') ? '×' : '◷'}</span><div className="history-info"><strong>{states[job.state] ?? job.state}</strong><span>합성 입력 {job.incoming_count}건 · 모의 전송 시도 {job.attempt_count}회{job.reason_codes.length ? ` · ${job.reason_codes.map(code => reasons[code] ?? code).join(', ')}` : ''}</span></div><time dateTime={job.updated_at}>{time(job.updated_at)}</time><button className="button detail-button" disabled={busy || detailBusy === job.job_id} onClick={() => void showDetail(job.job_id)} aria-label={`${states[job.state] ?? job.state} 상세 보기`}>{detailBusy === job.job_id ? '조회 중…' : '상세 보기'}</button></div>)}</div>}
          {detail && <section className="reply-detail" aria-label="답장 상세"><div className="detail-heading"><strong>{states[detail.state] ?? detail.state}</strong><button className="text-button" disabled={busy} onClick={() => { ++detailVersion.current; setDetail(null); setDeleteConfirm(false); }}>닫기</button></div>{detail.reply_text ? <blockquote>{detail.reply_text}</blockquote> : <p>표시할 생성문이 없습니다.</p>}<p className="help-text">모의 결과입니다. 로컬 발신 확인은 상대의 수신이나 읽음 확인을 뜻하지 않습니다.</p>{detail.reply_text && <div style={{ marginTop: 16 }}>{deleteConfirm ? <div className="pause-note" role="group" aria-label="로컬 생성문 삭제 확인"><p>이 작업의 로컬 생성문을 삭제할까요?</p><p>이미 발송한 메시지를 회수하지 않습니다. 발송 시도와 처리 이력은 남고, 아직 발송하지 않은 작업은 취소됩니다.</p><div className="session-controls"><button className="button secondary" disabled={busy} onClick={() => setDeleteConfirm(false)}>취소</button><button className="button dark" disabled={busy} onClick={() => void deleteBody()}>확인하고 삭제</button></div></div> : <button className="button secondary" disabled={busy} onClick={() => setDeleteConfirm(true)}>로컬 생성문 삭제</button>}</div>}<details><summary>진단 정보</summary><dl><dt>작업 ID</dt><dd>{detail.job_id}</dd><dt>상태</dt><dd>{detail.state}</dd><dt>이유 코드</dt><dd>{detail.reason_codes.join(', ') || '없음'}</dd></dl></details></section>}
        </section>
        <KakaoDiagnostics stopVersion={stopVersion} stopping={stopping} />
        <footer><span>KakaoReply · 합성 대화 시뮬레이터</span><span>자동 답장에는 <strong>— 부재중 AI 답장</strong> 표시가 붙습니다.</span></footer>
      </div>
    </main>
  </div>;
}
