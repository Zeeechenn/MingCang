import { describe, expect, it } from 'vitest';

import { FRONTEND_RUNTIME_IDENTITY, assessBackendRuntime } from '../runtime-identity';

describe('runtime identity trust boundary', () => {
  it('accepts a matching primary runtime', () => {
    const result = assessBackendRuntime({
      version: FRONTEND_RUNTIME_IDENTITY.version,
      build_commit: 'unknown',
      db_role: 'primary',
      db_latest_date: '2026-07-15',
      scheduler_mode: 'manual',
      database_exists: true,
    });

    expect(result.compatible).toBe(true);
    expect(result.issues).toEqual([]);
  });

  it('degrades version mismatches and demo databases', () => {
    const result = assessBackendRuntime({
      version: '0.5.2',
      db_role: 'demo',
      db_latest_date: '2026-06-03',
      scheduler_mode: 'manual',
      database_exists: true,
    });

    expect(result.compatible).toBe(false);
    expect(result.issues.join(' ')).toMatch(/版本不一致/);
    expect(result.issues.join(' ')).toMatch(/demo/);
  });
});
