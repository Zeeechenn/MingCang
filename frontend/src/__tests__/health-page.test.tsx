import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { HealthPage } from '../page-health';
import { refreshCoverage } from '../services/live';

vi.mock('../services/live', () => ({ refreshCoverage: vi.fn(() => Promise.resolve({ status: 'pass' })) }));

describe('HealthPage', () => {
  beforeEach(() => vi.mocked(refreshCoverage).mockClear());

  it('runs the real read-only coverage refresh callback', async () => {
    render(<HealthPage />);
    fireEvent.click(screen.getByRole('button', { name: '重新检查' }));

    await waitFor(() => expect(refreshCoverage).toHaveBeenCalledTimes(1));
  });

  it('opens the real coverage CSV endpoint when the backend is live', () => {
    window.MC_LIVE = { isLive: vi.fn(() => true) } as any;
    const open = vi.spyOn(window, 'open').mockImplementation(() => null);
    render(<HealthPage />);

    fireEvent.click(screen.getByRole('button', { name: '导出 CSV' }));

    expect(open).toHaveBeenCalledWith('/api/export/coverage.csv', '_blank', 'noopener,noreferrer');
    open.mockRestore();
  });
});
