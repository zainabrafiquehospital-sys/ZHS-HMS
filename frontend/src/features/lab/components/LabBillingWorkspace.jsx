'use client';

import { useEffect, useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { FlaskConical, Plus, Trash2, X } from 'lucide-react';
import { labService } from '@/features/lab/api/labService';
import { patientsService } from '@/features/patients/api/patientsService';
import { useCreateLabBill, usePrintLabBill } from '@/features/lab/hooks/useLab';
import { finalizeLabBillSchema, labManualPatientSchema } from '@/features/lab/schemas/labSchemas';
import { Card, CardContent, CardHeader, CardTitle } from '@/shared/components/ui/Card';
import { Button } from '@/shared/components/ui/Button';
import { Input } from '@/shared/components/ui/Input';
import { Label } from '@/shared/components/ui/Label';
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

function money(amount) {
  return `Rs. ${Number(amount).toFixed(2)}`;
}

// Local, stable keys for not-yet-submitted running-list rows — never
// sent to the server (see ProcedureItemsEditor.jsx's identical
// nextItemKey rationale). A module-level counter, not array index: two
// rows for the very same test (a genuine, allowed case — confirmed
// design, no quantity/merge, see LabBillItem's own docstring) still
// need distinct React keys.
let nextItemKey = (() => {
  let value = 0;
  return () => value++;
})();

/** Converts one running-list row into the `{lab_test_id} | {name,
 * price}` request shape `POST /lab/bills` expects (2026-08-28
 * addition) — mirrors ProcedureItemsEditor.jsx's identical
 * `procedureItemToRequestPayload`: a catalog-linked row sends only
 * `lab_test_id` (name/price are always server-derived from the
 * catalog), a manual row sends only `name`/`price`. */
function labBillItemToRequestPayload(item) {
  if (item.lab_test_id) {
    return { lab_test_id: item.lab_test_id };
  }
  return { name: item.name, price: Number(item.price) };
}

/** The "which patient is this for" panel — a direct Patient link
 * (confirmed design), never Visit-mediated the way Pharmacy's own
 * VisitLinkPanel is (search a patient, then pick one of their
 * visits): this module's own population is exactly as likely to have
 * no same-day registered Visit as Inventory's own ward/emergency
 * population already is (see backend/app/modules/lab/models.py's
 * LabBill docstring for the full rationale) — picking a patient is
 * the whole of it, no second "which visit" step. Manual Entry and the
 * anonymous walk-in fallback otherwise mirror VisitLinkPanel's
 * identical shape (same three fields, same "all three together" rule,
 * same "no record is looked up or created" framing, same "leave
 * unselected to bill this as a walk-in sale" default). */
function LabPatientLinkPanel({
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
  if (selectedPatient) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Linked Patient</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-wrap items-center justify-between gap-3">
          <span className="text-sm font-medium text-foreground">
            {selectedPatient.full_name} (MR: {selectedPatient.mr_number})
          </span>
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
        <CardTitle>Link to Patient (Optional)</CardTitle>
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
                <Label htmlFor="lab_manual_patient_name">Name</Label>
                <Input
                  id="lab_manual_patient_name"
                  value={manualName}
                  onChange={(event) => onManualNameChange(event.target.value)}
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="lab_manual_patient_age">Age</Label>
                <Input
                  id="lab_manual_patient_age"
                  type="number"
                  min="0"
                  max="150"
                  className="w-24"
                  value={manualAge}
                  onChange={(event) => onManualAgeChange(event.target.value)}
                />
              </div>
              <div className="flex flex-1 flex-col gap-1.5 sm:min-w-[10rem]">
                <Label htmlFor="lab_manual_patient_phone">Contact Number</Label>
                <Input
                  id="lab_manual_patient_phone"
                  value={manualPhone}
                  onChange={(event) => onManualPhoneChange(event.target.value)}
                />
              </div>
            </div>
            <p className="text-xs text-muted-foreground">
              All three fields are required together. Shown on the printed slip only — no patient
              record is looked up or created.
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
              selectedLabel={selectedPatient ? selectedPatient.full_name : ''}
              onSelect={(patient) => onSelectPatient(patient)}
            />
            <p className="text-xs text-muted-foreground">
              Leave unselected to bill this as a walk-in sale.
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

/** The receptionist's lab-test billing counter: search the active test
 * catalog, add one or more tests to a running local bill, then
 * finalize — a single step that posts the whole bill AND an optional
 * "Advance Received" payment together in one call (see
 * app/modules/lab/service.py's `create_bill`'s `initial_payment_amount`,
 * atomically recorded alongside creation), then prints the slip.
 * Advance Received defaults to the full Net Total once tests are added
 * (same UX Pharmacy's own workspace already established) but stays
 * freely editable for a genuine partial payment, or clearable to still
 * create the bill `UNPAID`.
 *
 * Adding a test never takes a quantity (confirmed design, see
 * models.py's `LabBillItem` docstring) — each "Add Test" click appends
 * exactly one line; picking the same test again appends a second,
 * independent line rather than merging into a quantity, matching
 * ProcedureItemsEditor.jsx's own non-merging "Add Another" behavior
 * (not Pharmacy's own quantity-merge).
 *
 * A test not yet in the catalog can also be typed in directly (2026-
 * 08-28 addition) — the "Not in the catalog? Type it in" fallback
 * inside the Add Test card, mirroring ProcedureItemsEditor.jsx's
 * identical manual-procedure block exactly (name + price fields, "Add
 * Another Test"). Both kinds of row coexist in the same running list,
 * each independently either catalog-linked or manual — a manual row's
 * Category column shows a dash (no catalog category to snapshot; see
 * models.py's `LabBillItem` docstring).
 *
 * Recording an *additional* payment later, toward whatever's still
 * Pending on an already-created bill, lives in Admin Overview's Lab
 * Bills tab — this workspace is only ever the point of a new sale.
 *
 * "Apply Discount" is an optional flat discount, off entirely by
 * default — same toggle shape as MedicineBillingWorkspace.jsx's
 * identical checkbox. */
export function LabBillingWorkspace() {
  const { toast } = useToast();
  const [selectedTest, setSelectedTest] = useState(null);
  const [items, setItems] = useState([]);
  const [finalizeError, setFinalizeError] = useState(null);
  const [selectedPatient, setSelectedPatient] = useState(null);
  const [linkMode, setLinkMode] = useState('search');
  const [manualName, setManualName] = useState('');
  const [manualAge, setManualAge] = useState('');
  const [manualPhone, setManualPhone] = useState('');
  const [applyDiscount, setApplyDiscount] = useState(false);
  // Manual/free-typed test entry (2026-08-28 addition) — the lab-bill
  // sibling of ProcedureItemsEditor.jsx's identical "Not in the
  // catalog? Type it in" fallback, mirrored as closely as this
  // workspace's own flat local-state shape (not that component's
  // reusable editor) allows. Own local state, distinct from
  // `selectedTest` above — the two entry paths coexist rather than
  // sharing one field.
  const [manualTestName, setManualTestName] = useState('');
  const [manualTestPrice, setManualTestPrice] = useState('');
  const [addTestError, setAddTestError] = useState(null);

  const createBill = useCreateLabBill();
  const printBill = usePrintLabBill();
  const {
    register,
    handleSubmit,
    watch,
    setValue,
    reset: resetFinalizeForm,
    formState: { errors: finalizeErrors, dirtyFields },
  } = useForm({
    resolver: zodResolver(finalizeLabBillSchema),
    defaultValues: {
      initial_payment_amount: '',
      initial_payment_method: '',
      discount_amount: '',
      discount_reason: '',
    },
  });

  const grandTotal = items.reduce((sum, item) => sum + Number(item.price), 0);
  const watchedDiscount = watch('discount_amount');
  const discountForPreview = applyDiscount && watchedDiscount ? Number(watchedDiscount) : 0;
  const netTotal = grandTotal - (Number.isFinite(discountForPreview) ? discountForPreview : 0);

  // Same "Advance Received tracks Net Total until the receptionist
  // actually types into it" auto-sync as MedicineBillingWorkspace.jsx's
  // own identical effect — see that component's own comment for the
  // full rationale.
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

  function handleAddTest() {
    if (!selectedTest) return;
    setItems((current) => [
      ...current,
      {
        key: nextItemKey(),
        lab_test_id: selectedTest.id,
        name: selectedTest.name,
        category: selectedTest.category,
        price: selectedTest.price,
      },
    ]);
    setSelectedTest(null);
  }

  // Mirrors ProcedureItemsEditor.jsx's identical handleAddManual —
  // same inline validation (non-empty name, price > 0), same "append
  // with no catalog id, then clear the two fields" shape. `category:
  // null` throughout — a manual line has no catalog category to show
  // (see LabBillItem's own docstring), the Category column renders a
  // dash for these rows below.
  function handleAddManualTest() {
    setAddTestError(null);
    const trimmedName = manualTestName.trim();
    const priceNumber = Number(manualTestPrice);
    if (!trimmedName) {
      setAddTestError('Enter a test name.');
      return;
    }
    if (!Number.isFinite(priceNumber) || priceNumber <= 0) {
      setAddTestError('Enter a price greater than 0.');
      return;
    }
    setItems((current) => [
      ...current,
      { key: nextItemKey(), lab_test_id: null, name: trimmedName, category: null, price: priceNumber },
    ]);
    setManualTestName('');
    setManualTestPrice('');
  }

  function handleRemoveLine(key) {
    setItems((current) => current.filter((item) => item.key !== key));
  }

  function handleModeChange(nextMode) {
    setLinkMode(nextMode);
    setSelectedPatient(null);
    setManualName('');
    setManualAge('');
    setManualPhone('');
  }

  function resetPatientLinkage() {
    setLinkMode('search');
    setSelectedPatient(null);
    setManualName('');
    setManualAge('');
    setManualPhone('');
  }

  async function handleFinalize(values) {
    setFinalizeError(null);

    let manualPatientPayload = {};
    if (linkMode === 'manual') {
      const parsed = labManualPatientSchema.safeParse({
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
        patient_id: selectedPatient ? selectedPatient.id : null,
        items: items.map((item) => labBillItemToRequestPayload(item)),
        initial_payment_amount: values.initial_payment_amount,
        initial_payment_method: values.initial_payment_amount
          ? values.initial_payment_method
          : null,
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
        title: 'Lab bill finalized',
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
        <h1 className="text-lg font-semibold text-foreground">Laboratory Billing</h1>
        <p className="text-sm text-muted-foreground">
          Search the lab test catalog, build a bill, then finalize and print.
        </p>
      </div>

      <LabPatientLinkPanel
        mode={linkMode}
        onModeChange={handleModeChange}
        selectedPatient={selectedPatient}
        onSelectPatient={setSelectedPatient}
        onClear={resetPatientLinkage}
        manualName={manualName}
        manualAge={manualAge}
        manualPhone={manualPhone}
        onManualNameChange={setManualName}
        onManualAgeChange={setManualAge}
        onManualPhoneChange={setManualPhone}
      />

      <Card>
        <CardHeader>
          <CardTitle>Add Test</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-end">
            <div className="flex flex-1 flex-col gap-1.5">
              <Label>Lab Test</Label>
              <SearchSelect
                queryKey={['lab', 'tests', 'search']}
                queryFn={(term) => labService.searchTests(term).then((res) => res.data)}
                getLabel={(test) => test.name}
                getDescription={(test) => `${test.category} · ${money(test.price)}`}
                placeholder="Search lab test by name"
                selectedLabel={selectedTest ? `${selectedTest.name}` : ''}
                onSelect={(test) => setSelectedTest(test)}
              />
            </div>
            <Button type="button" onClick={handleAddTest} disabled={!selectedTest}>
              <Plus className="h-4 w-4" />
              Add Test
            </Button>
          </div>

          {/* Manual/free-typed fallback (2026-08-28 addition, always
              available, never blocked on the catalog having this test
              yet) — coexists with catalog-linked rows in the same
              running list, mirroring ProcedureItemsEditor.jsx's
              identical dashed-border block exactly. */}
          <div className="flex flex-col gap-3 rounded-md border border-dashed border-border p-3 sm:flex-row sm:flex-wrap sm:items-end">
            <div className="flex min-w-[160px] flex-1 flex-col gap-1.5">
              <Label htmlFor="manual-lab-test-name">Not in the catalog? Type it in</Label>
              <Input
                id="manual-lab-test-name"
                placeholder="e.g. Vitamin D Panel"
                value={manualTestName}
                onChange={(event) => setManualTestName(event.target.value)}
              />
            </div>
            <div className="flex flex-col gap-1.5 sm:w-40">
              <Label htmlFor="manual-lab-test-price">Price (Rs.)</Label>
              <Input
                id="manual-lab-test-price"
                type="number"
                step="0.01"
                min="0"
                value={manualTestPrice}
                onChange={(event) => setManualTestPrice(event.target.value)}
              />
            </div>
            <Button type="button" variant="outline" onClick={handleAddManualTest}>
              <Plus className="h-4 w-4" />
              Add Another Test
            </Button>
          </div>
          {addTestError ? <p className="text-xs text-destructive">{addTestError}</p> : null}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Current Bill</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          {items.length === 0 ? (
            <p className="text-sm text-muted-foreground">No tests added yet.</p>
          ) : (
            <form onSubmit={handleSubmit(handleFinalize)} className="flex flex-col gap-4">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Test</TableHead>
                    <TableHead>Category</TableHead>
                    <TableHead className="text-right">Price</TableHead>
                    <TableHead />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {items.map((item) => (
                    <TableRow key={item.key}>
                      <TableCell className="font-medium text-foreground">{item.name}</TableCell>
                      <TableCell className="capitalize">{item.category ?? '—'}</TableCell>
                      <TableCell className="text-right tabular-nums">{money(item.price)}</TableCell>
                      <TableCell>
                        <Button
                          type="button"
                          size="sm"
                          variant="ghost"
                          onClick={() => handleRemoveLine(item.key)}
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
                        placeholder="e.g. Bulk tests, loyalty discount"
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
                  <FlaskConical className="h-4 w-4" />
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
