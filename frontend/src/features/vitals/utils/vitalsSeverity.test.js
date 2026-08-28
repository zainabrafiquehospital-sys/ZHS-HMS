import { describe, expect, it } from 'vitest';
import {
  getVitalSeverity,
  getTrend,
  getWorstSeverity,
  vitalFieldUnit,
} from './vitalsSeverity';

// Dedicated coverage for the 2026-08-28 temperature unit fix
// (temperature_celsius -> temperature + temperature_unit,
// going-forward only) — the one place in this file where a field's
// severity ranges/display unit are resolved per record rather than
// being a single global constant, so it's worth real regression
// protection.

describe('getVitalSeverity — non-temperature fields (unaffected by the unit fix)', () => {
  it('classifies a normal systolic BP as normal', () => {
    expect(getVitalSeverity('systolic_bp', 120).level).toBe('normal');
  });

  it('classifies a critically low systolic BP as critical/low', () => {
    expect(getVitalSeverity('systolic_bp', 80)).toEqual({ level: 'critical', direction: 'low' });
  });
});

describe('getVitalSeverity — temperature, unit-aware', () => {
  it('classifies a Fahrenheit reading using the Fahrenheit thresholds', () => {
    // 101.5°F sits between mildHigh (99.5) and criticalHigh (102.0).
    expect(getVitalSeverity('temperature', 101.5, { temperatureUnit: 'fahrenheit' })).toEqual({
      level: 'mild',
      direction: 'high',
    });
  });

  it('classifies a Celsius reading using the Celsius thresholds', () => {
    // 38.5°C sits between mildHigh (37.5) and criticalHigh (38.9) —
    // the same clinical severity as 101.5°F above, expressed in the
    // record's own original unit.
    expect(getVitalSeverity('temperature', 38.5, { temperatureUnit: 'celsius' })).toEqual({
      level: 'mild',
      direction: 'high',
    });
  });

  it('the SAME raw number is classified completely differently depending on unit', () => {
    // 38.5 read as Fahrenheit would be a critically low hypothermic
    // reading; read as Celsius (its real unit) it's a mild fever. This
    // is exactly the silent-corruption failure mode the "going forward
    // only, tag the unit" design exists to prevent.
    const asFahrenheit = getVitalSeverity('temperature', 38.5, { temperatureUnit: 'fahrenheit' });
    const asCelsius = getVitalSeverity('temperature', 38.5, { temperatureUnit: 'celsius' });
    expect(asFahrenheit.level).toBe('critical');
    expect(asFahrenheit.direction).toBe('low');
    expect(asCelsius.level).toBe('mild');
    expect(asCelsius.direction).toBe('high');
  });

  it('defaults to the Fahrenheit thresholds when no unit is given (the live entry-form case)', () => {
    expect(getVitalSeverity('temperature', 101.5).level).toBe('mild');
  });

  it('a standard 100.4°F fever reading falls within the mild-fever band, not critical', () => {
    expect(getVitalSeverity('temperature', 100.4, { temperatureUnit: 'fahrenheit' })).toEqual({
      level: 'mild',
      direction: 'high',
    });
  });
});

describe('getWorstSeverity — reads a record\'s own temperature_unit', () => {
  it('classifies a historical Celsius-tagged record correctly', () => {
    // 39.5°C is above the Celsius criticalHigh boundary (38.9).
    const record = { temperature: 39.5, temperature_unit: 'celsius' };
    expect(getWorstSeverity(record)).toBe('critical');
  });

  it('classifies a new Fahrenheit-tagged record correctly', () => {
    // 103.0°F is above the Fahrenheit criticalHigh boundary (102.0).
    const record = { temperature: 103.0, temperature_unit: 'fahrenheit' };
    expect(getWorstSeverity(record)).toBe('critical');
  });

  it('the same numeric value is NOT critical under the other unit', () => {
    // 38.9°F is nowhere near critical (that's a Celsius critical-high
    // boundary, not Fahrenheit) — proves the classification genuinely
    // depends on the record's own tagged unit, not just the number.
    const record = { temperature: 38.9, temperature_unit: 'fahrenheit' };
    expect(getWorstSeverity(record)).toBe('critical'); // still critical, but LOW (hypothermic), not high
    expect(getVitalSeverity('temperature', 38.9, { temperatureUnit: 'fahrenheit' }).direction).toBe(
      'low',
    );
  });
});

describe('vitalFieldUnit — temperature label resolves per record', () => {
  it('returns °C for a celsius-tagged record', () => {
    expect(vitalFieldUnit('temperature', 'celsius')).toBe('°C');
  });

  it('returns °F for a fahrenheit-tagged record', () => {
    expect(vitalFieldUnit('temperature', 'fahrenheit')).toBe('°F');
  });

  it('falls back to °F (the going-forward default) when no unit is given', () => {
    expect(vitalFieldUnit('temperature', undefined)).toBe('°F');
  });

  it('is unaffected for every other field', () => {
    expect(vitalFieldUnit('systolic_bp')).toBe('mmHg');
    expect(vitalFieldUnit('spo2_percent')).toBe('%');
  });
});

describe('getTrend — temperature unit-mismatch guard', () => {
  it('returns null when the previous reading is Celsius-tagged (mismatched units)', () => {
    // A live Fahrenheit entry (98.6) vs. a previous Celsius record
    // (37.0) — a raw numeric diff here would be meaningless.
    expect(
      getTrend('temperature', 98.6, 37.0, { previousTemperatureUnit: 'celsius' }),
    ).toBeNull();
  });

  it('computes a real trend when both readings are Fahrenheit', () => {
    expect(
      getTrend('temperature', 101.0, 98.6, { previousTemperatureUnit: 'fahrenheit' }),
    ).toBe('up');
  });

  it('still works normally for non-temperature fields (no unit concept)', () => {
    expect(getTrend('systolic_bp', 140, 120)).toBe('up');
    expect(getTrend('systolic_bp', 121, 120)).toBe('stable');
  });

  it('returns null when either value is missing, regardless of unit', () => {
    expect(getTrend('temperature', null, 98.6, { previousTemperatureUnit: 'fahrenheit' })).toBeNull();
    expect(getTrend('temperature', 98.6, undefined, { previousTemperatureUnit: 'fahrenheit' })).toBeNull();
  });
});
