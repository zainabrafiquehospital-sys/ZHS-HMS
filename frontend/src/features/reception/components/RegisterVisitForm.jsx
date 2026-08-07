'use client';

import { useState } from 'react';
import { useForm, Controller } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { registerVisitSchema } from '@/features/reception/schemas/registerVisitSchema';
import { useRegisterVisit } from '@/features/reception/hooks/useReception';
import { patientsService } from '@/features/patients/api/patientsService';
import { Button } from '@/shared/components/ui/Button';
import { Input } from '@/shared/components/ui/Input';
import { Label } from '@/shared/components/ui/Label';
import { Select } from '@/shared/components/ui/Select';
import { Textarea } from '@/shared/components/ui/Textarea';
import { Card, CardContent, CardHeader, CardTitle } from '@/shared/components/ui/Card';
import { SearchSelect } from '@/shared/components/SearchSelect';

const DEFAULT_VALUES = {
  patientMode: 'new',
  existingPatientId: '',
  existingPatientLabel: '',
  newPatient: {
    full_name: '',
    guardian_name: '',
    gender: '',
    age_years: '',
    phone_number: '',
    cnic: '',
    address: '',
  },
  procedure: '',
  amount: '',
  vitalsRequired: false,
};

function buildPayload(values) {
  const isNew = values.patientMode === 'new';
  return {
    patient_id: isNew ? null : values.existingPatientId,
    new_patient: isNew
      ? {
          full_name: values.newPatient.full_name,
          guardian_name: values.newPatient.guardian_name || null,
          gender: values.newPatient.gender || null,
          age_years: Number(values.newPatient.age_years),
          phone_number: values.newPatient.phone_number,
          cnic: values.newPatient.cnic || null,
          address: values.newPatient.address || null,
        }
      : null,
    procedure: values.procedure,
    amount: Number(values.amount),
    vitals_required: values.vitalsRequired,
  };
}

export function RegisterVisitForm({ onRegistered }) {
  const [submitError, setSubmitError] = useState(null);
  const registerVisit = useRegisterVisit();
  const {
    register,
    handleSubmit,
    control,
    watch,
    setValue,
    reset,
    formState: { errors, isSubmitting },
  } = useForm({
    resolver: zodResolver(registerVisitSchema),
    defaultValues: DEFAULT_VALUES,
  });

  const patientMode = watch('patientMode');
  const existingPatientLabel = watch('existingPatientLabel');

  async function onSubmit(values) {
    setSubmitError(null);
    try {
      const response = await registerVisit.mutateAsync(buildPayload(values));
      reset(DEFAULT_VALUES);
      onRegistered?.(response.data);
    } catch (error) {
      setSubmitError(error.message || 'Unable to register this visit.');
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Register Visit</CardTitle>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit(onSubmit)} className="flex flex-col gap-5">
          <div className="flex gap-2">
            <Button
              type="button"
              size="sm"
              variant={patientMode === 'new' ? 'default' : 'outline'}
              onClick={() => setValue('patientMode', 'new')}
            >
              New Patient
            </Button>
            <Button
              type="button"
              size="sm"
              variant={patientMode === 'existing' ? 'default' : 'outline'}
              onClick={() => setValue('patientMode', 'existing')}
            >
              Existing Patient
            </Button>
          </div>

          {patientMode === 'existing' ? (
            <div className="flex flex-col gap-1.5">
              <Label>Find Patient</Label>
              <SearchSelect
                queryKey={['patients', 'search']}
                queryFn={(term) => patientsService.search(term).then((res) => res.data)}
                getLabel={(patient) => patient.full_name}
                getDescription={(patient) => `MR: ${patient.mr_number}`}
                placeholder="Search by name, MR number, phone, or CNIC"
                selectedLabel={existingPatientLabel}
                onSelect={(patient) => {
                  setValue('existingPatientId', patient.id, { shouldValidate: true });
                  setValue('existingPatientLabel', `${patient.full_name} (${patient.mr_number})`);
                }}
              />
              {existingPatientLabel ? (
                <p className="text-xs text-muted-foreground">Selected: {existingPatientLabel}</p>
              ) : null}
              {errors.existingPatientId ? (
                <p className="text-xs text-destructive">{errors.existingPatientId.message}</p>
              ) : null}
            </div>
          ) : (
            <>
              {/* Only these three fields are required to register a new
                  patient — kept together, first, and un-collapsed so a
                  receptionist can register in a handful of keystrokes. */}
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="full_name">Patient Name</Label>
                  <Input id="full_name" autoFocus {...register('newPatient.full_name')} />
                  {errors.newPatient?.full_name ? (
                    <p className="text-xs text-destructive">
                      {errors.newPatient.full_name.message}
                    </p>
                  ) : null}
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="age_years">Age (years)</Label>
                  <Input
                    id="age_years"
                    type="number"
                    min="0"
                    max="150"
                    {...register('newPatient.age_years')}
                  />
                  {errors.newPatient?.age_years ? (
                    <p className="text-xs text-destructive">
                      {errors.newPatient.age_years.message}
                    </p>
                  ) : null}
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="phone_number">Phone Number</Label>
                  <Input id="phone_number" {...register('newPatient.phone_number')} />
                  {errors.newPatient?.phone_number ? (
                    <p className="text-xs text-destructive">
                      {errors.newPatient.phone_number.message}
                    </p>
                  ) : null}
                </div>
              </div>

              {/* Never removed from the system, just optional — collapsed
                  by default so they never slow down the common case. */}
              <details className="rounded-md border border-border">
                <summary className="cursor-pointer select-none px-3 py-2 text-sm font-medium text-muted-foreground">
                  More details (optional)
                </summary>
                <div className="grid grid-cols-1 gap-4 border-t border-border p-3 sm:grid-cols-2">
                  <div className="flex flex-col gap-1.5">
                    <Label htmlFor="guardian_name">Guardian / Husband Name</Label>
                    <Input id="guardian_name" {...register('newPatient.guardian_name')} />
                  </div>
                  <div className="flex flex-col gap-1.5">
                    <Label htmlFor="gender">Gender</Label>
                    <Select id="gender" {...register('newPatient.gender')}>
                      <option value="">Not specified</option>
                      <option value="female">Female</option>
                      <option value="male">Male</option>
                      <option value="other">Other</option>
                    </Select>
                  </div>
                  <div className="flex flex-col gap-1.5">
                    <Label htmlFor="cnic">CNIC</Label>
                    <Input id="cnic" {...register('newPatient.cnic')} />
                  </div>
                  <div className="flex flex-col gap-1.5 sm:col-span-2">
                    <Label htmlFor="address">Address</Label>
                    <Textarea id="address" {...register('newPatient.address')} />
                  </div>
                </div>
              </details>
            </>
          )}

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="procedure">Procedure</Label>
              <Input
                id="procedure"
                placeholder="e.g. Consultation, Follow-up, Normal Delivery"
                {...register('procedure')}
              />
              {errors.procedure ? (
                <p className="text-xs text-destructive">{errors.procedure.message}</p>
              ) : null}
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="amount">Amount</Label>
              <Input id="amount" type="number" min="0" step="0.01" {...register('amount')} />
              {errors.amount ? (
                <p className="text-xs text-destructive">{errors.amount.message}</p>
              ) : null}
            </div>
          </div>

          <Controller
            control={control}
            name="vitalsRequired"
            render={({ field }) => (
              <label className="flex items-center gap-2 text-sm text-foreground">
                <input
                  type="checkbox"
                  className="h-4 w-4 rounded border-input"
                  checked={field.value}
                  onChange={(event) => field.onChange(event.target.checked)}
                />
                Vitals required before doctor
              </label>
            )}
          />

          {submitError ? (
            <p className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
              {submitError}
            </p>
          ) : null}

          <Button type="submit" disabled={isSubmitting} className="w-full sm:w-auto">
            {isSubmitting ? 'Registering…' : 'Register Visit'}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
