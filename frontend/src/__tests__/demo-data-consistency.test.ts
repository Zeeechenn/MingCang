import { describe, expect, it } from 'vitest';

import { MC_DATA } from '../data';

describe('300308 demo dossier consistency', () => {
  const stock = MC_DATA.WATCHLIST.find((row) => row.symbol === '300308');

  it('uses the same signal score and long-term label across the snapshot', () => {
    expect(stock.latest_signal.composite_score).toBe(36);
    expect(MC_DATA.SIGNAL_FACTORS['300308'].formula).toContain('综合 36.0');
    expect(MC_DATA.ANALYSIS['300308']).toContain('综合 +36');
    expect(stock.long_term_label.label).toBe('值得持有');
    expect(MC_DATA.ANALYSIS['300308']).toContain('长期标签「值得持有」');
  });

  it('reports the actual demo evidence count and distinguishes target from current exposure', () => {
    expect(MC_DATA.EVIDENCE['300308']).toHaveLength(4);
    expect(stock.long_term_label.quality_notes.join(' ')).toContain('4 条新闻证据');
    expect(MC_DATA.DOSSIER['300308'].final_position).toBe('目标 ≤5%');
    expect(MC_DATA.EVIDENCE['300308'][2].detail).toContain('当前 12.8% 高于长期目标 5%');
    expect(MC_DATA.EVIDENCE['300308'][2].status).toBe('warning');
  });

  it('declares the snapshot date and demo provenance once for all sample surfaces', () => {
    expect(MC_DATA.DEMO_META).toMatchObject({
      is_demo: true,
      snapshot_as_of: '2026-06-09',
      provenance: 'frontend_static_snapshot',
    });
  });
});
