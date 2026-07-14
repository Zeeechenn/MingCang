import { act, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { MCStore, useStockSuggest } from '../shared';

function SearchHarness({ query, market = 'CN' }: { query: string; market?: string }) {
  const rows = useStockSuggest(query, market);
  return <div>{rows.map((row) => `${row.name} ${row.symbol}`).join('|')}</div>;
}

describe('live stock search', () => {
  beforeEach(() => {
    MCStore.set({ live: 'live', liveSources: { watchlist: 'live' } });
    window.MC_LIVE = {
      searchStocks: vi.fn().mockResolvedValue([
        { symbol: '300750', name: '宁德时代', market: 'CN', source: 'akshare' },
      ]),
    };
  });

  it('queries /stocks/search through the live facade instead of limiting results to the watchlist', async () => {
    render(<SearchHarness query="宁德时代" />);

    await waitFor(() => expect(window.MC_LIVE.searchStocks).toHaveBeenCalledWith('宁德时代', 'CN'));
    expect(await screen.findByText('宁德时代 300750')).toBeInTheDocument();
  });

  it('ignores an older response after the query changes', async () => {
    let resolveOld: (value: any[]) => void = () => {};
    vi.mocked(window.MC_LIVE.searchStocks)
      .mockImplementationOnce(() => new Promise((resolve) => { resolveOld = resolve; }))
      .mockResolvedValueOnce([{ symbol: '688041', name: '海光信息', market: 'CN' }]);

    const view = render(<SearchHarness query="宁德" />);
    await waitFor(() => expect(window.MC_LIVE.searchStocks).toHaveBeenCalledWith('宁德', 'CN'));
    view.rerender(<SearchHarness query="海光" />);
    expect(await screen.findByText('海光信息 688041')).toBeInTheDocument();

    await act(async () => resolveOld([{ symbol: '300750', name: '宁德时代', market: 'CN' }]));
    expect(screen.queryByText('宁德时代 300750')).not.toBeInTheDocument();
  });
});
