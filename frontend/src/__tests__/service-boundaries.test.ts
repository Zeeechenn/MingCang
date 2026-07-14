import { describe, expect, it } from 'vitest';

import * as legacyApi from '../api';
import * as legacyLive from '../live';
import * as api from '../services/api';
import * as live from '../services/live';

describe('frontend service boundaries', () => {
  it('keeps the pre-M66 API entry point as a compatibility export', () => {
    expect(legacyApi.getLatestM63Report).toBe(api.getLatestM63Report);
  });

  it('keeps the pre-M66 live entry point as a compatibility export', () => {
    expect(legacyLive.refreshCoverage).toBe(live.refreshCoverage);
    expect(legacyLive.startLive).toBe(live.startLive);
  });
});
