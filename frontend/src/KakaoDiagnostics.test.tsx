import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { KakaoDiagnostics } from './KakaoDiagnostics';
import { api } from './api';
import type { KakaoChoice } from './types';

vi.mock('./api', () => ({ api: { kakaoStatus: vi.fn(), kakaoCatalog: vi.fn(), kakaoVerify: vi.fn() } }));
const choices = [{ id: 'synthetic-room-a', title: '합성 테스트 대화 A' }, { id: 'synthetic-room-b', title: '합성 테스트 대화 B' }];
beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(api.kakaoStatus).mockResolvedValue({ installed: true });
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
    expect(screen.getByText(/대상을 선택하면 읽기를 확인할 수 있습니다/)).toBeInTheDocument();
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
    await user.click(screen.getByRole('checkbox'));
    await user.click(verify);
    expect(api.kakaoVerify).toHaveBeenCalledWith(choices[0].id);
    expect(await screen.findByText('새로 관측된 메시지가 없습니다.')).toBeInTheDocument();
    expect(screen.getByText('기준선 3건 · 새로 관측 0건')).toBeInTheDocument();
    expect(screen.getByText(/자동 응답 연결이나 실제 발송 성공을 의미하지 않습니다/)).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText('읽기 진단할 대화'), choices[1].id);
    expect(screen.getByRole('checkbox')).not.toBeChecked();
    expect(verify).toBeDisabled();
    expect(screen.queryByText('새로 관측된 메시지가 없습니다.')).not.toBeInTheDocument();
  });

  it.each(['REVALIDATION_REQUIRED', 'BASELINE', 'constructor'])('관측 상태 %s를 정상 읽기로 표시하지 않는다', async status => {
    vi.mocked(api.kakaoVerify).mockResolvedValue({ baseline_count: 3, new_count: 1, status });
    const user = await open();
    await user.click(screen.getByRole('button', { name: '실제 대화 목록 조회' }));
    await user.selectOptions(screen.getByLabelText('읽기 진단할 대화'), choices[0].id);
    await user.click(screen.getByRole('checkbox'));
    await user.click(screen.getByRole('button', { name: '선택한 대화 읽기 확인' }));
    expect(await screen.findByText('읽기 결과를 확정하지 못했습니다.')).toBeInTheDocument();
    expect(screen.queryByText('기준선 3건 · 새로 관측 1건')).not.toBeInTheDocument();
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
    await user.click(screen.getByRole('checkbox'));
    await user.click(screen.getByRole('button', { name: '선택한 대화 읽기 확인' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('다른 읽기 진단이 진행 중입니다.');
    expect(screen.queryByText('새로 관측된 메시지가 없습니다.')).not.toBeInTheDocument();
  });
});
