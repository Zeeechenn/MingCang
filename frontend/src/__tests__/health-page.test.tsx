import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { HealthPage } from '../page-health';
import { refreshCoverage } from '../live';

vi.mock('../live', () => ({ refreshCoverage: vi.fn(() => Promise.resolve({ status: 'pass' })) }));

describe('HealthPage', () => {
  beforeEach(() => vi.mocked(refreshCoverage).mockClear());

  it('runs the real read-only coverage refresh callback', async () => {
    render(<HealthPage />);
    fireEvent.click(screen.getByRole('button', { name: '重新检查' }));

    await waitFor(() => expect(refreshCoverage).toHaveBeenCalledTimes(1));
  });
});
