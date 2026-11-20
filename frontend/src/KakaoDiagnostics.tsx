import { useEffect, useRef, useState } from 'react';
import { KakaoReplyHistory } from './KakaoReplyHistory';
import { api } from './api';
import type { KakaoChoice, KakaoReadResult, KakaoDirectReadResult, KakaoReplyDraft } from './types';

const readResults: Record<string, string> = {
  UNCHANGED: 'kmsg가 관측 변경 없음으로 반환했습니다.',
  APPENDED: 'kmsg가 추가 관측을 반환했습니다.',
};

/** Availability is passive; room discovery and reads require separate user actions. */
export function KakaoDiagnostics({ stopVersion = 0, stopping = false }: { stopVersion?: number; stopping?: boolean }) {
  const [installed, setInstalled] = useState<boolean | null>(null);
  const [checking, setChecking] = useState(false);
  const [statusError, setStatusError] = useState(false);
  const [opened, setOpened] = useState(false);
  const alive = useRef(true);

  async function checkAvailability() {
    setChecking(true); setStatusError(false);
    try {
      const result = await api.kakaoStatus();
      if (alive.current) setInstalled(result.installed);
    } catch {
      if (alive.current) { setInstalled(null); setStatusError(true); }
    } finally { if (alive.current) setChecking(false); }
  }

  useEffect(() => {
    alive.current = true;
    void checkAvailability();
    return () => { alive.current = false; };
  }, []);

  return <section id="kakao" className="card history-card" aria-labelledby="kakao-diagnostics-title">
    <div className="card-header">
      <div><h2 id="kakao-diagnostics-title">Mac 카카오톡 읽기와 답장</h2></div>
      <button className="text-button" aria-expanded={opened} onClick={() => setOpened(value => !value)}>{opened ? '진단 닫기' : '진단 열기'}</button>
    </div>
    <div className="card-body">
      <p className="help-text" style={{ marginTop: 0 }}>실제 1:1 대화를 읽고 마지막 상대 메시지에 대한 초안을 만듭니다. 내용을 확인하고 발송 버튼을 누르면 카카오톡으로 1회 보냅니다.</p>
      <p className="help-text" aria-live="polite">{checking ? 'kmsg 설치 여부 확인 중…' : statusError ? '설치 여부를 확인하지 못했습니다.' : installed ? 'kmsg 실행 파일을 찾았습니다. 대화 이름을 입력해 바로 읽을 수 있습니다.' : 'kmsg 실행 파일을 찾지 못했습니다.'}</p>
      {opened && <>
        <button className="button secondary" style={{ marginTop: 12 }} disabled={checking} onClick={() => void checkAvailability()}>설치 여부 다시 확인</button>
        <div className="policy-note"><div>
          <strong>준비 순서</strong>
          <ol style={{ paddingLeft: 20, lineHeight: 1.9 }}>
            <li>macOS 13 이상에서 Mac용 카카오톡을 실행하고 로그인해 주세요.</li>
            {installed !== true && <li>Homebrew가 설치된 터미널에서 <code>brew install channprj/tap/kmsg</code>를 실행해 주세요.</li>}
            <li><code>kmsg status</code>를 직접 실행한 뒤, <strong>시스템 설정 → 개인정보 보호 및 보안 → 손쉬운 사용</strong>에서 실제 실행하는 <strong>kmsg 바이너리</strong>를 추가하거나 켜 주세요. 다시 <code>kmsg status</code>로 확인해 주세요. 이 명령은 카카오톡을 실행하거나 인증 화면을 열 수 있습니다.</li>
            <li>이름으로 바로 읽으면 kmsg가 대화창을 찾아 엽니다. 목록에서 선택해 읽을 때 창 열기를 허용하지 않으면 먼저 <strong>1:1 대화를 별도 창으로 열고 화면에 표시</strong>해 주세요.</li>
          </ol>
          <p><a href="https://github.com/channprj/kmsg/blob/main/README.en.md" target="_blank" rel="noreferrer">kmsg 설치 안내 ↗</a> · <a href="https://github.com/channprj/kmsg/blob/main/USAGE.md#troubleshooting" target="_blank" rel="noreferrer">권한·읽기 문제 해결 ↗</a></p>
        </div></div>
        <ReadDiagnostics key={stopVersion} enabled={installed === true && !checking && !statusError && !stopping} />
      </>}
    </div>
  </section>;
}

/** Unmounting clears names, selection, confirmation, and results from UI memory. */
function ReadDiagnostics({ enabled }: { enabled: boolean }) {
  const [name, setName] = useState('');
  const [directConfirmed, setDirectConfirmed] = useState(false);
  const [directError, setDirectError] = useState<string | null>(null);
  const [directResult, setDirectResult] = useState<KakaoDirectReadResult | null>(null);
  const [choices, setChoices] = useState<KakaoChoice[] | null>(null);
  const [selected, setSelected] = useState('');
  const [allowOpenWindow, setAllowOpenWindow] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState<'direct' | 'catalog' | 'verify' | 'prepare' | 'send' | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<KakaoReadResult | null>(null);
  const [draft, setDraft] = useState<KakaoReplyDraft | null>(null);
  const [sendConfirmed, setSendConfirmed] = useState(false);
  const [historyVersion, setHistoryVersion] = useState(0);
  const [replyNotice, setReplyNotice] = useState('');
  const [replyError, setReplyError] = useState('');
  const expiresAt = useRef(0);
  const sending = useRef(false);
  const alive = useRef(true);

  useEffect(() => {
    alive.current = true;
    return () => { alive.current = false; };
  }, []);

  function discardDraft() {
    setDraft(null); setSendConfirmed(false); setReplyNotice(''); setReplyError('');
    expiresAt.current = 0;
  }

  useEffect(() => {
    if (!draft) return;
    const timeout = window.setTimeout(() => {
      setDraft(null); setSendConfirmed(false);
      setReplyNotice('초안이 만료되었습니다. 최근 대화로 다시 만들어 주세요.');
    }, Math.max(0, expiresAt.current - Date.now()));
    return () => window.clearTimeout(timeout);
  }, [draft]);

  async function prepareReply() {
    if (!enabled || busy || !directConfirmed || !name.trim()) return;
    discardDraft(); setBusy('prepare'); setDirectResult(null); setDirectError(null);
    try {
      const next = await api.kakaoPrepareReply(name.trim());
      if (!alive.current) return;
      if (!next || typeof next.in_reply_to !== 'string' || !next.in_reply_to.trim() || typeof next.text !== 'string' || !next.text.trim() || typeof next.draft_id !== 'string' || !next.draft_id.trim() ||
          !Number.isSafeInteger(next.context_count) || next.context_count < 1 || next.context_count > 8 ||
          !Number.isSafeInteger(next.expires_in_seconds) || next.expires_in_seconds < 1) {
        throw new Error('초안 응답을 확인할 수 없습니다. 최근 대화로 다시 만들어 주세요.');
      }
      expiresAt.current = Date.now() + next.expires_in_seconds * 1000;
      setDraft(next);
    } catch (err) {
      if (alive.current) setReplyError(err instanceof Error ? err.message : '답장 초안을 만들지 못했습니다.');
    } finally { if (alive.current) setBusy(null); }
  }

  async function sendReply() {
    if (!enabled || busy || sending.current || !directConfirmed || !draft || !sendConfirmed) return;
    if (Date.now() >= expiresAt.current) {
      discardDraft(); setReplyNotice('초안이 만료되었습니다. 최근 대화로 다시 만들어 주세요.');
      return;
    }
    sending.current = true;
    const draftId = draft.draft_id;
    discardDraft(); setBusy('send');
    try {
      const result = await api.kakaoSendReply(draftId);
      if (!alive.current) return;
      if (result?.status !== 'CONFIRMED_LOCAL') throw new Error('발송 결과를 확인할 수 없습니다. 카카오톡 대화창에서 직접 확인해 주세요.');
      setReplyNotice('카카오톡 대화창에서 이 답장의 발신을 확인했습니다.');
    } catch (err) {
      if (alive.current) setReplyError(err instanceof Error ? err.message : '발송 결과를 확인할 수 없습니다. 카카오톡 대화창에서 직접 확인해 주세요.');
    } finally {
      sending.current = false;
      if (alive.current) { setBusy(null); setHistoryVersion(value => value + 1); }
    }
  }

  async function readByName() {
    if (!enabled || busy || !name.trim() || !directConfirmed) return;
    discardDraft(); setBusy('direct'); setDirectError(null); setDirectResult(null);
    setError(null); setResult(null); setChoices(null); setSelected(''); setConfirmed(false);
    try {
      const response = await api.kakaoReadByName(name.trim());
      if (alive.current) {
        if (response.status === 'READ' && Number.isSafeInteger(response.count) && response.count >= 0 && response.count <= 3) setDirectResult(response);
        else setDirectError('이름으로 읽기 응답을 확인하지 못했습니다. 결과를 표시하지 않았습니다.');
      }
    } catch (err) {
      if (alive.current) setDirectError(err instanceof Error ? err.message : '이름으로 읽기 결과를 확인하지 못했습니다.');
    } finally { if (alive.current) setBusy(null); }
  }

  async function catalog() {
    if (!enabled || busy) return;
    discardDraft(); setBusy('catalog'); setError(null); setResult(null); setChoices(null); setSelected(''); setConfirmed(false); setAllowOpenWindow(false);
    setDirectResult(null); setDirectError(null); setDirectConfirmed(false);
    try {
      const response = await api.kakaoCatalog();
      if (alive.current) setChoices(response.choices);
    } catch (err) {
      if (alive.current) setError(err instanceof Error ? err.message : '대화 목록 조회를 완료하지 못했습니다.');
    } finally { if (alive.current) setBusy(null); }
  }

  async function verify() {
    const choice = choices?.find(item => item.id === selected);
    if (!enabled || busy || !choice || !confirmed || choices?.filter(item => item.title === choice.title).length !== 1) return;
    discardDraft(); setBusy('verify'); setError(null); setResult(null);
    try {
      const response = await api.kakaoVerify(selected, allowOpenWindow);
      if (alive.current) setResult(response);
    } catch (err) {
      if (alive.current) setError(err instanceof Error ? err.message : '대상 대화의 읽기를 확인하지 못했습니다.');
    } finally { if (alive.current) setBusy(null); }
  }

  const resultText = result && Object.hasOwn(readResults, result.status) ? readResults[result.status] : undefined;
  return <div style={{ marginTop: 20 }}>
    <form aria-label="대화 이름으로 바로 읽기" onSubmit={event => { event.preventDefault(); void readByName(); }}>
      <label className="field-label" htmlFor="kakao-direct-name">읽을 대화 이름</label>
      <input id="kakao-direct-name" aria-describedby="kakao-direct-guidance" type="text" value={name} maxLength={200} autoComplete="off" disabled={!enabled || busy !== null} placeholder="카카오톡에 표시된 정확한 대화 이름" style={{ width: '100%', padding: '11px 12px', border: '1px solid #dfe3d4', borderRadius: 6, color: '#505b48', background: '#fffefa' }} onChange={event => { discardDraft(); setName(event.target.value); setDirectConfirmed(false); setDirectResult(null); setDirectError(null); }} />
      <div id="kakao-direct-guidance">
        <p className="help-text">대화 목록 조회 없이 입력한 이름으로 kmsg를 전경에서 한 번 실행해 최대 3건을 읽고, 건수만 표시합니다. 미리 창을 열어둘 필요는 없습니다.</p>
        <p className="help-text">kmsg가 이름 일부로 다른 대화를 열 수 있습니다. 반환된 제목이 입력한 이름과 다르면 읽기 결과를 버립니다.</p>
        <p className="help-text">대화창을 열고 닫을 수 있으며, 카카오톡이 앞으로 오거나 읽음 상태가 바뀔 수 있습니다.</p>
      </div>
      <label className="help-text" style={{ display: 'flex', alignItems: 'flex-start', gap: 8 }}><input type="checkbox" checked={directConfirmed} disabled={!enabled || busy !== null || !name.trim()} onChange={event => { discardDraft(); setDirectConfirmed(event.target.checked); }} />입력한 이름이 원하는 1:1 대화의 제목과 상대의 메시지 작성자 이름에 일치합니다. 창 열기와 읽음 상태 변경 가능성을 확인했습니다.</label>
      <button type="submit" className="button dark" style={{ marginTop: 14 }} disabled={!enabled || busy !== null || !name.trim() || !directConfirmed}>{busy === 'direct' ? '이름으로 읽는 중…' : '이름으로 바로 읽기'}</button>
      <div aria-live="polite">
        {busy === 'direct' && <p className="help-text">kmsg에 이름 지정 읽기를 요청했습니다. 결과를 기다리고 있습니다.</p>}
        {directError && <p className="error-box" role="alert">{directError}</p>}
        {directResult && <div className="pause-note" style={{ marginTop: 16 }}><strong>kmsg 이름 지정 읽기 결과</strong><p>kmsg가 반환한 관측 건수: {directResult.count}건</p><p>본문은 표시하지 않습니다. 이 건수로 새 메시지 여부나 대화 귀속·상대 신원을 확인할 수는 없습니다.</p></div>}
      </div>
      <section className="context-reply" aria-labelledby="context-reply-title">
        <h3 id="context-reply-title">마지막 메시지에 답장</h3>
        <p className="help-text">최근 메시지 최대 8건을 읽어 마지막 상대 메시지에 보낼 답장을 만듭니다. 기본 생성기는 간단한 일상 대화를 지원합니다. 자유로운 대화를 처리하려면 서버의 <code>KAKAOREPLY_OLLAMA_MODEL</code>에 설치한 로컬 Ollama 모델을 지정해 주세요.</p>
        <button type="button" className="button secondary" disabled={!enabled || busy !== null || !name.trim() || !directConfirmed} onClick={() => void prepareReply()}>{busy === 'prepare' ? '답장 만드는 중…' : '답장 초안 만들기'}</button>
        {draft && <div className="reply-detail">
          <p>최근 대화 {draft.context_count}건을 읽었습니다.</p>
          <strong>마지막 상대 메시지</strong>
          <blockquote>{draft.in_reply_to}</blockquote>
          <strong>{name.trim()}에게 보낼 답장</strong>
          <blockquote>{draft.text}</blockquote>
          <label className="context-reply-confirm"><input type="checkbox" checked={sendConfirmed} disabled={!enabled || busy !== null} onChange={event => setSendConfirmed(event.target.checked)} />
            <span>카카오톡에서 ‘{name.trim()}’의 1:1 대화창을 열어 화면에 표시했고, 위 답장을 이 대화에 보낼 것을 확인했습니다.</span></label>
          <div className="context-actions">
            <button type="button" className="button dark" disabled={!enabled || busy !== null || !sendConfirmed} onClick={() => void sendReply()}>카카오톡으로 1회 발송</button>
            <button type="button" className="button secondary" onClick={discardDraft}>초안 폐기</button>
          </div>
        </div>}
        <div role="status" aria-live="polite">{busy === 'send' ? '카카오톡 발신 확인 중…' : replyNotice}</div>
        {replyError && <p className="error-box" role="alert">{replyError}</p>}
      </section>
    </form>
    <KakaoReplyHistory version={historyVersion} sending={busy === 'send'} />
    <section aria-label="목록에서 선택해 읽기" style={{ marginTop: 26, paddingTop: 18, borderTop: '1px solid #e3e6d8' }}>
      <h3 style={{ fontSize: 12, fontWeight: 600 }}>대안: 목록에서 선택해 읽기</h3>
      <p className="help-text">아래 버튼을 눌렀을 때만 실제 대화 목록을 조회합니다. 진단을 닫으면 입력한 이름·목록·선택·결과를 지웁니다.</p>
      <button className="button secondary" style={{ marginTop: 12 }} disabled={!enabled || busy !== null} onClick={() => void catalog()}>{busy === 'catalog' ? '대화 목록 읽는 중…' : choices === null ? '실제 대화 목록 조회' : '대화 목록 다시 조회'}</button>
      {choices !== null && choices.length === 0 && <p className="help-text">표시할 대화가 없습니다.</p>}
      {choices !== null && choices.length > 0 && <div style={{ marginTop: 18 }}>
        <label className="field-label" htmlFor="kakao-read-target">읽기 진단할 대화</label>
        <select id="kakao-read-target" value={selected} disabled={busy !== null || !enabled} onChange={event => { setSelected(event.target.value); setConfirmed(false); setAllowOpenWindow(false); setResult(null); setError(null); }}>
          <option value="">대화를 직접 선택해 주세요</option>
          {choices.map((choice, index) => <option key={choice.id} value={choice.id} disabled={choices.filter(item => item.title === choice.title).length !== 1}>{choice.title} · 항목 {index + 1}{choices.filter(item => item.title === choice.title).length !== 1 ? ' · 이름 중복' : ''}</option>)}
        </select>
        <label className="help-text" style={{ display: 'flex', alignItems: 'flex-start', gap: 8 }}><input type="checkbox" checked={allowOpenWindow} disabled={!selected || busy !== null || !enabled} onChange={event => { setAllowOpenWindow(event.target.checked); setConfirmed(false); setResult(null); }} />읽기 확인 시 선택한 대화창 열기 허용</label>
        <p className="help-text">{allowOpenWindow ? '미리 창을 열어둘 필요는 없습니다. kmsg가 대화를 찾아 창을 열고 닫을 수 있으며, 카카오톡이 앞으로 오거나 읽음 상태가 바뀔 수 있습니다.' : '읽기 전에 선택한 1:1 대화를 별도 창으로 열고 화면에 표시해 주세요.'}</p>
        <label className="help-text" style={{ display: 'flex', alignItems: 'flex-start', gap: 8 }}><input type="checkbox" checked={confirmed} disabled={!selected || busy !== null || !enabled} onChange={event => setConfirmed(event.target.checked)} />선택한 대화가 원하는 상대와의 1:1 대화임을 확인했습니다.</label>
        <button className="button dark" style={{ marginTop: 14 }} disabled={!enabled || busy !== null || !selected || !confirmed} onClick={() => void verify()}>{busy === 'verify' ? '읽기 확인 중…' : allowOpenWindow ? '대화창을 열고 읽기 확인' : '선택한 대화 읽기 확인'}</button>
      </div>}
      {error && <p className="error-box" role="alert">{error}</p>}
      {result && <div className="pause-note" style={{ marginTop: 18 }} aria-live="polite">
        <strong>{resultText ?? '읽기 결과를 확정하지 못했습니다.'}</strong>
        {resultText ? <p>kmsg가 반환한 관측 건수: 기준선 {result.baseline_count}건 · 추가 {result.new_count}건</p> : <p>대상·작성자·관측 상태를 다시 확인해 주세요. 정상 읽기 완료로 처리하지 않았습니다.</p>}
        <p>반환된 창 제목만으로 본문이 선택한 상대의 대화에 속하는지 또는 상대 신원을 확인할 수는 없습니다.</p><p>본문은 이 화면에 표시하지 않습니다. 이 결과는 자동 응답 연결이나 실제 발송 성공을 의미하지 않습니다.</p>
      </div>}
    </section>
  </div>;
}
