import { describe, expect, it } from 'vitest';
import { LAB_BILL_PATIENT_REQUIRED_MESSAGE, resolveLabBillLinkage } from './patientLinkage';

describe('resolveLabBillLinkage', () => {
  it('BLOCKS finalize with a clear error when neither a linked patient nor manual details are present', () => {
    const result = resolveLabBillLinkage({
      linkMode: 'search',
      selectedPatient: null,
      manualName: '',
      manualAge: '',
      manualPhone: '',
    });
    expect(result.ok).toBe(false);
    expect(result.error).toBe(LAB_BILL_PATIENT_REQUIRED_MESSAGE);
    expect(result.error).toMatch(/Manual Entry/);
  });

  it('allows finalize when a patient is linked, passing its id through and no manual payload', () => {
    const result = resolveLabBillLinkage({
      linkMode: 'search',
      selectedPatient: { id: 'patient-123', full_name: 'Rukhsana' },
      manualName: '',
      manualAge: '',
      manualPhone: '',
    });
    expect(result).toEqual({ ok: true, patientId: 'patient-123', manualPayload: {} });
  });

  it('allows finalize in Manual Entry mode when all three fields are valid', () => {
    const result = resolveLabBillLinkage({
      linkMode: 'manual',
      selectedPatient: null,
      manualName: 'Rukhsana',
      manualAge: '25',
      manualPhone: '03244695906',
    });
    expect(result.ok).toBe(true);
    expect(result.patientId).toBeNull();
    expect(result.manualPayload).toEqual({
      manual_patient_name: 'Rukhsana',
      manual_patient_age: 25,
      manual_patient_phone: '03244695906',
    });
  });

  it('BLOCKS finalize in Manual Entry mode when a required field is missing (e.g. name)', () => {
    const result = resolveLabBillLinkage({
      linkMode: 'manual',
      selectedPatient: null,
      manualName: '',
      manualAge: '25',
      manualPhone: '03244695906',
    });
    expect(result.ok).toBe(false);
    expect(result.error).toMatch(/[Nn]ame is required/);
  });

  it('ignores a stale selectedPatient while in Manual Entry mode (mode is the source of truth)', () => {
    const result = resolveLabBillLinkage({
      linkMode: 'manual',
      selectedPatient: { id: 'stale', full_name: 'Someone' },
      manualName: 'Rukhsana',
      manualAge: '25',
      manualPhone: '03244695906',
    });
    expect(result.ok).toBe(true);
    expect(result.patientId).toBeNull();
  });
});
