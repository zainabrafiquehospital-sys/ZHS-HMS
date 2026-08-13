import { describe, expect, it } from 'vitest';
import { computePageCount } from './pagination';

describe('computePageCount', () => {
  it('divides total by page size, rounding up', () => {
    expect(computePageCount(45, 20)).toBe(3);
    expect(computePageCount(40, 20)).toBe(2);
    expect(computePageCount(41, 20)).toBe(3);
  });

  it('returns exactly 1 page when total is less than one page size', () => {
    expect(computePageCount(5, 20)).toBe(1);
  });

  it('floors at 1 page for an empty result set, never 0', () => {
    expect(computePageCount(0, 20)).toBe(1);
  });

  it('floors at 1 page when total is not yet known (undefined/null meta)', () => {
    expect(computePageCount(undefined, 20)).toBe(1);
    expect(computePageCount(null, 20)).toBe(1);
  });

  it('floors at 1 page for a degenerate page size', () => {
    expect(computePageCount(50, 0)).toBe(1);
    expect(computePageCount(50, undefined)).toBe(1);
  });
});
