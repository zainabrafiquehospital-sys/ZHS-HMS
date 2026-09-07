import { describe, expect, it } from 'vitest';
import {
  autoLinkVisit,
  MEDICINE_BILL_PATIENT_REQUIRED_MESSAGE,
  openVisits,
  resolveMedicineBillLinkage,
} from './patientLinkage';

const visit = (id, status) => ({ id, status, queue_token: `Token #${id}` });

describe('openVisits', () => {
  it('drops completed and cancelled visits, keeps everything still in motion', () => {
    const all = [
      visit('a', 'registered'),
      visit('b', 'waiting_doctor'),
      visit('c', 'completed'),
      visit('d', 'cancelled'),
      visit('e', 'payment_pending'),
    ];
    expect(openVisits(all).map((v) => v.id)).toEqual(['a', 'b', 'e']);
  });

  it('treats null/undefined as an empty list', () => {
    expect(openVisits(null)).toEqual([]);
    expect(openVisits(undefined)).toEqual([]);
  });
});

describe('autoLinkVisit', () => {
  it('auto-links when the patient has exactly one open visit', () => {
    const picked = autoLinkVisit([visit('only', 'waiting_billing'), visit('old', 'completed')]);
    expect(picked?.id).toBe('only');
  });

  it('does NOT auto-link when there are multiple open visits (receptionist must disambiguate)', () => {
    expect(autoLinkVisit([visit('x', 'waiting_doctor'), visit('y', 'registered')])).toBeNull();
  });

  it('does NOT auto-link when the only visits are terminal', () => {
    expect(autoLinkVisit([visit('x', 'completed'), visit('y', 'cancelled')])).toBeNull();
  });

  it('does NOT auto-link when there are no visits at all', () => {
    expect(autoLinkVisit([])).toBeNull();
    expect(autoLinkVisit(undefined)).toBeNull();
  });
});

describe('resolveMedicineBillLinkage', () => {
  it('BLOCKS finalize with a clear error when neither a visit link nor manual details are present', () => {
    const result = resolveMedicineBillLinkage({
      linkMode: 'search',
      selectedVisit: null,
      manualName: '',
      manualAge: '',
      manualPhone: '',
    });
    expect(result.ok).toBe(false);
    expect(result.error).toBe(MEDICINE_BILL_PATIENT_REQUIRED_MESSAGE);
    expect(result.error).toMatch(/Manual Entry/);
  });

  it('allows finalize when a visit is linked, passing its id through and no manual payload', () => {
    const result = resolveMedicineBillLinkage({
      linkMode: 'search',
      selectedVisit: { id: 'visit-123' },
      manualName: '',
      manualAge: '',
      manualPhone: '',
    });
    expect(result).toEqual({ ok: true, visitId: 'visit-123', manualPayload: {} });
  });

  it('allows finalize in Manual Entry mode when all three fields are valid', () => {
    const result = resolveMedicineBillLinkage({
      linkMode: 'manual',
      selectedVisit: null,
      manualName: 'Asiya Bibi',
      manualAge: '34',
      manualPhone: '03001234567',
    });
    expect(result.ok).toBe(true);
    expect(result.visitId).toBeNull();
    expect(result.manualPayload).toEqual({
      manual_patient_name: 'Asiya Bibi',
      manual_patient_age: 34,
      manual_patient_phone: '03001234567',
    });
  });

  it('BLOCKS finalize in Manual Entry mode when a required field is missing (e.g. phone)', () => {
    const result = resolveMedicineBillLinkage({
      linkMode: 'manual',
      selectedVisit: null,
      manualName: 'Asiya Bibi',
      manualAge: '34',
      manualPhone: '',
    });
    expect(result.ok).toBe(false);
    expect(result.error).toMatch(/[Cc]ontact number/);
  });

  it('does not fall through to "anonymous" when Manual Entry is empty — it reports the field error', () => {
    const result = resolveMedicineBillLinkage({
      linkMode: 'manual',
      selectedVisit: null,
      manualName: '',
      manualAge: '',
      manualPhone: '',
    });
    expect(result.ok).toBe(false);
  });
});
