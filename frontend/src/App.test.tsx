import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { App } from './App';
import { api } from './api';
import type { Job, RuntimeState } from './types';

vi.mock('./api', () => ({ api: { state: vi.fn(), reconnect: vi.fn(), start: vi.fn(), message: vi.fn(), advance: vi.fn(), pause: vi.fn(), detail: vi.fn() } }));

const base: RuntimeState = {
  transport: 'mock', mode: 'off', live_send_enabled: false, now: '2026-11-20T03:00:00Z',
  binding_id: 'synthetic-partner', reply_delay: 600, settle: 20, human_cooldown: 900,
  pending_due_at: null, paused_reason: null, simulated_send_count: 0, jobs: [],
};
const job: Job = { job_id: 'synthetic-job-1', state: 'PENDING', reason_codes: [], due_at: '2026-11-20T03:10:00Z', created_at: base.now, updated_at: base.now, incoming_count: 1, attempt_count: 0 };
const withState = (fields: Partial<RuntimeState>): RuntimeState => ({ ...base, ...fields });

beforeEach(() => { vi.resetAllMocks(); vi.mocked(api.state).mockResolvedValue(base); });

async function ready() { render(<App />); await screen.findByText('로컬 서버 연결됨'); }

describe('모의 대화 사용자 흐름', () => {
  it('안전한 기본 상태에서 시작하며 실제 연결로 표시하지 않는다', async () => {
    await ready();
    expect(screen.getByText('중지됨')).toBeInTheDocument();
    expect(screen.getByText('실제 전송 꺼짐')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '합성 메시지 넣기' })).toBeDisabled();
    expect(screen.getByText('지금은 모의 연결입니다.')).toBeInTheDocument();
  });

  it('합성 입력부터 대기와 모의 발송, 상세 생성문 조회까지 실행한다', async () => {
    const user = userEvent.setup();
    vi.mocked(api.start).mockResolvedValue(withState({ mode: 'auto' }));
    vi.mocked(api.message).mockResolvedValue(withState({ mode: 'auto', jobs: [job], pending_due_at: job.due_at }));
    const sent = { ...job, state: 'CONFIRMED_LOCAL', attempt_count: 1, updated_at: '2026-11-20T03:10:00Z', reason_codes: ['ACKNOWLEDGEMENT'] };
    vi.mocked(api.advance).mockResolvedValue(withState({ mode: 'auto', now: sent.updated_at, jobs: [sent], simulated_send_count: 1 }));
    vi.mocked(api.detail).mockResolvedValue({ ...sent, reply_text: '메시지 잘 봤어!\n— 부재중 AI 답장' });
    await ready();
    await user.click(screen.getByRole('button', { name: '모의 자동 시작' }));
    await user.click(screen.getByRole('button', { name: '합성 메시지 넣기' }));
    expect(api.message).toHaveBeenCalledWith('오늘 하루 어땠어?', 'partner');
    expect(await screen.findByText('답장 대기')).toBeInTheDocument();
    expect(screen.getByText('10분')).toBeInTheDocument();
    expect(api.detail).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: '다음 답장 시각까지 이동' }));
    expect(api.advance).toHaveBeenCalledWith(600);
    expect(await screen.findByText('모의 발송 확인')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '모의 발송 확인 상세 보기' }));
    expect(await screen.findByText(/메시지 잘 봤어!/)).toBeInTheDocument();
    expect(api.detail).toHaveBeenCalledWith(job.job_id);
  });

  it('본인 메시지를 보내면 취소 결과를 표시한다', async () => {
    const user = userEvent.setup();
    vi.mocked(api.state).mockResolvedValue(withState({ mode: 'auto', jobs: [job], pending_due_at: job.due_at }));
    vi.mocked(api.message).mockResolvedValue(withState({ mode: 'auto', jobs: [{ ...job, state: 'CANCELED_HUMAN', reason_codes: ['OWNER_REPLIED'] }] }));
    await ready();
    await user.selectOptions(screen.getByLabelText('누가 보낸 메시지인가요?'), 'owner');
    await user.clear(screen.getByLabelText('테스트 문장'));
    await user.type(screen.getByLabelText('테스트 문장'), '직접 답장할게');
    await user.click(screen.getByRole('button', { name: '합성 메시지 넣기' }));
    expect(api.message).toHaveBeenCalledWith('직접 답장할게', 'owner');
    expect(await screen.findByText('본인 답장으로 취소')).toBeInTheDocument();
    expect(screen.queryByText('OWNER_REPLIED')).not.toBeInTheDocument();
  });

  it('시간 이동 응답을 기다리는 중에도 중지하며 늦은 응답으로 활성 상태를 되살리지 않는다', async () => {
    const user = userEvent.setup();
    let finishAdvance!: (state: RuntimeState) => void;
    vi.mocked(api.state).mockResolvedValue(withState({ mode: 'auto', jobs: [job], pending_due_at: job.due_at }));
    vi.mocked(api.advance).mockReturnValue(new Promise(resolve => { finishAdvance = resolve; }));
    vi.mocked(api.pause).mockResolvedValue(withState({ paused_reason: 'STOPPED', jobs: [{ ...job, state: 'CANCELED_STALE' }] }));
    await ready();
    await user.click(screen.getByRole('button', { name: '+10분' }));
    expect(screen.getByRole('button', { name: '즉시 중지' })).toBeEnabled();
    await user.click(screen.getByRole('button', { name: '즉시 중지' }));
    expect(await screen.findByText('중지됨')).toBeInTheDocument();
    await act(async () => finishAdvance(withState({ mode: 'auto', jobs: [job] })));
    expect(screen.getByText('중지됨')).toBeInTheDocument();
    expect(screen.queryByText('모의 자동 모드')).not.toBeInTheDocument();
  });

  it('서버 실패를 성공으로 표시하지 않고 연결 재시도로 회복한다', async () => {
    const user = userEvent.setup();
    vi.mocked(api.start).mockRejectedValue(new Error('로컬 서버에 연결하지 못했습니다.'));
    vi.mocked(api.reconnect).mockResolvedValue(base);
    await ready();
    await user.click(screen.getByRole('button', { name: '모의 자동 시작' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('로컬 서버에 연결하지 못했습니다.');
    expect(screen.getByText('중지됨')).toBeInTheDocument();
    expect(screen.queryByText('모의 자동 모드를 시작했습니다.')).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '연결 다시 확인' }));
    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument());
  });

  it('초안 모드와 작성자 불명 메시지를 구분해 요청한다', async () => {
    const user = userEvent.setup();
    vi.mocked(api.start).mockResolvedValue(withState({ mode: 'draft' }));
    vi.mocked(api.message).mockResolvedValue(withState({ mode: 'draft', jobs: [{ ...job, state: 'SKIPPED_POLICY', reason_codes: ['AMBIGUOUS_AUTHOR_OR_CONTEXT'] }] }));
    await ready();
    await user.click(screen.getByRole('button', { name: '초안만 생성' }));
    expect(api.start).toHaveBeenCalledWith('draft');
    await user.selectOptions(screen.getByLabelText('누가 보낸 메시지인가요?'), 'unknown');
    await user.click(screen.getByRole('button', { name: '합성 메시지 넣기' }));
    expect(api.message).toHaveBeenCalledWith('오늘 하루 어땠어?', 'unknown');
    expect(await screen.findByText('정책에 따라 보류')).toBeInTheDocument();
    expect(screen.queryByText('AMBIGUOUS_AUTHOR_OR_CONTEXT')).not.toBeInTheDocument();
  });
});
