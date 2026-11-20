import { act, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { KakaoDiagnostics } from './KakaoDiagnostics';
import { api } from './api';
import type { KakaoChoice, KakaoDirectReadResult, KakaoReplyDraft } from './types';

vi.mock('./api', () => ({ api: { kakaoStatus: vi.fn(), kakaoCatalog: vi.fn(), kakaoVerify: vi.fn(), kakaoReadByName: vi.fn(), kakaoPrepareReply: vi.fn(), kakaoSendReply: vi.fn(), kakaoReplyHistory: vi.fn(), kakaoReviewAttempt: vi.fn() } }));
const choices = [{ id: 'synthetic-room-a', title: '합성 테스트 대화 A' }, { id: 'synthetic-room-b', title: '합성 테스트 대화 B' }];
beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(api.kakaoReplyHistory).mockResolvedValue({ attempts: [] });
  vi.mocked(api.kakaoStatus).mockResolvedValue({ installed: true });
  vi.mocked(api.kakaoReadByName).mockResolvedValue({ status: 'READ', count: 3 });
  vi.mocked(api.kakaoCatalog).mockResolvedValue({ choices });
  vi.mocked(api.kakaoVerify).mockResolvedValue({ baseline_count: 3, new_count: 0, status: 'UNCHANGED' });
});
async function open() {
  const user = userEvent.setup(); render(<KakaoDiagnostics />);
  await screen.findByText(/kmsg 실행 파일을 찾았습니다/);
  await user.click(screen.getByRole('button', { name: '진단 열기' }));
  return user;
}

describe('읽기 전용 진단', () => {
  it('시작과 화면 열기에는 설치 여부만 확인하며 실제 목록과 대화를 읽지 않는다', async () => {
    await open();
    expect(api.kakaoStatus).toHaveBeenCalledTimes(1);
    expect(api.kakaoCatalog).not.toHaveBeenCalled();
    expect(api.kakaoVerify).not.toHaveBeenCalled();
    expect(screen.queryByText(/brew install channprj\/tap\/kmsg/)).not.toBeInTheDocument();
    expect(screen.getByText(/대화 이름을 입력해 바로 읽을 수 있습니다/)).toBeInTheDocument();
    expect(screen.getByText('시스템 설정 → 개인정보 보호 및 보안 → 손쉬운 사용')).toBeInTheDocument();
    expect(screen.getByText('1:1 대화를 별도 창으로 열고 화면에 표시')).toBeInTheDocument();
  });

  it('미설치이면 읽기 작업을 막고 설치 안내를 제공한다', async () => {
    vi.mocked(api.kakaoStatus).mockResolvedValue({ installed: false });
    const user = userEvent.setup(); render(<KakaoDiagnostics />);
    await screen.findByText('kmsg 실행 파일을 찾지 못했습니다.');
    await user.click(screen.getByRole('button', { name: '진단 열기' }));
    expect(screen.getByRole('button', { name: '실제 대화 목록 조회' })).toBeDisabled();
    expect(screen.getByText(/brew install channprj\/tap\/kmsg/)).toBeInTheDocument();
    expect(api.kakaoCatalog).not.toHaveBeenCalled();
  });

  it('직접 선택과 1:1 확인 후에만 읽으며 결과를 자동 연결 성공으로 표시하지 않는다', async () => {
    const user = await open();
    await user.click(screen.getByRole('button', { name: '실제 대화 목록 조회' }));
    const verify = screen.getByRole('button', { name: '선택한 대화 읽기 확인' });
    expect(verify).toBeDisabled();
    await user.selectOptions(screen.getByLabelText('읽기 진단할 대화'), choices[0].id);
    expect(verify).toBeDisabled();
    await user.click(screen.getByRole('checkbox', { name: /선택한 대화가 원하는 상대/ }));
    await user.click(verify);
    expect(api.kakaoVerify).toHaveBeenCalledWith(choices[0].id, false);
    expect(await screen.findByText('kmsg가 관측 변경 없음으로 반환했습니다.')).toBeInTheDocument();
    expect(screen.getByText('kmsg가 반환한 관측 건수: 기준선 3건 · 추가 0건')).toBeInTheDocument();
    expect(screen.getByText(/자동 응답 연결이나 실제 발송 성공을 의미하지 않습니다/)).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText('읽기 진단할 대화'), choices[1].id);
    expect(screen.getByRole('checkbox', { name: /선택한 대화가 원하는 상대/ })).not.toBeChecked();
    expect(verify).toBeDisabled();
    expect(screen.queryByText('kmsg가 관측 변경 없음으로 반환했습니다.')).not.toBeInTheDocument();
  });

  it.each(['REVALIDATION_REQUIRED', 'BASELINE', 'constructor'])('관측 상태 %s를 정상 읽기로 표시하지 않는다', async status => {
    vi.mocked(api.kakaoVerify).mockResolvedValue({ baseline_count: 3, new_count: 1, status });
    const user = await open();
    await user.click(screen.getByRole('button', { name: '실제 대화 목록 조회' }));
    await user.selectOptions(screen.getByLabelText('읽기 진단할 대화'), choices[0].id);
    await user.click(screen.getByRole('checkbox', { name: /선택한 대화가 원하는 상대/ }));
    await user.click(screen.getByRole('button', { name: '선택한 대화 읽기 확인' }));
    expect(await screen.findByText('읽기 결과를 확정하지 못했습니다.')).toBeInTheDocument();
    expect(screen.queryByText('kmsg가 반환한 관측 건수: 기준선 3건 · 추가 1건')).not.toBeInTheDocument();
  });

  it('진단을 닫았다 열면 대화 이름과 선택·결과를 버리고 자동 재조회하지 않는다', async () => {
    const user = await open();
    await user.click(screen.getByRole('button', { name: '실제 대화 목록 조회' }));
    expect(screen.getByRole('option', { name: /합성 테스트 대화 A/ })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '진단 닫기' }));
    expect(screen.queryByRole('option', { name: /합성 테스트 대화 A/ })).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '진단 열기' }));
    expect(screen.queryByLabelText('읽기 진단할 대화')).not.toBeInTheDocument();
    expect(api.kakaoCatalog).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('button', { name: '실제 대화 목록 조회' })).toBeEnabled();
  });

  it('조회 중 닫아도 늦은 응답이 다시 대화 이름을 표시하지 않는다', async () => {
    let finish!: (value: { choices: KakaoChoice[] }) => void;
    vi.mocked(api.kakaoCatalog).mockReturnValue(new Promise(resolve => { finish = resolve; }));
    const user = await open();
    await user.click(screen.getByRole('button', { name: '실제 대화 목록 조회' }));
    await user.click(screen.getByRole('button', { name: '진단 닫기' }));
    await act(async () => finish({ choices }));
    await user.click(screen.getByRole('button', { name: '진단 열기' }));
    expect(screen.queryByLabelText('읽기 진단할 대화')).not.toBeInTheDocument();
  });

  it('읽기 실패 안내를 표시하고 확인 성공 결과를 남기지 않는다', async () => {
    vi.mocked(api.kakaoVerify).mockRejectedValue(new Error('다른 읽기 진단이 진행 중입니다. 잠시 후 다시 시도해 주세요.'));
    const user = await open();
    await user.click(screen.getByRole('button', { name: '실제 대화 목록 조회' }));
    await user.selectOptions(screen.getByLabelText('읽기 진단할 대화'), choices[0].id);
    await user.click(screen.getByRole('checkbox', { name: /선택한 대화가 원하는 상대/ }));
    await user.click(screen.getByRole('button', { name: '선택한 대화 읽기 확인' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('다른 읽기 진단이 진행 중입니다.');
    expect(screen.queryByText('kmsg가 관측 변경 없음으로 반환했습니다.')).not.toBeInTheDocument();
  });
});


describe('이름으로 바로 읽기', () => {
  it('명시적 1:1·창 열기 확인 뒤 direct API만 한 번 호출하고 건수와 출처만 표시한다', async () => {
    const user = await open();
    const read = screen.getByRole('button', { name: '이름으로 바로 읽기' });
    expect(read).toBeDisabled();
    await user.type(screen.getByLabelText('읽을 대화 이름'), choices[0].title);
    expect(read).toBeDisabled();
    await user.click(screen.getByRole('checkbox', { name: /입력한 이름이 원하는 1:1 대화/ }));
    expect(screen.getByText(/전경에서 한 번 실행해 최대 3건/)).toBeVisible();
    expect(screen.getByText(/반환된 제목이 입력한 이름과 다르면 읽기 결과를 버립니다/)).toBeVisible();
    await user.click(read);
    expect(api.kakaoReadByName).toHaveBeenCalledExactlyOnceWith(choices[0].title);
    expect(api.kakaoCatalog).not.toHaveBeenCalled();
    expect(api.kakaoVerify).not.toHaveBeenCalled();
    const form = within(screen.getByRole('form', { name: '대화 이름으로 바로 읽기' }));
    expect(await form.findByText('kmsg 이름 지정 읽기 결과')).toBeVisible();
    expect(form.getByText('kmsg가 반환한 관측 건수: 3건')).toBeVisible();
    expect(form.queryByText(/기준선|추가 관측/)).not.toBeInTheDocument();
    expect(screen.queryByLabelText('읽기 진단할 대화')).not.toBeInTheDocument();
  });

  it('빈 이름이나 공백만 입력하면 확인·읽기 버튼을 활성화하지 않는다', async () => {
    const user = await open();
    await user.type(screen.getByLabelText('읽을 대화 이름'), '   ');
    expect(screen.getByRole('checkbox', { name: /입력한 이름이 원하는 1:1 대화/ })).toBeDisabled();
    expect(screen.getByRole('button', { name: '이름으로 바로 읽기' })).toBeDisabled();
    expect(api.kakaoReadByName).not.toHaveBeenCalled();
    expect(api.kakaoCatalog).not.toHaveBeenCalled();
    expect(api.kakaoVerify).not.toHaveBeenCalled();
  });

  it('이름을 바꾸면 이전 확인과 결과를 무효화한다', async () => {
    const user = await open();
    await user.type(screen.getByLabelText('읽을 대화 이름'), choices[0].title);
    await user.click(screen.getByRole('checkbox', { name: /입력한 이름이 원하는 1:1 대화/ }));
    await user.click(screen.getByRole('button', { name: '이름으로 바로 읽기' }));
    await screen.findByText('kmsg가 반환한 관측 건수: 3건');
    await user.type(screen.getByLabelText('읽을 대화 이름'), '추가');
    expect(screen.getByRole('checkbox', { name: /입력한 이름이 원하는 1:1 대화/ })).not.toBeChecked();
    expect(screen.getByRole('button', { name: '이름으로 바로 읽기' })).toBeDisabled();
    expect(screen.queryByText('kmsg가 반환한 관측 건수: 3건')).not.toBeInTheDocument();
  });

  it('제목 불일치 오류는 입력 폼 바로 아래 표시하며 결과 건수를 표시하지 않는다', async () => {
    vi.mocked(api.kakaoReadByName).mockRejectedValue(new Error('kmsg가 반환한 대화 제목이 입력한 이름과 달라 읽기 결과를 버렸습니다.'));
    const user = await open();
    await user.type(screen.getByLabelText('읽을 대화 이름'), choices[0].title);
    await user.click(screen.getByRole('checkbox', { name: /입력한 이름이 원하는 1:1 대화/ }));
    await user.click(screen.getByRole('button', { name: '이름으로 바로 읽기' }));
    const form = within(screen.getByRole('form', { name: '대화 이름으로 바로 읽기' }));
    expect(await form.findByRole('alert')).toHaveTextContent('읽기 결과를 버렸습니다.');
    expect(form.queryByText(/kmsg가 반환한 관측 건수/)).not.toBeInTheDocument();
    expect(api.kakaoCatalog).not.toHaveBeenCalled();
    expect(api.kakaoVerify).not.toHaveBeenCalled();
  });

  it.each([-1, 4, 1.5])('잘못된 건수 %s는 정상 결과로 표시하지 않는다', async count => {
    vi.mocked(api.kakaoReadByName).mockResolvedValue({ status: 'READ', count });
    const user = await open();
    await user.type(screen.getByLabelText('읽을 대화 이름'), choices[0].title);
    await user.click(screen.getByRole('checkbox', { name: /입력한 이름이 원하는 1:1 대화/ }));
    await user.click(screen.getByRole('button', { name: '이름으로 바로 읽기' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('결과를 표시하지 않았습니다.');
    expect(screen.queryByText('kmsg 이름 지정 읽기 결과')).not.toBeInTheDocument();
  });

  it('읽기 대기 중 닫으면 늦은 결과와 이름을 복원하지 않는다', async () => {
    let finish!: (value: KakaoDirectReadResult) => void;
    vi.mocked(api.kakaoReadByName).mockReturnValue(new Promise(resolve => { finish = resolve; }));
    const user = await open();
    await user.type(screen.getByLabelText('읽을 대화 이름'), choices[0].title);
    await user.click(screen.getByRole('checkbox', { name: /입력한 이름이 원하는 1:1 대화/ }));
    await user.click(screen.getByRole('button', { name: '이름으로 바로 읽기' }));
    expect(screen.getByRole('button', { name: '실제 대화 목록 조회' })).toBeDisabled();
    await user.click(screen.getByRole('button', { name: '진단 닫기' }));
    await act(async () => finish({ status: 'READ', count: 2 }));
    await user.click(screen.getByRole('button', { name: '진단 열기' }));
    expect(screen.getByLabelText('읽을 대화 이름')).toHaveValue('');
    expect(screen.queryByText('kmsg가 반환한 관측 건수: 2건')).not.toBeInTheDocument();
  });

  it('별도 목록 조회 실패는 direct 이름 읽기를 막거나 자동 실행하지 않는다', async () => {
    vi.mocked(api.kakaoCatalog).mockRejectedValue(new Error('대화 목록 조회 시간이 초과되었습니다.'));
    const user = await open();
    await user.click(screen.getByRole('button', { name: '실제 대화 목록 조회' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('대화 목록 조회 시간이 초과되었습니다.');
    expect(api.kakaoReadByName).not.toHaveBeenCalled();
    await user.type(screen.getByLabelText('읽을 대화 이름'), choices[0].title);
    await user.click(screen.getByRole('checkbox', { name: /입력한 이름이 원하는 1:1 대화/ }));
    await user.click(screen.getByRole('button', { name: '이름으로 바로 읽기' }));
    expect(await screen.findByText('kmsg가 반환한 관측 건수: 3건')).toBeVisible();
    expect(api.kakaoCatalog).toHaveBeenCalledTimes(1);
    expect(api.kakaoVerify).not.toHaveBeenCalled();
  });
});

describe('최근 대화 답장', () => {
  const draft = { draft_id: 'synthetic-draft', in_reply_to: '합성 상대 메시지', text: '합성 초안\n— 부재중 AI 답장', context_count: 4, expires_in_seconds: 60 };
  async function chooseRoom() {
    const user = await open();
    await user.type(screen.getByLabelText('읽을 대화 이름'), choices[0].title);
    await user.click(screen.getByRole('checkbox', { name: /입력한 이름이 원하는 1:1 대화/ }));
    return user;
  }

  it('초안을 읽고 실제 대상·본문을 확인한 후에만 1회 발송한다', async () => {
    vi.mocked(api.kakaoPrepareReply).mockResolvedValue(draft);
    let finish!: (value: {status: 'CONFIRMED_LOCAL'}) => void;
    vi.mocked(api.kakaoSendReply).mockReturnValue(new Promise(resolve => { finish = resolve; }));
    const user = await chooseRoom();
    await user.click(screen.getByRole('button', { name: '답장 초안 만들기' }));
    expect(api.kakaoPrepareReply).toHaveBeenCalledExactlyOnceWith(choices[0].title);
    expect(screen.getByText('최근 대화 4건을 읽었습니다.')).toBeVisible();
    expect(screen.getByText(/합성 초안/)).toBeVisible();
    expect(screen.getByText(choices[0].title + '에게 보낼 답장')).toBeVisible();
    const send = screen.getByRole('button', { name: '카카오톡으로 1회 발송' });
    expect(send).toBeDisabled();
    expect(api.kakaoSendReply).not.toHaveBeenCalled();
    await user.click(screen.getByRole('checkbox', { name: /위 답장을 이 대화에/ }));
    await user.dblClick(send);
    expect(api.kakaoSendReply).toHaveBeenCalledExactlyOnceWith(draft.draft_id);
    expect(screen.queryByText(/이 답장의 발신을 확인/)).not.toBeInTheDocument();
    await act(async () => finish({ status: 'CONFIRMED_LOCAL' }));
    expect(screen.getByText(/이 답장의 발신을 확인/)).toBeVisible();
    expect(screen.queryByRole('button', { name: '카카오톡으로 1회 발송' })).not.toBeInTheDocument();
  });

  it('대상 이름이 바뀌면 초안과 발송 확인을 폐기한다', async () => {
    vi.mocked(api.kakaoPrepareReply).mockResolvedValue(draft);
    const user = await chooseRoom();
    await user.click(screen.getByRole('button', { name: '답장 초안 만들기' }));
    await user.click(screen.getByRole('checkbox', { name: /위 답장을 이 대화에/ }));
    await user.type(screen.getByLabelText('읽을 대화 이름'), '다른 방');
    expect(screen.queryByText(/합성 초안/)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '카카오톡으로 1회 발송' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '답장 초안 만들기' })).toBeDisabled();
    expect(api.kakaoSendReply).not.toHaveBeenCalled();
  });

  it('중지한 뒤 도착한 생성 결과로 발송할 수 없다', async () => {
    let finish!: (value: KakaoReplyDraft) => void;
    vi.mocked(api.kakaoPrepareReply).mockReturnValue(new Promise(resolve => { finish = resolve; }));
    const user = userEvent.setup();
    const { rerender } = render(<KakaoDiagnostics />);
    await screen.findByText(/kmsg 실행 파일을 찾았습니다/);
    await user.click(screen.getByRole('button', { name: '진단 열기' }));
    await user.type(screen.getByLabelText('읽을 대화 이름'), choices[0].title);
    await user.click(screen.getByRole('checkbox', { name: /입력한 이름이 원하는 1:1 대화/ }));
    await user.click(screen.getByRole('button', { name: '답장 초안 만들기' }));
    rerender(<KakaoDiagnostics stopVersion={1} />);
    await act(async () => finish(draft));
    expect(screen.queryByText(/합성 초안/)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '카카오톡으로 1회 발송' })).not.toBeInTheDocument();
    expect(api.kakaoSendReply).not.toHaveBeenCalled();
  });

  it('발송 결과가 불명확해도 자동으로 재시도하거나 성공을 표시하지 않는다', async () => {
    vi.mocked(api.kakaoPrepareReply).mockResolvedValue(draft);
    vi.mocked(api.kakaoSendReply).mockRejectedValue(new Error('발송 결과를 확인할 수 없습니다.'));
    const user = await chooseRoom();
    await user.click(screen.getByRole('button', { name: '답장 초안 만들기' }));
    await user.click(screen.getByRole('checkbox', { name: /위 답장을 이 대화에/ }));
    await user.click(screen.getByRole('button', { name: '카카오톡으로 1회 발송' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('발송 결과를 확인할 수 없습니다.');
    expect(screen.queryByRole('button', { name: '카카오톡으로 1회 발송' })).not.toBeInTheDocument();
    expect(screen.queryByText(/이 답장의 발신을 확인/)).not.toBeInTheDocument();
    expect(api.kakaoSendReply).toHaveBeenCalledTimes(1);
  });
});

it('결과 미확정 이력은 직접 확인을 기록한 뒤에도 발송 성공으로 바뀌지 않는다', async () => {
  const attempt = { id: 'synthetic-attempt', at: '2026-01-01T00:00:00Z', status: 'DELIVERY_UNKNOWN' as const, requires_review: true };
  vi.mocked(api.kakaoReplyHistory).mockResolvedValueOnce({ attempts: [attempt] }).mockResolvedValueOnce({ attempts: [{ ...attempt, requires_review: false }] });
  vi.mocked(api.kakaoReviewAttempt).mockResolvedValue({});
  const user = await open();
  await user.click(await screen.findByRole('button', { name: '카카오톡에서 발송 여부 확인 완료' }));
  expect(api.kakaoReviewAttempt).toHaveBeenCalledExactlyOnceWith(attempt.id);
  expect(await screen.findByText('사용자 확인 완료')).toBeVisible();
  expect(screen.getByText('발송 결과 미확정')).toBeVisible();
  expect(screen.queryByText('로컬 발신 확인')).not.toBeInTheDocument();
  expect(api.kakaoSendReply).not.toHaveBeenCalled();
});

it('화면 시계가 초안 유효 시간을 넘으면 발송 요청을 보내지 않는다', async () => {
  vi.mocked(api.kakaoPrepareReply).mockResolvedValue({ draft_id: 'synthetic-expiry', in_reply_to: '합성 질문', text: '합성 답장', context_count: 2, expires_in_seconds: 120 });
  const user = await open();
  await user.type(screen.getByLabelText('읽을 대화 이름'), choices[0].title);
  await user.click(screen.getByRole('checkbox', { name: /입력한 이름이 원하는 1:1 대화/ }));
  await user.click(screen.getByRole('button', { name: '답장 초안 만들기' }));
  await user.click(screen.getByRole('checkbox', { name: /위 답장을 이 대화에/ }));
  const now = vi.spyOn(Date, 'now').mockReturnValue(Date.now() + 121_000);
  try { await user.click(screen.getByRole('button', { name: '카카오톡으로 1회 발송' })); }
  finally { now.mockRestore(); }
  expect(screen.getByText(/초안이 만료되었습니다/)).toBeVisible();
  expect(api.kakaoSendReply).not.toHaveBeenCalled();
});
