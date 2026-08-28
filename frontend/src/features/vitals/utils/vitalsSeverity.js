/**
 * Clinical reference ranges and severity classification for the 5
 * vitals fields that have a well-established, single-value acute
 * safety threshold: systolic/diastolic BP, pulse rate, temperature,
 * and SpO2. `weight_kg`/`height_cm` are deliberately excluded — unlike
 * the other five, there is no simple universal "critical value"
 * threshold for a standalone weight or height reading (that requires
 * context this form doesn't have, like a growth chart or BMI paired
 * with the other), so flagging them would be fabricating a threshold
 * rather than applying an established one.
 *
 * Ranges are standard ADULT clinical thresholds (this is predominantly
 * an adult OB/GYN population), commonly cited in nursing/EWS
 * reference material — not a substitute for clinical judgment, and
 * deliberately conservative rather than hyper-precise. `pulse_rate` is
 * the one field given a second, pediatric band: resting heart rate is
 * both the most age-sensitive of these five vitals and the one where
 * a simple child-vs-adult split is well-established and low-risk to
 * apply. Blood pressure genuinely also varies by age in real pediatric
 * practice, but real pediatric BP norms are height/percentile-based —
 * far too much to responsibly encode as a flat threshold from general
 * knowledge, so BP intentionally uses the same adult range regardless
 * of age. Patient age/gender are still surfaced in the UI so the nurse
 * or doctor can apply their own judgment for anything this
 * simplification doesn't cover — this module narrows the range of
 * what it claims to know, it doesn't pretend to cover everything.
 *
 * Each range is {criticalLow, mildLow, mildHigh, criticalHigh}:
 *   value <  criticalLow             -> critical (low)
 *   criticalLow <= value < mildLow   -> mild (low)
 *   mildLow <= value <= mildHigh     -> normal
 *   mildHigh < value <= criticalHigh -> mild (high)
 *   value >  criticalHigh            -> critical (high)
 *
 * `temperature` (2026-08-28 change, was `temperature_celsius`) is a
 * going-forward-only unit fix — see backend app/modules/vitals/
 * models.py's `VitalsRecord` docstring for the full rationale. Every
 * NEW reading is Fahrenheit; every reading recorded before this change
 * stays exactly as originally captured, in Celsius, tagged
 * `temperature_unit: 'celsius'`. Because a single "temperature" field
 * can now genuinely mean either unit depending on which record it came
 * from, its severity ranges/display unit are the one place in this
 * module that are resolved *per record* (via that record's own
 * `temperature_unit`) rather than being a single global constant —
 * every caller that already has severity ranges elsewhere in this file
 * as a flat, unit-less lookup must pass `temperatureUnit` for this one
 * field. `TEMPERATURE_RANGES.fahrenheit` is the exact conversion
 * (F = C*9/5+32, two boundaries rounded to a clean tenth) of the
 * pre-existing Celsius thresholds below it — the same clinical cutoffs,
 * not a redesign.
 */

const PEDIATRIC_AGE_CUTOFF_YEARS = 12;

const ADULT_RANGES = {
  systolic_bp: { criticalLow: 90, mildLow: 100, mildHigh: 139, criticalHigh: 179 },
  diastolic_bp: { criticalLow: 50, mildLow: 60, mildHigh: 89, criticalHigh: 119 },
  pulse_rate: { criticalLow: 50, mildLow: 60, mildHigh: 100, criticalHigh: 119 },
  spo2_percent: { criticalLow: 91, mildLow: 95, mildHigh: 100, criticalHigh: 100 },
};

// See this file's own top-level docstring — resolved per record via
// `temperature_unit`, never a single global range the way every other
// field's is.
const TEMPERATURE_RANGES = {
  celsius: { criticalLow: 35.0, mildLow: 36.1, mildHigh: 37.5, criticalHigh: 38.9 },
  fahrenheit: { criticalLow: 95.0, mildLow: 97.0, mildHigh: 99.5, criticalHigh: 102.0 },
};

const PEDIATRIC_PULSE_RANGE = {
  criticalLow: 60,
  mildLow: 70,
  mildHigh: 120,
  criticalHigh: 139,
};

export const VITALS_FIELDS_WITH_SEVERITY = [
  'systolic_bp',
  'diastolic_bp',
  'pulse_rate',
  'temperature',
  'spo2_percent',
];

/** Every numeric field VitalsRecord actually has (see backend
 * app/modules/vitals/models.py) — the single source of truth for
 * "which fields does this form/display iterate over", so
 * RecordVitalsForm and ConsultationPanel's read-only display can't
 * drift out of sync with each other or with the backend model. */
export const ALL_VITALS_FIELDS = [
  'systolic_bp',
  'diastolic_bp',
  'pulse_rate',
  'temperature',
  'weight_kg',
  'height_cm',
  'spo2_percent',
];

export const VITAL_FIELD_LABELS = {
  systolic_bp: 'Systolic BP',
  diastolic_bp: 'Diastolic BP',
  pulse_rate: 'Pulse Rate',
  temperature: 'Temperature',
  weight_kg: 'Weight',
  height_cm: 'Height',
  spo2_percent: 'SpO2',
};

// `temperature` here is the going-forward entry-form default (every
// new reading is Fahrenheit) — for rendering a *stored* record, whose
// temperature may be from before this change, use `vitalFieldUnit`
// below instead of this static lookup.
export const VITAL_FIELD_UNITS = {
  systolic_bp: 'mmHg',
  diastolic_bp: 'mmHg',
  pulse_rate: 'bpm',
  temperature: '°F',
  weight_kg: 'kg',
  height_cm: 'cm',
  spo2_percent: '%',
};

const TEMPERATURE_UNIT_SYMBOL = { celsius: '°C', fahrenheit: '°F' };

/** The correct display unit for one field on a *stored* record —
 * identical to `VITAL_FIELD_UNITS[field]` for every field except
 * `temperature`, which resolves from that specific record's own
 * `temperatureUnit` (falling back to the going-forward Fahrenheit
 * default only when `temperatureUnit` is genuinely absent, e.g. a
 * live not-yet-saved form entry with no record at all). Never guess a
 * stored record's unit from context — always pass its real
 * `temperature_unit` here. */
export function vitalFieldUnit(field, temperatureUnit) {
  if (field !== 'temperature') return VITAL_FIELD_UNITS[field];
  return TEMPERATURE_UNIT_SYMBOL[temperatureUnit] ?? VITAL_FIELD_UNITS.temperature;
}

export const SEVERITY_BADGE_VARIANT = {
  normal: 'success',
  mild: 'warning',
  critical: 'destructive',
};

export const SEVERITY_LABEL = {
  normal: 'Normal',
  mild: 'Mild',
  critical: 'Critical',
};

function rangeFor(field, ageYears, temperatureUnit) {
  if (field === 'temperature') {
    return TEMPERATURE_RANGES[temperatureUnit] ?? TEMPERATURE_RANGES.fahrenheit;
  }
  if (field === 'pulse_rate' && typeof ageYears === 'number' && ageYears < PEDIATRIC_AGE_CUTOFF_YEARS) {
    return PEDIATRIC_PULSE_RANGE;
  }
  return ADULT_RANGES[field];
}

/** Classifies one field's value against its reference range. Returns
 * `null` for fields with no established range (weight/height) or when
 * `value` is null/undefined/NaN (nothing entered yet — never treated
 * as "normal", since that would be claiming a measurement that wasn't
 * taken). Otherwise returns 'normal' | 'mild' | 'critical', plus
 * `direction` ('low' | 'high' | null) for building a human message.
 *
 * `temperatureUnit` (2026-08-28 addition) only matters for
 * `field === 'temperature'` — see this file's own top-level docstring.
 * Omit it for a live entry-form value (always Fahrenheit); pass a
 * stored record's own `temperature_unit` when classifying a record
 * that was already saved. */
export function getVitalSeverity(field, value, { ageYears, temperatureUnit } = {}) {
  const range = rangeFor(field, ageYears, temperatureUnit);
  if (!range || value === null || value === undefined || Number.isNaN(value)) {
    return { level: null, direction: null };
  }
  if (value < range.criticalLow) return { level: 'critical', direction: 'low' };
  if (value < range.mildLow) return { level: 'mild', direction: 'low' };
  if (value <= range.mildHigh) return { level: 'normal', direction: null };
  if (value <= range.criticalHigh) return { level: 'mild', direction: 'high' };
  return { level: 'critical', direction: 'high' };
}

/** Runs every severity-tracked field in `values` (a plain
 * {field: number|null|undefined} map, e.g. the vitals form's current
 * values) through `getVitalSeverity` and summarizes the result — used
 * both to decide whether the "quick all-normal" fast path applies and
 * to build the critical-value confirmation prompt's message. Fields
 * that are empty/not entered are excluded from both `hasMild`/
 * `hasCritical` and from `allNormal`'s requirement — "all normal" means
 * every *entered* value is normal, not that every possible field was
 * filled in (vitals capture legitimately records only a subset; see
 * VitalsRecord's own model docstring on the backend).
 *
 * Always the live entry-form's own values — `temperature` here is
 * therefore always Fahrenheit (see this file's own top-level
 * docstring), no `temperatureUnit` needed. */
export function summarizeVitalsSeverity(values, { ageYears } = {}) {
  const entries = VITALS_FIELDS_WITH_SEVERITY.map((field) => {
    const raw = values?.[field];
    const value = raw === '' || raw === undefined || raw === null ? null : Number(raw);
    const { level, direction } = getVitalSeverity(field, value, { ageYears });
    return { field, value, level, direction };
  }).filter((entry) => entry.level !== null);

  const criticalEntries = entries.filter((entry) => entry.level === 'critical');
  const mildEntries = entries.filter((entry) => entry.level === 'mild');

  return {
    entries,
    criticalEntries,
    mildEntries,
    hasCritical: criticalEntries.length > 0,
    hasMild: mildEntries.length > 0,
    hasAnyEntered: entries.length > 0,
    allNormal: entries.length > 0 && criticalEntries.length === 0 && mildEntries.length === 0,
  };
}

/** Human sentence for one out-of-range entry, e.g. "Systolic BP 190
 * mmHg is critically high." — used to build the critical-value
 * confirmation prompt's message from real entered values. Always the
 * live entry form's own values (see `summarizeVitalsSeverity`'s
 * docstring) — `temperature`'s unit is always the going-forward
 * Fahrenheit default here. */
export function describeSeverityEntry({ field, value, level, direction }) {
  const label = VITAL_FIELD_LABELS[field];
  const unit = VITAL_FIELD_UNITS[field];
  const qualifier = level === 'critical' ? 'critically' : 'mildly';
  const directionWord = direction === 'low' ? 'low' : direction === 'high' ? 'high' : 'abnormal';
  return `${label} ${value} ${unit} is ${qualifier} ${directionWord}`;
}

const SEVERITY_RANK = { normal: 0, mild: 1, critical: 2 };

/** The single worst severity level found across a recorded vitals
 * reading's fields (a VitalsRecordOut-shaped object) — used by the
 * doctor's queue/consultation view to show one summary badge per visit
 * rather than five. Returns null when the record is missing or has no
 * severity-tracked field filled in at all, never a fabricated
 * "normal". Classifies `temperature` against *that record's own*
 * `temperature_unit` (2026-08-28 addition) — correct regardless of
 * whether `record` predates this change or not. */
export function getWorstSeverity(record, { ageYears } = {}) {
  if (!record) return null;
  let worst = null;
  for (const field of VITALS_FIELDS_WITH_SEVERITY) {
    const { level } = getVitalSeverity(field, record[field], {
      ageYears,
      temperatureUnit: record.temperature_unit,
    });
    if (level && (worst === null || SEVERITY_RANK[level] > SEVERITY_RANK[worst])) {
      worst = level;
    }
  }
  return worst;
}

const TREND_STABLE_THRESHOLD = {
  systolic_bp: 5,
  diastolic_bp: 5,
  pulse_rate: 5,
  // The going-forward Fahrenheit-vs-Fahrenheit noise threshold — the
  // exact conversion of the old 0.2°C delta (ΔF = ΔC*9/5, no +32
  // offset: converting a *difference* is not the same formula as
  // converting a point value). There is no Celsius-vs-Celsius case
  // left to threshold: `getTrend` below only ever compares the live
  // entry form's value (always Fahrenheit) against a previous record,
  // and returns `null` outright when that previous record is
  // Celsius-tagged rather than applying any threshold across
  // mismatched units.
  temperature: 0.36,
  weight_kg: 0.5,
  height_cm: 0.5,
  spo2_percent: 1,
};

/** Compares a current entered value against the patient's previous
 * reading for the same field. Returns null when either side is
 * missing (nothing to compare — never fabricate a trend from an
 * absent value), otherwise 'up' | 'down' | 'stable' based on a
 * per-field noise threshold (a 1 mmHg difference isn't a meaningful
 * trend; a 15 mmHg one is).
 *
 * `field === 'temperature'` is a special case (2026-08-28 addition):
 * `currentValue` is always Fahrenheit (the live entry form), but
 * `previousValue` may be from a Celsius-tagged historical record —
 * `previousTemperatureUnit` must be passed whenever `field` is
 * `'temperature'` so a mismatched-unit pair returns `null` (a raw
 * numeric diff across two different units is meaningless, never
 * rendered as a real trend) rather than a fabricated arrow. */
export function getTrend(field, currentValue, previousValue, { previousTemperatureUnit } = {}) {
  if (
    currentValue === null ||
    currentValue === undefined ||
    currentValue === '' ||
    previousValue === null ||
    previousValue === undefined
  ) {
    return null;
  }
  if (field === 'temperature' && previousTemperatureUnit === 'celsius') {
    return null;
  }
  const current = Number(currentValue);
  const previous = Number(previousValue);
  if (Number.isNaN(current) || Number.isNaN(previous)) return null;

  const threshold = TREND_STABLE_THRESHOLD[field] ?? 0;
  const diff = current - previous;
  if (Math.abs(diff) <= threshold) return 'stable';
  return diff > 0 ? 'up' : 'down';
}
