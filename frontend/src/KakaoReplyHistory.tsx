import { useEffect, useState } from 'react';
import { api } from './api';
import type { KakaoReplyAttempt } from './types';

const displayTime = new Intl.DateTimeFormat('ko-KR', { dateStyle: 'short', timeStyle: 'medium' });

export function KakaoReplyHistory({ version, sending }: { version: number; sending: boolean }) {
  const [attempts, setAttempts] = useState<KakaoReplyAttempt[]>([]);
  const [reviewing, setReviewing] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);
  const [error, setError] = useState('');

  useEffect(() => {
    let active = true;
    setError('');
    api.kakaoReplyHistory().then(({ attempts }) => {
      if (active) setAttempts(attempts);
    }).catch(() => {
      if (active) { setAttempts([]); setError('최근 카카오톡 발송 이력을 확인하지 못했습니다.'); }
    });
    return () => { active = false; };
  }, [version, revision]);

  async function markReviewed(id: string) {
    if (sending || reviewing) return;
    setReviewing(id); setError('');
    try {
      await api.kakaoReviewAttempt(id);
      setRevision(value => value + 1);
    } catch (err) {
      setError(err instanceof Error ? err.message : '확인 결과를 기록하지 못했습니다.');
    } finally { setReviewing(null); }
  }

  if (!attempts.length && !error) return null;
  return <section className="context-reply" aria-labelledby="live-attempts-title">
    <h3 id="live-attempts-title">최근 카카오톡 발송 이력</h3>
    {error && <p className="help-text" role="status">{error}</p>}
    {attempts.length > 0 && <ul className="live-attempts">{attempts.map(attempt => {
      const confirmed = attempt.status === 'CONFIRMED_LOCAL';
      return <li key={attempt.id}>
        <time dateTime={attempt.at}>{Number.isFinite(Date.parse(attempt.at)) ? displayTime.format(new Date(attempt.at)) : '시각 미확인'}</time>
        <strong>{confirmed ? '로컬 발신 확인' : '발송 결과 미확정'}</strong>
        {attempt.status === 'DELIVERY_UNKNOWN' && (attempt.requires_review
          ? <div><p>카카오톡 대화창에서 발송 여부를 직접 확인해 주세요. 확인을 기록하면 다음 상대 메시지에 답할 수 있습니다.</p>
            <button type="button" className="button secondary" disabled={sending || reviewing !== null} onClick={() => void markReviewed(attempt.id)}>카카오톡에서 발송 여부 확인 완료</button></div>
          : <span>사용자 확인 완료</span>)}
      </li>;
    })}</ul>}
  </section>;
}
