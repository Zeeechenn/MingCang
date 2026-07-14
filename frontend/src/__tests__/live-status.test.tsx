import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { LiveStatusBadgeView, deriveLiveMode } from '../live-status';

describe('live source truth', () => {
  it('marks a mixed backend/demo payload as degraded', () => {
    expect(deriveLiveMode({ watchlist: 'live', positions: 'live', coverage: 'demo' })).toBe('degraded');
  });

  it('names degraded domains and the demo snapshot date', () => {
    render(
      <LiveStatusBadgeView
        mode="degraded"
        sources={{ watchlist: 'live', coverage: 'demo' }}
        snapshotAsOf="2026-06-09"
      />,
    );

    expect(screen.getByText('部分实时')).toBeInTheDocument();
    expect(screen.getByTitle(/coverage.*2026-06-09/)).toBeInTheDocument();
  });
});
