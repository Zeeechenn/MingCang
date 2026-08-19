import { render, screen } from '@testing-library/react';
import React from 'react';
import { describe, expect, it } from 'vitest';

import * as legacyApi from '../api';
import * as legacyLive from '../live';
import * as api from '../services/api';
import * as live from '../services/live';
import { useRoute } from '../shared';

function RouteProbe() {
  const route = useRoute();
  return React.createElement(
    'div',
    { 'data-testid': 'route' },
    `${route.page}:${route.market || ''}:${route.symbol || ''}`,
  );
}

describe('frontend service boundaries', () => {
  it('keeps the pre-M66 API entry point as a compatibility export', () => {
    expect(legacyApi.getLatestM63Report).toBe(api.getLatestM63Report);
  });

  it('keeps the pre-M66 live entry point as a compatibility export', () => {
    expect(legacyLive.refreshCoverage).toBe(live.refreshCoverage);
    expect(legacyLive.startLive).toBe(live.startLive);
  });

  it('strips hash query strings before route matching while preserving stock routes', () => {
    window.location.hash = '#/daily?tab=shadow';
    const { unmount } = render(React.createElement(RouteProbe));
    expect(screen.getByTestId('route')).toHaveTextContent('daily::');
    unmount();

    window.location.hash = '#/stock/HK/00700?tab=shadow';
    render(React.createElement(RouteProbe));
    expect(screen.getByTestId('route')).toHaveTextContent('stock:HK:00700');
    window.location.hash = '';
  });
});
