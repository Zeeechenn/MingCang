import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import {
  refreshResearchCopilot,
  reviewLatestSignal,
  runDeepResearch,
  triggerKillSwitch,
  triggerLongTermTeam,
} from '../services/api';
import { AdminPage } from '../page-admin';
import { PositionsPage } from '../page-positions';
import { StockPage } from '../page-stock';

vi.mock('../services/api', async (importOriginal) => {
  const original = await importOriginal<typeof import('../services/api')>();
  return {
    ...original,
    refreshResearchCopilot: vi.fn(() => Promise.resolve({ stance: 'neutral' })),
    reviewLatestSignal: vi.fn(() => Promise.resolve({ status: 'ok' })),
    runDeepResearch: vi.fn(() => Promise.resolve({ status: 'ok' })),
    triggerKillSwitch: vi.fn(() => Promise.resolve({ active: true })),
    triggerLongTermTeam: vi.fn(() => Promise.resolve({ status: 'triggered' })),
  };
});

class ResizeObserverStub {
  observe() {}
  disconnect() {}
}

describe('frontend operation truth', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal('ResizeObserver', ResizeObserverStub);
    window.MC_LIVE = {
      ensureSymbol: vi.fn(),
      createPosition: vi.fn(() => Promise.resolve({ id: 99 })),
      closePosition: vi.fn(() => Promise.resolve({ status: 'closed' })),
      deletePosition: vi.fn(() => Promise.resolve({ status: 'deleted' })),
      saveRuntime: vi.fn(() => Promise.resolve({})),
      memoryConfirm: vi.fn(() => Promise.resolve({})),
      memoryDelete: vi.fn(() => Promise.resolve({})),
    } as any;
  });

  it('uses the real stock review and copilot APIs', async () => {
    render(<StockPage symbol="300308" />);

    fireEvent.click(screen.getByRole('button', { name: '复盘最新信号' }));
    await waitFor(() => expect(reviewLatestSignal).toHaveBeenCalledWith('300308'));

    fireEvent.click(screen.getByRole('button', { name: '刷新副驾驶' }));
    await waitFor(() => expect(refreshResearchCopilot).toHaveBeenCalledWith('300308'));
  });

  it('confirms and runs real research operations from governance', async () => {
    render(<AdminPage />);
    fireEvent.click(screen.getByRole('button', { name: /研究团队/ }));

    fireEvent.change(screen.getByPlaceholderText('深度研究主题，如:AI 光模块供需'), {
      target: { value: 'AI 光模块供需' },
    });
    fireEvent.change(screen.getByPlaceholderText('标的，逗号分隔'), {
      target: { value: '300308,002475' },
    });
    fireEvent.click(screen.getByRole('button', { name: '运行深度研究' }));
    expect(runDeepResearch).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: '确认运行深度研究' }));
    await waitFor(() => expect(runDeepResearch).toHaveBeenCalledWith({
      topic: 'AI 光模块供需',
      symbols: ['300308', '002475'],
      as_of: null,
    }));

    fireEvent.click(screen.getByRole('button', { name: '运行长期团队' }));
    expect(triggerLongTermTeam).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: '确认运行长期团队' }));
    await waitFor(() => expect(triggerLongTermTeam).toHaveBeenCalledTimes(1));
  });

  it('uses the real kill switch API and keeps credentials honest', async () => {
    render(<AdminPage />);
    fireEvent.click(screen.getByRole('button', { name: /熔断保护/ }));
    fireEvent.click(screen.getByRole('button', { name: '触发熔断' }));
    fireEvent.click(screen.getByRole('button', { name: '确认触发' }));
    await waitFor(() => expect(triggerKillSwitch).toHaveBeenCalledWith('web_governance'));

    fireEvent.click(screen.getByRole('button', { name: /本地凭证/ }));
    expect(screen.getAllByText('仅支持手动配置').length).toBeGreaterThan(0);
    expect(screen.queryByPlaceholderText('粘贴 API Key')).not.toBeInTheDocument();
  });

  it('requires a second explicit confirmation before creating a position', async () => {
    render(<PositionsPage />);
    fireEvent.change(screen.getByPlaceholderText('代码或名称'), { target: { value: '300308' } });
    fireEvent.change(screen.getByPlaceholderText('名称自动补全'), { target: { value: '中际旭创' } });
    fireEvent.change(screen.getByPlaceholderText('数量'), { target: { value: '100' } });
    fireEvent.change(screen.getByPlaceholderText('成本价'), { target: { value: '150' } });
    fireEvent.click(screen.getByRole('button', { name: '添加' }));

    expect(window.MC_LIVE.createPosition).not.toHaveBeenCalled();
    expect(screen.getByText(/中际旭创.*300308/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '确认写入持仓' }));

    await waitFor(() => expect(window.MC_LIVE.createPosition).toHaveBeenCalledWith({
      symbol: '300308',
      name: '中际旭创',
      market: 'CN',
      quantity: 100,
      avg_cost: 150,
    }));
  });
});
