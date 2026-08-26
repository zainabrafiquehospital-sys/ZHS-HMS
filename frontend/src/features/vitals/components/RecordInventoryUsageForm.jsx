'use client';

import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { HeartPulse, X } from 'lucide-react';
import { patientsService } from '@/features/patients/api/patientsService';
import {
  useInventoryItems,
  useInventoryPatientContext,
  useRecordInventoryUsage,
} from '@/features/inventory/hooks/useInventory';
import {
  inventoryManualPatientSchema,
  recordUsageFormSchema,
} from '@/features/inventory/schemas/inventorySchemas';
import { Card, CardContent, CardHeader, CardTitle } from '@/shared/components/ui/Card';
import { Button } from '@/shared/components/ui/Button';
import { Input } from '@/shared/components/ui/Input';
import { Label } from '@/shared/components/ui/Label';
import { Select } from '@/shared/components/ui/Select';
import { Textarea } from '@/shared/components/ui/Textarea';
import { SearchSelect } from '@/shared/components/SearchSelect';
import { PageLoader } from '@/shared/components/PageLoader';
import { PageError } from '@/shared/components/PageError';
import { todayDisplayDayKey } from '@/utils/timezone';

/** The "which patient is this for" panel — patient-linked, not
 * visit-linked (a deliberate departure from Pharmacy's own
 * VisitLinkPanel, confirmed design decision — see backend/app/modules/
 * inventory/models.py's InventoryUsageEntry docstring): this module's
 * own ward/emergency population is exactly the group most likely to
 * have no same-day OPD visit at all, so there is no "then pick one of
 * their visits" second step the way MedicineBillingWorkspace.jsx's
 * VisitLinkPanel has — picking a patient is the whole of it. Once
 * picked, their MR number and most recent registered procedure (if any)
 * show as a read-only preview, purely informational — nothing about the
 * usage entry itself depends on a visit existing. Manual Entry mirrors
 * VisitLinkPanel's identical fallback exactly (same three fields, same
 * "all three together" rule, same "no patient/visit record is looked up
 * or created" framing). */
function PatientLinkPanel({
  mode,
  onModeChange,
  selectedPatient,
  onSelectPatient,
  onClear,
  manualName,
  manualAge,
  manualPhone,
  onManualNameChange,
  onManualAgeChange,
  onManualPhoneChange,
}) {
  const { data: context, isLoading: isLoadingContext } = useInventoryPatientContext(
    selectedPatient?.id,
  );

  if (selectedPatient) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Patient</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-col gap-0.5 text-sm">
            <span className="font-medium text-foreground">
              {selectedPatient.full_name} (MR: {selectedPatient.mr_number})
            </span>
            <span className="text-muted-foreground">
              {isLoadingContext
                ? 'Loading recent visit…'
                : context?.latest_visit
                  ? `Most recent visit: ${context.latest_visit.queue_token} · ${context.latest_visit.procedure}`
                  : 'No registered visit on file for this patient.'}
            </span>
          </div>
          <Button type="button" size="sm" variant="outline" onClick={onClear}>
            <X className="h-4 w-4" />
            Change
          </Button>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Patient</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div className="flex gap-2">
          <Button
            type="button"
            size="sm"
            variant={mode === 'search' ? 'default' : 'outline'}
            onClick={() => onModeChange('search')}
          >
            Search & Link Patient
          </Button>
          <Button
            type="button"
            size="sm"
            variant={mode === 'manual' ? 'default' : 'outline'}
            onClick={() => onModeChange('manual')}
          >
            Manual Entry
          </Button>
        </div>

        {mode === 'manual' ? (
          <div className="flex flex-col gap-4">
            <div className="flex flex-col gap-4 sm:flex-row sm:flex-wrap">
              <div className="flex flex-1 flex-col gap-1.5 sm:min-w-[12rem]">
                <Label htmlFor="usage_manual_patient_name">Name</Label>
                <Input
                  id="usage_manual_patient_name"
                  value={manualName}
                  onChange={(event) => onManualNameChange(event.target.value)}
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="usage_manual_patient_age">Age</Label>
                <Input
                  id="usage_manual_patient_age"
                  type="number"
                  min="0"
                  max="150"
                  className="w-24"
                  value={manualAge}
                  onChange={(event) => onManualAgeChange(event.target.value)}
                />
              </div>
              <div className="flex flex-1 flex-col gap-1.5 sm:min-w-[10rem]">
                <Label htmlFor="usage_manual_patient_phone">Contact Number</Label>
                <Input
                  id="usage_manual_patient_phone"
                  value={manualPhone}
                  onChange={(event) => onManualPhoneChange(event.target.value)}
                />
              </div>
            </div>
            <p className="text-xs text-muted-foreground">
              All three fields are required together — for a patient not yet in the system. No
              patient record is looked up or created.
            </p>
          </div>
        ) : (
          <div className="flex flex-col gap-1.5 sm:max-w-sm">
            <Label>Patient</Label>
            <SearchSelect
              queryKey={['patients', 'search']}
              queryFn={(term) => patientsService.search(term).then((res) => res.data)}
              getLabel={(patient) => patient.full_name}
              getDescription={(patient) => `MR: ${patient.mr_number}`}
              placeholder="Search by name, MR number, phone, or CNIC"
              onSelect={(patient) => onSelectPatient(patient)}
            />
            <p className="text-xs text-muted-foreground">
              Not in the system yet? Switch to Manual Entry above.
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

/** Records an Emergency Stock usage entry against a patient — the only
 * way emergency_stock_level decreases (see backend/app/modules/
 * inventory/service.py's record_usage docstring). Item picker restricted
 * to active items, mirroring the Inventory Manager's own Receive/
 * Transfer pickers. */
export function RecordInventoryUsageForm() {
  const { data: items, isLoading, isError, error, refetch } = useInventoryItems();
  const recordUsage = useRecordInventoryUsage();
  const [linkMode, setLinkMode] = useState('search');
  const [selectedPatient, setSelectedPatient] = useState(null);
  const [manualName, setManualName] = useState('');
  const [manualAge, setManualAge] = useState('');
  const [manualPhone, setManualPhone] = useState('');
  const [submitError, setSubmitError] = useState(null);
  const [successMessage, setSuccessMessage] = useState(null);
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm({
    resolver: zodResolver(recordUsageFormSchema),
    defaultValues: { item_id: '', quantity: '', used_on: todayDisplayDayKey(), reason_note: '' },
  });

  const activeItems = (items ?? []).filter((item) => item.is_active);

  function clearPatientLink() {
    setSelectedPatient(null);
    setManualName('');
    setManualAge('');
    setManualPhone('');
  }

  async function onSubmit(values) {
    setSubmitError(null);
    setSuccessMessage(null);

    let manualPatientPayload = {};
    if (!selectedPatient && linkMode === 'manual') {
      const parsed = inventoryManualPatientSchema.safeParse({
        manual_patient_name: manualName,
        manual_patient_age: manualAge,
        manual_patient_phone: manualPhone,
      });
      if (!parsed.success) {
        setSubmitError('Enter all three manual patient fields, or search for an existing patient.');
        return;
      }
      manualPatientPayload = parsed.data;
    } else if (!selectedPatient) {
      setSubmitError('Select a patient, or switch to Manual Entry.');
      return;
    }

    try {
      await recordUsage.mutateAsync({
        item_id: values.item_id,
        quantity: values.quantity,
        used_on: values.used_on,
        reason_note: values.reason_note || null,
        patient_id: selectedPatient?.id ?? null,
        ...manualPatientPayload,
      });
      setSuccessMessage('Usage entry recorded.');
      reset({ item_id: '', quantity: '', used_on: values.used_on, reason_note: '' });
      clearPatientLink();
    } catch (submitErr) {
      setSubmitError(submitErr.message || 'Unable to record this usage entry.');
    }
  }

  if (isLoading) return <PageLoader label="Loading items" />;
  if (isError) {
    return <PageError error={error} reset={refetch} message="Couldn't load the item catalog." />;
  }

  return (
    <div className="flex flex-col gap-6">
      <PatientLinkPanel
        mode={linkMode}
        onModeChange={setLinkMode}
        selectedPatient={selectedPatient}
        onSelectPatient={setSelectedPatient}
        onClear={clearPatientLink}
        manualName={manualName}
        manualAge={manualAge}
        manualPhone={manualPhone}
        onManualNameChange={setManualName}
        onManualAgeChange={setManualAge}
        onManualPhoneChange={setManualPhone}
      />

      <Card>
        <CardHeader>
          <CardTitle>Record Usage</CardTitle>
        </CardHeader>
        <CardContent>
          {activeItems.length === 0 ? (
            <p className="text-sm text-muted-foreground">No active items available right now.</p>
          ) : (
            <form onSubmit={handleSubmit(onSubmit)} className="flex flex-col gap-4">
              <div className="flex flex-col gap-4 sm:flex-row sm:flex-wrap sm:items-end">
                <div className="flex min-w-[220px] flex-1 flex-col gap-1.5">
                  <Label htmlFor="usage_item_id">Item</Label>
                  <Select id="usage_item_id" {...register('item_id')}>
                    <option value="">Select an item…</option>
                    {activeItems.map((item) => (
                      <option key={item.id} value={item.id}>
                        {item.name} ({item.unit}) — {item.emergency_stock_level} available
                      </option>
                    ))}
                  </Select>
                  {errors.item_id ? (
                    <p className="text-xs text-destructive">{errors.item_id.message}</p>
                  ) : null}
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="usage_quantity">Quantity</Label>
                  <Input
                    id="usage_quantity"
                    type="number"
                    step="0.01"
                    min="0"
                    {...register('quantity')}
                  />
                  {errors.quantity ? (
                    <p className="text-xs text-destructive">{errors.quantity.message}</p>
                  ) : null}
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="usage_used_on">Used On</Label>
                  <Input id="usage_used_on" type="date" {...register('used_on')} />
                  {errors.used_on ? (
                    <p className="text-xs text-destructive">{errors.used_on.message}</p>
                  ) : null}
                </div>
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="usage_reason_note">Reason (optional)</Label>
                <Textarea id="usage_reason_note" {...register('reason_note')} />
              </div>
              <div>
                <Button type="submit" disabled={isSubmitting}>
                  <HeartPulse className="h-4 w-4" />
                  {isSubmitting ? 'Recording…' : 'Record Usage'}
                </Button>
              </div>
            </form>
          )}
          {submitError ? (
            <p className="mt-3 rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
              {submitError}
            </p>
          ) : null}
          {successMessage ? (
            <p className="mt-3 rounded-md bg-emerald-50 px-3 py-2 text-sm text-emerald-700">
              {successMessage}
            </p>
          ) : null}
        </CardContent>
      </Card>
    </div>
  );
}
