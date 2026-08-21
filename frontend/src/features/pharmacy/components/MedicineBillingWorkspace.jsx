'use client';

import { useEffect, useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { Plus, Trash2, PackagePlus, X } from 'lucide-react';
import { pharmacyService } from '@/features/pharmacy/api/pharmacyService';
import { patientsService } from '@/features/patients/api/patientsService';
import {
  useCreateMedicineBill,
  usePrintMedicineBill,
  useVisitsForPatient,
} from '@/features/pharmacy/hooks/usePharmacy';
import {
  billLineItemSchema,
  finalizeBillSchema,
  manualPatientSchema,
} from '@/features/pharmacy/schemas/pharmacySchemas';
import { VisitProcedureDisplay } from '@/features/visits/components/VisitProcedureDisplay';
import { Card, CardContent, CardHeader, CardTitle } from '@/shared/components/ui/Card';
import { Button } from '@/shared/components/ui/Button';
import { Input } from '@/shared/components/ui/Input';
import { Label } from '@/shared/components/ui/Label';
import { Badge } from '@/shared/components/ui/Badge';
import { SearchSelect } from '@/shared/components/SearchSelect';
import { PaymentMethodSelect } from '@/shared/components/PaymentMethodSelect';
import { useToast } from '@/shared/components/toast/ToastProvider';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/shared/components/ui/Table';
import { formatDisplayDate, formatDisplayTime, displayDayKey } from '@/utils/timezone';
import { VISIT_STATUS_BADGE_VARIANT } from '@/shared/constants/visitStatus';

function money(amount) {
  return `Rs. ${Number(amount).toFixed(2)}`;
}

/** The optional "attach patient details to this bill" panel — three
 * mutually exclusive states, mirroring app/modules/pharmacy/models.py's
 * `MedicineBill` docstring exactly: a linked registered Visit (search
 * a patient — same SearchSelect + patientsService.search pattern as
 * RegisterVisitForm.jsx — then pick one of their visits), Manual Entry
 * (name/age/contact typed in for the slip only, no Patient/Visit
 * looked up or created), or neither (an anonymous walk-in, unchanged).
 * The two toggle buttons mirror RegisterVisitForm.jsx's own New
 * Patient/Existing Patient mode switch. */
function VisitLinkPanel({
  mode,
  onModeChange,
  selectedPatient,
  selectedVisit,
  onSelectPatient,
  onSelectVisit,
  onClear,
  manualName,
  manualAge,
  manualPhone,
  onManualNameChange,
  onManualAgeChange,
  onManualPhoneChange,
}) {
  const { data: visits, isLoading } = useVisitsForPatient(selectedPatient?.id);

  if (selectedVisit) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Linked Visit</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-col gap-0.5 text-sm">
            <span className="font-medium text-foreground">
              {selectedPatient.full_name} (MR: {selectedPatient.mr_number})
            </span>
            <span className="text-muted-foreground">
              Queue Token <span className="font-mono">{selectedVisit.queue_token}</span> ·{' '}
              {selectedVisit.procedure} ·{' '}
              {formatDisplayDate(displayDayKey(selectedVisit.created_at))} at{' '}
              {formatDisplayTime(selectedVisit.created_at)}
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
        <CardTitle>Link to Visit (Optional)</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div className="flex gap-2">
          <Button
            type="button"
            size="sm"
            variant={mode === 'search' ? 'default' : 'outline'}
            onClick={() => onModeChange('search')}
          >
            Search & Link Visit
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
                <Label htmlFor="manual_patient_name">Name</Label>
                <Input
                  id="manual_patient_name"
                  value={manualName}
                  onChange={(event) => onManualNameChange(event.target.value)}
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="manual_patient_age">Age</Label>
                <Input
                  id="manual_patient_age"
                  type="number"
                  min="0"
                  max="150"
                  className="w-24"
                  value={manualAge}
                  onChange={(event) => onManualAgeChange(event.target.value)}
                />
              </div>
              <div className="flex flex-1 flex-col gap-1.5 sm:min-w-[10rem]">
                <Label htmlFor="manual_patient_phone">Contact Number</Label>
                <Input
                  id="manual_patient_phone"
                  value={manualPhone}
                  onChange={(event) => onManualPhoneChange(event.target.value)}
                />
              </div>
            </div>
            <p className="text-xs text-muted-foreground">
              All three fields are required together. Shown on the printed slip only — no patient
              or visit record is looked up or created.
            </p>
          </div>
        ) : (
          <>
            <div className="flex flex-col gap-1.5 sm:max-w-sm">
              <Label>Patient</Label>
              <SearchSelect
                queryKey={['patients', 'search']}
                queryFn={(term) => patientsService.search(term).then((res) => res.data)}
                getLabel={(patient) => patient.full_name}
                getDescription={(patient) => `MR: ${patient.mr_number}`}
                placeholder="Search by name, MR number, phone, or CNIC"
                selectedLabel={selectedPatient ? `${selectedPatient.full_name}` : ''}
                onSelect={(patient) => onSelectPatient(patient)}
              />
              {selectedPatient ? (
                <p className="text-xs text-muted-foreground">Selected: {selectedPatient.full_name}</p>
              ) : (
                <p className="text-xs text-muted-foreground">
                  Leave unselected to bill this as a walk-in sale.
                </p>
              )}
            </div>

            {selectedPatient ? (
              isLoading ? (
                <p className="text-sm text-muted-foreground">Loading visits…</p>
              ) : (visits ?? []).length === 0 ? (
                <p className="text-sm text-muted-foreground">No visits found for this patient.</p>
              ) : (
                <ul className="flex flex-col gap-2">
                  {visits.map((visit) => (
                    <li key={visit.id}>
                      <button
                        type="button"
                        onClick={() => onSelectVisit(visit)}
                        className="flex w-full flex-wrap items-center justify-between gap-2 rounded-md border border-border px-3 py-2 text-left text-sm hover:bg-muted"
                      >
                        <span className="flex items-center gap-2">
                          <span className="font-mono font-medium text-foreground">
                            {visit.queue_token}
                          </span>
                          <VisitProcedureDisplay
                            visit={visit}
                            className="text-muted-foreground"
                          />
                          <Badge
                            variant={VISIT_STATUS_BADGE_VARIANT[visit.status] ?? 'outline'}
                            className="capitalize"
                          >
                            {visit.status.replaceAll('_', ' ')}
                          </Badge>
                        </span>
                        <span className="text-xs text-muted-foreground">
                          {formatDisplayDate(displayDayKey(visit.created_at))} at{' '}
                          {formatDisplayTime(visit.created_at)}
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              )
            ) : null}
          </>
        )}
      </CardContent>
    </Card>
  );
}

/** The receptionist's medicine-sale counter: search the active price
 * list, add one or more line items to a running local bill, then
 * finalize — a single step that posts the whole bill AND an optional
 * "Advance Received" payment together in one call (see
 * app/modules/pharmacy/service.py's `create_bill`'s
 * `initial_payment_amount`, atomically recorded alongside creation,
 * never a separate later request), then prints the slip. Advance
 * Received defaults to the full Net Total once items are added
 * (2026-08-21 fix — payment is normally collected in full before the
 * slip is printed) but stays freely editable for a genuine partial
 * payment, or clearable to still create the bill `UNPAID`, exactly as
 * a blank/zero amount always has.
 *
 * Recording an *additional* payment later, toward whatever's still
 * Pending on an already-created bill, now lives in Admin Overview's
 * Medicine Bills tab — this workspace is only ever the point of a new
 * sale, not a lookup for an old one.
 *
 * Linking to a registered Visit is optional (see `VisitLinkPanel`
 * above) — when no patient/visit is picked, `visit_id` stays null and
 * the bill is a standalone walk-in sale, exactly as before. Manual
 * Entry (also via `VisitLinkPanel`) is the third, mutually exclusive
 * alternative: a name/age/contact typed in for the slip with no
 * Patient/Visit lookup or creation at all — see
 * app/modules/pharmacy/models.py's `MedicineBill` docstring for the
 * full three-state rule, enforced server-side (never trust the client
 * alone for a data-integrity invariant like this one).
 *
 * "Apply Discount" (2026-08-19 addition) is an optional flat discount,
 * off entirely by default — same toggle shape as RegisterVisitForm.jsx's
 * "Vitals required" checkbox. Ticking it reveals a Discount amount and
 * an optional (never required, unlike Billing's own Invoice discount)
 * reason, and a live Net Total preview computed client-side purely for
 * display; the actual authoritative total is always computed server-side
 * (see PharmacyService.create_bill's docstring) and is what the printed
 * slip and every stored figure reflect. */
export function MedicineBillingWorkspace() {
  const { toast } = useToast();
  const [selectedMedicine, setSelectedMedicine] = useState(null);
  const [quantity, setQuantity] = useState('1');
  const [quantityError, setQuantityError] = useState(null);
  const [items, setItems] = useState([]);
  const [finalizeError, setFinalizeError] = useState(null);
  const [selectedPatient, setSelectedPatient] = useState(null);
  const [selectedVisit, setSelectedVisit] = useState(null);
  const [linkMode, setLinkMode] = useState('search');
  const [manualName, setManualName] = useState('');
  const [manualAge, setManualAge] = useState('');
  const [manualPhone, setManualPhone] = useState('');
  // Mirrors RegisterVisitForm.jsx's vitalsRequired checkbox shape
  // exactly: unticked, the two discount fields stay hidden and no
  // discount is ever sent, regardless of any stale value a receptionist
  // typed before unticking (see handleFinalize below).
  const [applyDiscount, setApplyDiscount] = useState(false);

  const createBill = useCreateMedicineBill();
  const printBill = usePrintMedicineBill();
  const {
    register,
    handleSubmit,
    watch,
    setValue,
    reset: resetFinalizeForm,
    formState: { errors: finalizeErrors, dirtyFields },
  } = useForm({
    resolver: zodResolver(finalizeBillSchema),
    defaultValues: {
      initial_payment_amount: '',
      initial_payment_method: '',
      discount_amount: '',
      discount_reason: '',
    },
  });

  const grandTotal = items.reduce((sum, item) => sum + Number(item.unit_price) * item.quantity, 0);
  const watchedDiscount = watch('discount_amount');
  const discountForPreview = applyDiscount && watchedDiscount ? Number(watchedDiscount) : 0;
  const netTotal = grandTotal - (Number.isFinite(discountForPreview) ? discountForPreview : 0);

  // Advance Received defaults to the full Net Total (2026-08-21 fix) —
  // payment is always collected before the slip is printed, so a
  // normal full-payment bill (the common case) should be Received/Paid
  // without the receptionist retyping the total. `setValue` here never
  // passes `shouldDirty`, so this keeps auto-syncing to the Net Total
  // as items/discount change right up until the receptionist actually
  // types into the field themselves — at that point `dirtyFields`
  // flips true (their value differs from the original `''` default)
  // and this effect backs off, leaving a genuine partial payment alone.
  useEffect(() => {
    if (items.length > 0 && !dirtyFields.initial_payment_amount) {
      setValue('initial_payment_amount', netTotal);
    }
  }, [netTotal, items.length, dirtyFields.initial_payment_amount, setValue]);

  function handleApplyDiscountToggle(checked) {
    setApplyDiscount(checked);
    if (!checked) {
      setValue('discount_amount', '');
      setValue('discount_reason', '');
    }
  }

  function handleAddLine() {
    setQuantityError(null);
    if (!selectedMedicine) return;
    const parsed = billLineItemSchema.safeParse({ quantity });
    if (!parsed.success) {
      setQuantityError(parsed.error.issues[0]?.message ?? 'Invalid quantity');
      return;
    }

    setItems((current) => {
      const existingIndex = current.findIndex((item) => item.medicine_id === selectedMedicine.id);
      if (existingIndex >= 0) {
        const next = [...current];
        next[existingIndex] = {
          ...next[existingIndex],
          quantity: next[existingIndex].quantity + parsed.data.quantity,
        };
        return next;
      }
      return [
        ...current,
        {
          medicine_id: selectedMedicine.id,
          name: selectedMedicine.name,
          category: selectedMedicine.category,
          unit_price: selectedMedicine.unit_price,
          quantity: parsed.data.quantity,
        },
      ];
    });
    setSelectedMedicine(null);
    setQuantity('1');
  }

  function handleRemoveLine(medicineId) {
    setItems((current) => current.filter((item) => item.medicine_id !== medicineId));
  }

  // The two modes are mutually exclusive in the UI too, mirroring the
  // backend's own invariant (models.py's MedicineBill docstring) —
  // switching modes clears whichever the other one had gathered, so a
  // stale search selection or a half-typed manual entry never lingers
  // and accidentally reappears if the receptionist switches back.
  function handleModeChange(nextMode) {
    setLinkMode(nextMode);
    setSelectedPatient(null);
    setSelectedVisit(null);
    setManualName('');
    setManualAge('');
    setManualPhone('');
  }

  function resetPatientLinkage() {
    setLinkMode('search');
    setSelectedPatient(null);
    setSelectedVisit(null);
    setManualName('');
    setManualAge('');
    setManualPhone('');
  }

  async function handleFinalize(values) {
    setFinalizeError(null);

    let manualPatientPayload = {};
    if (linkMode === 'manual') {
      const parsed = manualPatientSchema.safeParse({
        manual_patient_name: manualName,
        manual_patient_age: manualAge,
        manual_patient_phone: manualPhone,
      });
      if (!parsed.success) {
        setFinalizeError(parsed.error.issues[0]?.message ?? 'Manual patient details are incomplete.');
        return;
      }
      manualPatientPayload = parsed.data;
    }

    try {
      const response = await createBill.mutateAsync({
        visit_id: selectedVisit ? selectedVisit.id : null,
        items: items.map((item) => ({ medicine_id: item.medicine_id, quantity: item.quantity })),
        initial_payment_amount: values.initial_payment_amount,
        initial_payment_method: values.initial_payment_amount
          ? values.initial_payment_method
          : null,
        // Belt-and-suspenders with handleApplyDiscountToggle's own
        // clearing: even if a stale value somehow survived, an
        // unticked checkbox always sends no discount at all.
        discount_amount: applyDiscount ? values.discount_amount : 0,
        discount_reason: applyDiscount ? values.discount_reason || null : null,
        ...manualPatientPayload,
      });
      const bill = response.data;
      setItems([]);
      resetPatientLinkage();
      setApplyDiscount(false);
      resetFinalizeForm({
        initial_payment_amount: '',
        initial_payment_method: '',
        discount_amount: '',
        discount_reason: '',
      });
      toast.success({
        title: 'Medicine bill finalized',
        description: `Total ${money(bill.total_amount)} · Received ${money(bill.amount_paid)}`,
      });
      await printBill.mutateAsync(bill.id);
    } catch (error) {
      setFinalizeError(error.message || 'Unable to finalize this bill.');
      toast.error({
        title: 'Unable to finalize this bill',
        description: error.message,
      });
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-1">
        <h1 className="text-lg font-semibold text-foreground">Medicine Billing</h1>
        <p className="text-sm text-muted-foreground">
          Search the price list, build a bill, then finalize and print.
        </p>
      </div>

      <VisitLinkPanel
        mode={linkMode}
        onModeChange={handleModeChange}
        selectedPatient={selectedPatient}
        selectedVisit={selectedVisit}
        onSelectPatient={setSelectedPatient}
        onSelectVisit={setSelectedVisit}
        onClear={() => {
          setSelectedPatient(null);
          setSelectedVisit(null);
        }}
        manualName={manualName}
        manualAge={manualAge}
        manualPhone={manualPhone}
        onManualNameChange={setManualName}
        onManualAgeChange={setManualAge}
        onManualPhoneChange={setManualPhone}
      />

      <Card>
        <CardHeader>
          <CardTitle>Add Medicine</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-4 sm:flex-row sm:items-end">
          <div className="flex flex-1 flex-col gap-1.5">
            <Label>Medicine</Label>
            <SearchSelect
              queryKey={['pharmacy', 'medicines', 'search']}
              queryFn={(term) => pharmacyService.searchMedicines(term).then((res) => res.data)}
              getLabel={(medicine) => medicine.name}
              getDescription={(medicine) => `${medicine.category} · ${money(medicine.unit_price)}`}
              placeholder="Search medicine by name"
              selectedLabel={selectedMedicine ? `${selectedMedicine.name}` : ''}
              onSelect={(medicine) => setSelectedMedicine(medicine)}
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="quantity">Quantity</Label>
            <Input
              id="quantity"
              type="number"
              min="1"
              max="1000"
              value={quantity}
              onChange={(event) => setQuantity(event.target.value)}
              className="w-24"
            />
          </div>
          <Button type="button" onClick={handleAddLine} disabled={!selectedMedicine}>
            <Plus className="h-4 w-4" />
            Add Line
          </Button>
        </CardContent>
        {quantityError ? (
          <p className="px-4 pb-4 text-xs text-destructive">{quantityError}</p>
        ) : null}
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Current Bill</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          {items.length === 0 ? (
            <p className="text-sm text-muted-foreground">No medicines added yet.</p>
          ) : (
            <form onSubmit={handleSubmit(handleFinalize)} className="flex flex-col gap-4">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Medicine</TableHead>
                    <TableHead>Category</TableHead>
                    <TableHead className="text-right">Qty</TableHead>
                    <TableHead className="text-right">Unit Price</TableHead>
                    <TableHead className="text-right">Line Total</TableHead>
                    <TableHead />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {items.map((item) => (
                    <TableRow key={item.medicine_id}>
                      <TableCell className="font-medium text-foreground">{item.name}</TableCell>
                      <TableCell className="capitalize">{item.category}</TableCell>
                      <TableCell className="text-right tabular-nums">{item.quantity}</TableCell>
                      <TableCell className="text-right tabular-nums">
                        {money(item.unit_price)}
                      </TableCell>
                      <TableCell className="text-right font-medium tabular-nums">
                        {money(Number(item.unit_price) * item.quantity)}
                      </TableCell>
                      <TableCell>
                        <Button
                          type="button"
                          size="sm"
                          variant="ghost"
                          onClick={() => handleRemoveLine(item.medicine_id)}
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              <div className="flex items-center justify-between border-t border-border pt-4">
                <span className="text-sm font-semibold text-foreground">Grand Total</span>
                <span className="text-lg font-bold tabular-nums text-foreground">
                  {money(grandTotal)}
                </span>
              </div>

              {/* Optional flat discount (2026-08-19 addition) — same
                  toggle shape as RegisterVisitForm.jsx's "Vitals
                  required" checkbox: unticked, no discount fields show
                  and none is applied; ticked, it reveals the amount +
                  optional reason and a live Net Total preview below.
                  Unlike Billing's own Invoice discount, a reason is
                  never required here (a deliberate product decision —
                  see PharmacyService.create_bill's docstring). Plain
                  local state, not a registered form field — mirrors
                  MedicineBillingWorkspace's own linkMode/manual-field
                  toggles above, which are handled the same ad hoc way
                  rather than folded into finalizeBillSchema. */}
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
                      <Label htmlFor="discount_amount">Discount (Rs.)</Label>
                      <Input
                        id="discount_amount"
                        type="number"
                        step="0.01"
                        placeholder="0.00"
                        {...register('discount_amount')}
                      />
                      {finalizeErrors.discount_amount ? (
                        <p className="text-xs text-destructive">
                          {finalizeErrors.discount_amount.message}
                        </p>
                      ) : null}
                    </div>
                    <div className="flex flex-1 flex-col gap-1.5 sm:min-w-[12rem]">
                      <Label htmlFor="discount_reason">Discount Reason (optional)</Label>
                      <Input
                        id="discount_reason"
                        placeholder="e.g. Bulk purchase, loyalty discount"
                        {...register('discount_reason')}
                      />
                    </div>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-semibold text-foreground">Net Total</span>
                    <span className="text-lg font-bold tabular-nums text-foreground">
                      {money(netTotal)}
                    </span>
                  </div>
                </>
              ) : null}

              {/* Optional payment collected in the same step — defaults
                  to the full Net Total once items are added (2026-08-21
                  fix, see the auto-sync effect above), since payment is
                  normally collected in full before the slip is printed;
                  still freely editable down to a genuine partial amount,
                  or cleared to finalize unpaid, exactly as before.
                  Recorded atomically with the bill itself (see
                  PharmacyService.create_bill's docstring) — never a
                  separate, possibly-failing second request. */}
              <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
                <div className="flex flex-col gap-1.5 sm:w-48">
                  <Label htmlFor="initial_payment_amount">Advance Received (Rs.)</Label>
                  <Input
                    id="initial_payment_amount"
                    type="number"
                    step="0.01"
                    placeholder="0.00"
                    {...register('initial_payment_amount')}
                  />
                  {finalizeErrors.initial_payment_amount ? (
                    <p className="text-xs text-destructive">
                      {finalizeErrors.initial_payment_amount.message}
                    </p>
                  ) : null}
                </div>
                <div className="sm:w-44">
                  <PaymentMethodSelect
                    id="initial_payment_method"
                    registration={register('initial_payment_method')}
                    error={finalizeErrors.initial_payment_method}
                  />
                </div>
                <Button
                  type="submit"
                  size="lg"
                  disabled={createBill.isPending || printBill.isPending}
                  className="w-full sm:w-auto"
                >
                  <PackagePlus className="h-4 w-4" />
                  {createBill.isPending || printBill.isPending ? 'Finalizing…' : 'Finalize & Print'}
                </Button>
              </div>
              {finalizeError ? <p className="text-sm text-destructive">{finalizeError}</p> : null}
            </form>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
