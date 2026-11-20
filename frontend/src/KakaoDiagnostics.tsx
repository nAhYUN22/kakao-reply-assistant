import { useEffect, useRef, useState } from 'react';
import { api } from './api';
import type { KakaoChoice, KakaoReadResult } from './types';

const readResults: Record<string, string> = {
  UNCHANGED: '새로 관측된 메시지가 없습니다.',
  APPENDED: '새 메시지 관측을 확인했습니다.',
};

/** Availability is passive; room discovery and reads require separate user actions. */
export function KakaoDiagnostics() {
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

  return <section className="card history-card" aria-labelledby="kakao-diagnostics-title">
    <div className="card-header">
      <div><span className="step">READ</span><h2 id="kakao-diagnostics-title">Mac 카카오톡 읽기 진단</h2><span className="mini-tag">전송 없음</span></div>
      <button className="text-button" aria-expanded={opened} onClick={() => setOpened(value => !value)}>{opened ? '진단 닫기' : '진단 열기'}</button>
    </div>
    <div className="card-body">
      <p className="help-text" style={{ marginTop: 0 }}>모의 답장과 별도의 읽기 전용 점검입니다. 이 진단은 실제 자동 답장을 활성화하지 않습니다.</p>
      <p className="help-text" aria-live="polite">{checking ? 'kmsg 설치 여부 확인 중…' : statusError ? '설치 여부를 확인하지 못했습니다.' : installed ? 'kmsg 실행 파일을 찾았습니다. 대상을 선택하면 읽기를 확인할 수 있습니다.' : 'kmsg 실행 파일을 찾지 못했습니다.'}</p>
      {opened && <>
        <button className="button secondary" style={{ marginTop: 12 }} disabled={checking} onClick={() => void checkAvailability()}>설치 여부 다시 확인</button>
        <div className="policy-note"><div>
          <strong>준비 순서</strong>
          <ol style={{ paddingLeft: 20, lineHeight: 1.9 }}>
            <li>macOS 13 이상에서 Mac용 카카오톡을 실행하고 로그인해 주세요.</li>
            {installed !== true && <li>Homebrew가 설치된 터미널에서 <code>brew install channprj/tap/kmsg</code>를 실행해 주세요.</li>}
            <li><code>kmsg status</code>를 직접 실행한 뒤, <strong>시스템 설정 → 개인정보 보호 및 보안 → 손쉬운 사용</strong>에서 실제 실행하는 <strong>kmsg 바이너리</strong>를 추가하거나 켜 주세요. 다시 <code>kmsg status</code>로 확인해 주세요. 이 명령은 카카오톡을 실행하거나 인증 화면을 열 수 있습니다.</li>
            <li>읽을 <strong>1:1 대화를 별도 창으로 열고 화면에 표시</strong>해 주세요. 이 진단은 닫힌 대화를 찾아 열지 않습니다.</li>
          </ol>
          <p><a href="https://github.com/channprj/kmsg/blob/main/README.en.md" target="_blank" rel="noreferrer">kmsg 설치 안내 ↗</a> · <a href="https://github.com/channprj/kmsg/blob/main/USAGE.md#troubleshooting" target="_blank" rel="noreferrer">권한·읽기 문제 해결 ↗</a></p>
        </div></div>
        <ReadDiagnostics enabled={installed === true && !checking && !statusError} />
      </>}
    </div>
  </section>;
}

/** Unmounting clears room names, selection, confirmation, and results from UI memory. */
function ReadDiagnostics({ enabled }: { enabled: boolean }) {
  const [choices, setChoices] = useState<KakaoChoice[] | null>(null);
  const [selected, setSelected] = useState('');
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState<'catalog' | 'verify' | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<KakaoReadResult | null>(null);
  const alive = useRef(true);

  useEffect(() => {
    alive.current = true;
    return () => { alive.current = false; };
  }, []);

  async function catalog() {
    setBusy('catalog'); setError(null); setResult(null); setChoices(null); setSelected(''); setConfirmed(false);
    try {
      const response = await api.kakaoCatalog();
      if (alive.current) setChoices(response.choices);
    } catch (err) {
      if (alive.current) setError(err instanceof Error ? err.message : '대화 목록을 읽지 못했습니다. kmsg 설치·손쉬운 사용 권한·카카오톡 로그인 상태를 확인해 주세요.');
    } finally { if (alive.current) setBusy(null); }
  }

  async function verify() {
    if (!enabled || busy || !selected || !confirmed) return;
    setBusy('verify'); setError(null); setResult(null);
    try {
      const response = await api.kakaoVerify(selected);
      if (alive.current) setResult(response);
    } catch (err) {
      if (alive.current) setError(err instanceof Error ? err.message : '대상 대화의 읽기를 확인하지 못했습니다. 1:1 대상과 별도 창 표시·권한을 확인하고 다시 시도해 주세요.');
    } finally { if (alive.current) setBusy(null); }
  }

  const resultText = result && Object.hasOwn(readResults, result.status) ? readResults[result.status] : undefined;
  return <div style={{ marginTop: 20 }}>
    <p className="help-text">아래 버튼을 누르면 실제 카카오톡의 대화 목록을 조회합니다. 대화 이름은 이 진단 화면에서만 표시하며, 닫으면 선택과 결과를 지웁니다.</p>
    <button className="button secondary" style={{ marginTop: 12 }} disabled={!enabled || busy !== null} onClick={() => void catalog()}>{busy === 'catalog' ? '대화 목록 읽는 중…' : choices === null ? '실제 대화 목록 조회' : '대화 목록 다시 조회'}</button>
    {choices !== null && choices.length === 0 && <p className="help-text">표시할 대화가 없습니다. 카카오톡 로그인과 열린 대화를 확인해 주세요.</p>}
    {choices !== null && choices.length > 0 && <div style={{ marginTop: 18 }}>
      <label className="field-label" htmlFor="kakao-read-target">읽기 진단할 대화</label>
      <select id="kakao-read-target" value={selected} disabled={busy !== null || !enabled} onChange={event => { setSelected(event.target.value); setConfirmed(false); setResult(null); setError(null); }}>
        <option value="">대화를 직접 선택해 주세요</option>
        {choices.map((choice, index) => <option key={choice.id} value={choice.id}>{choice.title} · 항목 {index + 1}</option>)}
      </select>
      <label className="help-text" style={{ display: 'flex', alignItems: 'flex-start', gap: 8 }}><input type="checkbox" checked={confirmed} disabled={!selected || busy !== null || !enabled} onChange={event => setConfirmed(event.target.checked)} />선택한 대화가 원하는 상대와의 1:1 대화이며, 별도 창으로 열려 있는 것을 확인했습니다.</label>
      <button className="button dark" style={{ marginTop: 14 }} disabled={!enabled || busy !== null || !selected || !confirmed} onClick={() => void verify()}>{busy === 'verify' ? '읽기 확인 중…' : '선택한 대화 읽기 확인'}</button>
    </div>}
    {error && <p className="error-box" role="alert">{error}</p>}
    {result && <div className="pause-note" style={{ marginTop: 18 }} aria-live="polite">
      <strong>{resultText ?? '읽기 결과를 확정하지 못했습니다.'}</strong>
      {resultText ? <p>기준선 {result.baseline_count}건 · 새로 관측 {result.new_count}건</p> : <p>대상·작성자·관측 상태를 다시 확인해 주세요. 정상 읽기 완료로 처리하지 않았습니다.</p>}
      <p>본문은 이 화면에 표시하지 않습니다. 이 결과는 자동 응답 연결이나 실제 발송 성공을 의미하지 않습니다.</p>
    </div>}
  </div>;
}
