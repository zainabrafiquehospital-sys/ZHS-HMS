import { describe, expect, it } from 'vitest';
import { deriveVitalsStatus, VITALS_STATUS } from './vitalsStatus';

describe('deriveVitalsStatus', () => {
  it('returns "collected" whenever at least one reading is on file, regardless of vitals_required', () => {
    expect(deriveVitalsStatus([{ id: 'v1' }], true)).toBe(VITALS_STATUS.COLLECTED);
    expect(deriveVitalsStatus([{ id: 'v1' }], false)).toBe(VITALS_STATUS.COLLECTED);
    expect(deriveVitalsStatus([{ id: 'v1' }, { id: 'v2' }], false)).toBe(VITALS_STATUS.COLLECTED);
  });

  it('returns "pending" when nothing is on file but the visit was flagged vitals-required', () => {
    expect(deriveVitalsStatus([], true)).toBe(VITALS_STATUS.PENDING);
    expect(deriveVitalsStatus(undefined, true)).toBe(VITALS_STATUS.PENDING);
    expect(deriveVitalsStatus(null, true)).toBe(VITALS_STATUS.PENDING);
  });

  it('returns "not_required" when nothing is on file and the visit was not flagged', () => {
    expect(deriveVitalsStatus([], false)).toBe(VITALS_STATUS.NOT_REQUIRED);
    expect(deriveVitalsStatus(undefined, false)).toBe(VITALS_STATUS.NOT_REQUIRED);
    expect(deriveVitalsStatus(null, undefined)).toBe(VITALS_STATUS.NOT_REQUIRED);
  });
});
