import { useEffect, useRef, useState } from 'react';
import { api } from './api';
import type { KakaoChoice, KakaoReadResult } from './types';

const readResults: Record<string, string> = {
  UNCHANGED: 'kmsg가 관측 변경 없음으로 반환했습니다.',
  APPENDED: 'kmsg가 추가 관측을 반환했습니다.',
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
            <li>이름으로 찾은 대상은 <strong>대화창 열기 허용</strong>을 선택해 읽을 수 있습니다. 허용하지 않으면 먼저 <strong>1:1 대화를 별도 창으로 열고 화면에 표시</strong>해 주세요.</li>
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
  const [name, setName] = useState('');
  const [lookupNotice, setLookupNotice] = useState<string | null>(null);
  const [lookupError, setLookupError] = useState<string | null>(null);
  const [allowOpenWindow, setAllowOpenWindow] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState<'catalog' | 'verify' | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<KakaoReadResult | null>(null);
  const alive = useRef(true);

  useEffect(() => {
    alive.current = true;
    return () => { alive.current = false; };
  }, []);

  async function catalog(lookupName?: string) {
    if (!enabled || busy) return;
    setError(null); setLookupError(null); setResult(null); setSelected(''); setConfirmed(false); setLookupNotice(null); setAllowOpenWindow(false);
    if (lookupName !== undefined && !lookupName.trim()) {
      setLookupError('찾을 대화 이름을 입력해 주세요.');
      return;
    }
    setBusy('catalog'); setChoices(null);
    try {
      const response = await api.kakaoCatalog();
      if (alive.current) {
        setChoices(response.choices);
        if (lookupName !== undefined) {
          const matches = response.choices.filter(choice => choice.title === lookupName.trim());
          if (matches.length === 1) {
            setSelected(matches[0].id); setAllowOpenWindow(true);
            setLookupNotice(matches[0].title);
          } else {
            setLookupError(matches.length === 0 ? '이름이 정확히 일치하는 대화가 없습니다. 카카오톡 대화 목록에 표시된 이름을 확인해 주세요.' : '같은 이름의 대화가 여러 개입니다. 대상을 확정하지 않았습니다. 카카오톡에서 이름을 구분한 뒤 다시 조회해 주세요.');
          }
        }
      }
    } catch (err) {
      if (alive.current) setLookupError(`대화 목록 조회를 완료하지 못해 이름을 검색하지 못했습니다. ${err instanceof Error ? err.message : '원인을 확인할 수 없습니다. 다시 조회해 주세요.'}`);
    } finally { if (alive.current) setBusy(null); }
  }

  async function verify() {
    const choice = choices?.find(item => item.id === selected);
    if (!enabled || busy || !choice || !confirmed || choices?.filter(item => item.title === choice.title).length !== 1) return;
    setBusy('verify'); setError(null); setResult(null);
    try {
      const response = await api.kakaoVerify(selected, allowOpenWindow);
      if (alive.current) setResult(response);
    } catch (err) {
      if (alive.current) setError(err instanceof Error ? err.message : '대상 대화의 읽기를 확인하지 못했습니다. 1:1 대상과 별도 창 표시·권한을 확인하고 다시 시도해 주세요.');
    } finally { if (alive.current) setBusy(null); }
  }

  const resultText = result && Object.hasOwn(readResults, result.status) ? readResults[result.status] : undefined;
  return <div style={{ marginTop: 20 }}>
    <p className="help-text">아래 버튼을 누르면 실제 카카오톡의 대화 목록을 조회합니다. 대화 이름은 이 진단 화면에서만 표시하며, 닫으면 선택과 결과를 지웁니다.</p>
    <form aria-label="대화 이름 검색" style={{ marginTop: 16 }} onSubmit={event => { event.preventDefault(); void catalog(name); }}>
      <label className="field-label" htmlFor="kakao-name-search">대화 이름으로 찾기</label>
      <input id="kakao-name-search" aria-describedby="kakao-search-feedback" type="text" value={name} maxLength={200} autoComplete="off" disabled={!enabled || busy !== null} placeholder="카카오톡 대화 목록에 표시된 이름" style={{ width: '100%', padding: '11px 12px', border: '1px solid #dfe3d4', borderRadius: 6, color: '#505b48', background: '#fffefa' }} onChange={event => { setName(event.target.value); setSelected(''); setConfirmed(false); setAllowOpenWindow(false); setResult(null); setError(null); setLookupError(null); setLookupNotice(null); }} />
      <p className="help-text">조회한 대화 목록에서 정확히 일치하는 이름 하나만 선택합니다. 연락처 전체 검색은 하지 않습니다.</p>
      <button type="submit" className="button dark" style={{ marginTop: 12 }} disabled={!enabled || busy !== null}>이름으로 대화 찾기</button>
      <div id="kakao-search-feedback" aria-live="polite">
        {busy === 'catalog' && <p className="help-text">대화 목록을 조회하고 있습니다. 아직 이름 일치 여부를 확인하지 않았습니다.</p>}
        {lookupError && <p className="error-box" role="alert">{lookupError}</p>}
        {lookupNotice && <p className="help-text">선택된 대화: <strong>{lookupNotice}</strong><br />이름이 정확히 일치하는 대화 1개를 찾았습니다. 대상과 1:1 대화 여부를 확인해 주세요.</p>}
      </div>
    </form>
    <button className="button secondary" style={{ marginTop: 12 }} disabled={!enabled || busy !== null} onClick={() => void catalog()}>{busy === 'catalog' ? '대화 목록 읽는 중…' : choices === null ? '실제 대화 목록 조회' : '대화 목록 다시 조회'}</button>
    {choices !== null && choices.length === 0 && <p className="help-text">표시할 대화가 없습니다. 카카오톡 로그인과 열린 대화를 확인해 주세요.</p>}
    {choices !== null && choices.length > 0 && <div style={{ marginTop: 18 }}>
      <label className="field-label" htmlFor="kakao-read-target">읽기 진단할 대화</label>
      <select id="kakao-read-target" value={selected} disabled={busy !== null || !enabled} onChange={event => { setSelected(event.target.value); setConfirmed(false); setAllowOpenWindow(false); setLookupNotice(null); setLookupError(null); setResult(null); setError(null); }}>
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
  </div>;
}
