import { describe, expect, it } from 'vitest';

import { assetKey, currencyAmount, scopedData, stockPath } from '../shared';

describe('multi-market frontend boundaries', () => {
  it('keeps market identity in routes and cache keys', () => {
    expect(assetKey('700', 'HK')).toBe('HK:00700');
    expect(stockPath('00700', 'HK')).toBe('/stock/HK/00700');
    expect(stockPath('AAPL', 'US')).toBe('/stock/US/AAPL');
  });

  it('reads scoped live data before legacy symbol data', () => {
    const rows = {
      AAPL: ['legacy'],
      'US:AAPL': ['us-live'],
      'HK:AAPL': ['hk-live'],
    };

    expect(scopedData(rows, 'AAPL', 'US')).toEqual(['us-live']);
    expect(scopedData(rows, 'AAPL', 'HK')).toEqual(['hk-live']);
  });

  it('never presents cross-market money without a currency', () => {
    expect(currencyAmount(12_000, 'CN')).toBe('CNY 12,000');
    expect(currencyAmount(12_000, 'HK')).toBe('HKD 12,000');
    expect(currencyAmount(12_000, 'US')).toBe('USD 12,000');
  });
});
