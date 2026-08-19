import { describe, expect, it } from 'vitest';

const pageSources = import.meta.glob('../page-*.tsx', {
  eager: true,
  query: '?raw',
  import: 'default',
}) as Record<string, string>;

describe('frontend page implementation boundaries', () => {
  it('forbids page-to-page implementation imports', () => {
    const offenders: string[] = [];
    for (const [file, text] of Object.entries(pageSources)) {
      const matches = text.match(/from ['"]\.\/page-[^'"]+['"]/g) || [];
      offenders.push(...matches.map((match) => `${file}: ${match}`));
    }
    expect(offenders).toEqual([]);
  });
});
