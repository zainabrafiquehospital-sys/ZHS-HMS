'use client';

import { useState } from 'react';
import { useForm, Controller } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { registerVisitSchema } from '@/features/reception/schemas/registerVisitSchema';
import { useRegisterVisit, useDoctorsForSelection } from '@/features/reception/hooks/useReception';
import { patientsService } from '@/features/patients/api/patientsService';
import {
  ProcedureItemsEditor,
  procedureItemToRequestPayload,
} from '@/features/visits/components/ProcedureItemsEditor';
import { Button } from '@/shared/components/ui/Button';
import { Input } from '@/shared/components/ui/Input';
import { Label } from '@/shared/components/ui/Label';
import { Select } from '@/shared/components/ui/Select';
import { Textarea } from '@/shared/components/ui/Textarea';
import { Card, CardContent, CardHeader, CardTitle } from '@/shared/components/ui/Card';
import { SearchSelect } from '@/shared/components/SearchSelect';
import { PaymentMethodSelect } from '@/shared/components/PaymentMethodSelect';
import { ReturningPatientDialog } from '@/features/reception/components/ReturningPatientDialog';
import { useToast } from '@/shared/components/toast/ToastProvider';

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
  vitalsRequired: false,
  doctorUserId: '',
  discountAmount: '',
  discountReason: '',
  paymentMethod: '',
  advanceAmount: '',
};

// `netAmount`/`isPartialPayment` (2026-08-22 addition) come from the
// component's own live computation, not registered form fields — same
// "plain local state feeding the payload" shape `procedureItems`/
// `applyDiscount` already use. Unticked (the common case): the full net
// total is sent as `initial_payment_amount`, mirroring the Medicine
// Bill "Advance Received" field's own auto-fill-to-full-total default
// (see MedicineBillingWorkspace.jsx) — just without a freely-editable
// input at all in this case, since there is nothing to edit. Ticked:
// the receptionist's own typed `advanceAmount` is sent instead.
function buildPayload(values, applyDiscount, procedureItems, netAmount, isPartialPayment) {
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
    procedures: procedureItems.map(procedureItemToRequestPayload),
    vitals_required: values.vitalsRequired,
    // Blank (the default) leaves the field out of the payload as
    // `null` — auto-assignment, exactly today's behavior. A selection
    // sends that doctor's id and bypasses it server-side (see
    // ReceptionService.register_visit's own docstring).
    doctor_user_id: values.doctorUserId || null,
    // Belt-and-suspenders with handleApplyDiscountToggle's own
    // clearing (below): even if a stale value somehow survived, an
    // unticked checkbox always sends no discount at all.
    discount_amount: applyDiscount ? values.discountAmount : 0,
    discount_reason: applyDiscount ? values.discountReason || null : null,
    initial_payment_amount: isPartialPayment ? values.advanceAmount : netAmount,
    initial_payment_method: values.paymentMethod,
  };
}

export function RegisterVisitForm({ onRegistered }) {
  const { toast } = useToast();
  const registerVisit = useRegisterVisit();
  const { doctors } = useDoctorsForSelection();
  const onlineDoctors = doctors.filter((doctor) => doctor.is_online);
  const offlineDoctors = doctors.filter((doctor) => !doctor.is_online);
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
  // Captured once so its own `onBlur` can be composed with the
  // returning-patient lookup below, rather than spread inline —
  // spreading `register(...)` directly onto the Input would only let
  // one of the two onBlur behaviors survive.
  const phoneNumberField = register('newPatient.phone_number');

  // Returning-patient detection (New Patient mode only) — fires on the
  // phone number field's own blur (see the `onBlur` wired onto that
  // Input below), never on every keystroke like SearchSelect's own
  // fuzzy autocomplete does elsewhere in this same form: this is a
  // one-shot "does this exact, now-complete number already belong to
  // someone" check, not an open-ended search. `phoneMatches` is `null`
  // when the dialog is closed, otherwise the array ReturningPatientDialog
  // renders (one row, or several for family members sharing a number —
  // see that component's own docstring). `dismissedPhoneNumbers` is
  // plain in-memory state, not persisted anywhere — "no further prompt
  // for this number this session" means exactly the lifetime of this
  // mounted form, cleared again after a full page reload, matching the
  // scope the task asked for (never a cross-session suppression, which
  // would risk hiding a real match from a *different* receptionist
  // later reusing the same browser).
  const [phoneMatches, setPhoneMatches] = useState(null);
  const [dismissedPhoneNumbers, setDismissedPhoneNumbers] = useState(() => new Set());

  async function handlePhoneNumberBlur() {
    if (patientMode !== 'new') return;
    const phone = watch('newPatient.phone_number')?.trim();
    // Matches registerVisitSchema's own `min_length` floor for this
    // field (see that schema) — never fires a lookup against an
    // obviously-incomplete number still being typed.
    if (!phone || phone.length < 6 || dismissedPhoneNumbers.has(phone)) return;
    try {
      const res = await patientsService.findByPhoneNumber(phone);
      if (res.data.length > 0) {
        setPhoneMatches(res.data);
      }
    } catch {
      // A failed lookup must never block registration — the receptionist
      // can still register as a new patient exactly as if this feature
      // didn't exist; no toast/error surfaced for a background check.
    }
  }

  function handleUseExistingPatient(patient) {
    setValue('patientMode', 'existing');
    setValue('existingPatientId', patient.id, { shouldValidate: true });
    setValue('existingPatientLabel', `${patient.full_name} (${patient.mr_number})`);
    setPhoneMatches(null);
  }

  function handleDismissPhoneMatches() {
    const phone = watch('newPatient.phone_number')?.trim();
    if (phone) {
      setDismissedPhoneNumbers((previous) => new Set(previous).add(phone));
    }
    setPhoneMatches(null);
  }

  // The itemized procedure breakdown (2026-08-21 addition, replacing
  // the old flat procedure/amount fields) — plain local state, not a
  // registered form field, the same way `applyDiscount` right below
  // already is; see ProcedureItemsEditor.jsx's own docstring for the
  // full shape/rationale.
  const [procedureItems, setProcedureItems] = useState([]);
  const [procedureItemsError, setProcedureItemsError] = useState(null);
  // Mirrors MedicineBillingWorkspace.jsx's "Apply Discount" checkbox
  // exactly (2026-08-19 addition): unticked, the two discount fields
  // stay hidden and no discount is ever sent, regardless of any stale
  // value typed before unticking (see handleApplyDiscountToggle below).
  const [applyDiscount, setApplyDiscount] = useState(false);
  const watchedDiscount = watch('discountAmount');
  const procedureItemsTotal = procedureItems.reduce(
    (sum, item) => sum + Number(item.amount || 0),
    0,
  );
  const netAmountPreview = procedureItemsTotal - (applyDiscount ? Number(watchedDiscount || 0) : 0);

  function handleApplyDiscountToggle(checked) {
    setApplyDiscount(checked);
    if (!checked) {
      setValue('discountAmount', '');
      setValue('discountReason', '');
    }
  }

  // "Partial Payment" (2026-08-22 addition) — mirrors the "Apply
  // Discount" checkbox's exact toggle shape immediately above: unticked
  // (the common case), no Advance Amount field is shown at all and the
  // full net total is sent as the registration's collected payment —
  // there is nothing to type, unlike MedicineBillingWorkspace.jsx's
  // continuously-editable "Advance Received" field, which this
  // deliberately does not mirror literally (see this form's own
  // Payment Method field below, always visible, since some payment —
  // full or partial — is always collected at registration). Ticked, an
  // Advance Amount input appears, validated against the live net total
  // preview (see onSubmit below) rather than the zod schema, the same
  // "cross-field validation happens against a live-computed total, not
  // in the schema" convention discountAmount already follows here.
  const [isPartialPayment, setIsPartialPayment] = useState(false);
  const [advanceAmountError, setAdvanceAmountError] = useState(null);

  function handlePartialPaymentToggle(checked) {
    setIsPartialPayment(checked);
    setAdvanceAmountError(null);
    if (!checked) {
      setValue('advanceAmount', '');
    }
  }

  async function onSubmit(values) {
    setProcedureItemsError(null);
    setAdvanceAmountError(null);
    if (procedureItems.length === 0) {
      setProcedureItemsError('Add at least one procedure.');
      return;
    }
    if (isPartialPayment) {
      const advance = Number(values.advanceAmount);
      if (!Number.isFinite(advance) || advance <= 0 || advance > netAmountPreview) {
        setAdvanceAmountError(
          `Enter an amount greater than 0 and up to ${netAmountPreview.toFixed(2)}.`,
        );
        return;
      }
    }
    try {
      const response = await registerVisit.mutateAsync(
        buildPayload(values, applyDiscount, procedureItems, netAmountPreview, isPartialPayment),
      );
      reset(DEFAULT_VALUES);
      setProcedureItems([]);
      setApplyDiscount(false);
      setIsPartialPayment(false);
      onRegistered?.(response.data);
      // RegistrationSummary (rendered by the parent via onRegistered)
      // stays as the persistent, referenceable receipt-like panel —
      // this toast is just the transient "it worked" acknowledgment,
      // the two aren't redundant (Part 1's own inline-vs-toast audit).
      toast.success({
        title: 'Visit registered',
        description: `Queue token ${response.data.visit.queue_token}`,
      });
    } catch (error) {
      toast.error({
        title: 'Unable to register this visit',
        description: error.message,
        onRetry: () => onSubmit(values),
      });
    }
  }

  return (
    <>
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
                    <Input
                      id="phone_number"
                      {...phoneNumberField}
                      onBlur={(event) => {
                        // Compose RHF's own onBlur (validation/touched
                        // tracking) with the returning-patient lookup —
                        // both must run, so this is wired explicitly
                        // rather than trusting register()'s own
                        // `onBlur` option to be called internally,
                        // which isn't guaranteed across RHF versions.
                        phoneNumberField.onBlur(event);
                        handlePhoneNumberBlur();
                      }}
                    />
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

            {/* Itemized procedures (2026-08-21 addition, replacing the old
              flat Procedure/Amount fields) — catalog search + manual
              fallback, one or more line items, each with its own price;
              see ProcedureItemsEditor.jsx's own docstring. */}
            <div className="flex flex-col gap-1.5">
              <Label>Procedures</Label>
              <ProcedureItemsEditor items={procedureItems} onChange={setProcedureItems} />
              {procedureItemsError ? (
                <p className="text-xs text-destructive">{procedureItemsError}</p>
              ) : null}
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

            {/* Optional doctor selection (2026-08-24 addition) — blank
              (the default, first/highlighted option) preserves exactly
              today's behavior: auto-assign the least-busy online
              doctor, or leave unassigned if none is online (see
              ReceptionService.register_visit's own docstring).
              Online doctors group first, so the common case (picking
              among whoever is on duty right now) never requires
              scrolling — but every consultation-capable doctor is
              still reachable via the "Offline" group below it, so
              Reception is never blocked from routing to a specific
              doctor just because they're temporarily logged out. */}
            <div className="flex flex-col gap-1.5 sm:w-72">
              <Label htmlFor="doctorUserId">Assign to Doctor (optional)</Label>
              <Select id="doctorUserId" defaultValue="" {...register('doctorUserId')}>
                <option value="">Auto-assign (recommended)</option>
                {onlineDoctors.length > 0 ? (
                  <optgroup label="Online">
                    {onlineDoctors.map((doctor) => (
                      <option key={doctor.id} value={doctor.id}>
                        {doctor.full_name}
                      </option>
                    ))}
                  </optgroup>
                ) : null}
                {offlineDoctors.length > 0 ? (
                  <optgroup label="Offline">
                    {offlineDoctors.map((doctor) => (
                      <option key={doctor.id} value={doctor.id}>
                        {doctor.full_name} (Offline)
                      </option>
                    ))}
                  </optgroup>
                ) : null}
              </Select>
              {errors.doctorUserId ? (
                <p className="text-xs text-destructive">{errors.doctorUserId.message}</p>
              ) : null}
            </div>

            {/* Optional flat discount off the procedures' combined total
              (2026-08-19 addition) — same toggle shape as the "Vitals
              required" checkbox above: unticked, no discount fields show
              and none is applied; ticked, it reveals the amount +
              optional reason and a live Net Amount preview. Flows
              through to Billing's Generate Invoice prefill and every
              revenue figure automatically — see VisitService.
              register_visit's own docstring — since the Visit's stored
              `amount` ends up already post-discount. Plain local state,
              not a registered form field — mirrors
              MedicineBillingWorkspace.jsx's own applyDiscount toggle. */}
            <label className="flex items-center gap-2 text-sm text-foreground">
              <input
                type="checkbox"
                className="h-4 w-4 rounded border-input"
                checked={applyDiscount}
                onChange={(event) => handleApplyDiscountToggle(event.target.checked)}
              />
              Apply Discount
            </label>
            {applyDiscount ? (
              <>
                <div className="flex flex-col gap-4 rounded-md border border-dashed border-border p-3 sm:flex-row sm:flex-wrap">
                  <div className="flex flex-col gap-1.5 sm:w-40">
                    <Label htmlFor="discountAmount">Discount (Rs.)</Label>
                    <Input
                      id="discountAmount"
                      type="number"
                      step="0.01"
                      placeholder="0.00"
                      {...register('discountAmount')}
                    />
                    {errors.discountAmount ? (
                      <p className="text-xs text-destructive">{errors.discountAmount.message}</p>
                    ) : null}
                  </div>
                  <div className="flex flex-1 flex-col gap-1.5 sm:min-w-[12rem]">
                    <Label htmlFor="discountReason">Discount Reason (optional)</Label>
                    <Input
                      id="discountReason"
                      placeholder="e.g. Referral, staff discount"
                      {...register('discountReason')}
                    />
                  </div>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-sm font-semibold text-foreground">Net Amount</span>
                  <span className="text-lg font-bold tabular-nums text-foreground">
                    {Number.isFinite(netAmountPreview) ? netAmountPreview.toFixed(2) : '0.00'}
                  </span>
                </div>
              </>
            ) : null}

            {/* Registration-charge payment (2026-08-22 addition) — a real
              payment (full or partial) is always collected at
              registration, so Payment Method is always visible, unlike
              the discount fields above. Unticked "Partial Payment" (the
              common case): no Advance Amount field at all, the full net
              total above is what gets collected. Ticked: reveals the
              Advance Amount input, validated against the live net total
              (see onSubmit). */}
            <label className="flex items-center gap-2 text-sm text-foreground">
              <input
                type="checkbox"
                className="h-4 w-4 rounded border-input"
                checked={isPartialPayment}
                onChange={(event) => handlePartialPaymentToggle(event.target.checked)}
              />
              Partial Payment
            </label>
            {isPartialPayment ? (
              <div className="flex flex-col gap-1.5 sm:w-48">
                <Label htmlFor="advanceAmount">Advance Amount (Rs.)</Label>
                <Input
                  id="advanceAmount"
                  type="number"
                  step="0.01"
                  placeholder="0.00"
                  {...register('advanceAmount')}
                />
                {advanceAmountError ? (
                  <p className="text-xs text-destructive">{advanceAmountError}</p>
                ) : null}
              </div>
            ) : null}
            <div className="sm:w-56">
              <PaymentMethodSelect
                id="paymentMethod"
                registration={register('paymentMethod')}
                error={errors.paymentMethod}
              />
            </div>

            <Button type="submit" disabled={isSubmitting} className="w-full sm:w-auto">
              {isSubmitting ? 'Registering…' : 'Register Visit'}
            </Button>
          </form>
        </CardContent>
      </Card>
      <ReturningPatientDialog
        matches={phoneMatches}
        onUseExisting={handleUseExistingPatient}
        onDismiss={handleDismissPhoneMatches}
      />
    </>
  );
}
