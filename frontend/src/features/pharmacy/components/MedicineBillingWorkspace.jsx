'use client';

import { useState } from 'react';
import { Plus, Printer, Trash2, PackagePlus, X } from 'lucide-react';
import { pharmacyService } from '@/features/pharmacy/api/pharmacyService';
import { patientsService } from '@/features/patients/api/patientsService';
import {
  useCreateMedicineBill,
  usePrintMedicineBill,
  useVisitsForPatient,
} from '@/features/pharmacy/hooks/usePharmacy';
import { billLineItemSchema } from '@/features/pharmacy/schemas/pharmacySchemas';
import { Card, CardContent, CardHeader, CardTitle } from '@/shared/components/ui/Card';
import { Button } from '@/shared/components/ui/Button';
import { Input } from '@/shared/components/ui/Input';
import { Label } from '@/shared/components/ui/Label';
import { Badge } from '@/shared/components/ui/Badge';
import { SearchSelect } from '@/shared/components/SearchSelect';
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

/** The optional "link to a registered visit" picker — two steps, both
 * skippable: find the patient (same SearchSelect + patientsService.search
 * pattern as RegisterVisitForm.jsx), then pick one of their recent
 * visits (useVisitsForPatient — GET /visits?patient_id=, no dedicated
 * visit-search endpoint exists). Once a visit is picked, `onSelectVisit`
 * carries both the patient and the visit up so the parent can show the
 * confirmation strip and pass `visit_id` on finalize. */
function VisitLinkPanel({
  selectedPatient,
  selectedVisit,
  onSelectPatient,
  onSelectVisit,
  onClear,
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
                      <span className="text-muted-foreground">{visit.procedure}</span>
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
      </CardContent>
    </Card>
  );
}

/** The receptionist's medicine-sale counter: search the active price
 * list, add one or more line items to a running local bill, then
 * finalize (posts the whole bill in one call — see
 * app/modules/pharmacy/service.py's `create_bill`) and print the slip.
 *
 * Linking to a registered Visit is optional (see `VisitLinkPanel`
 * above) — when no patient/visit is picked, `visit_id` stays null and
 * the bill is a standalone walk-in sale, exactly as before. */
export function MedicineBillingWorkspace() {
  const { toast } = useToast();
  const [selectedMedicine, setSelectedMedicine] = useState(null);
  const [quantity, setQuantity] = useState('1');
  const [quantityError, setQuantityError] = useState(null);
  const [items, setItems] = useState([]);
  const [finalizeError, setFinalizeError] = useState(null);
  const [selectedPatient, setSelectedPatient] = useState(null);
  const [selectedVisit, setSelectedVisit] = useState(null);

  const createBill = useCreateMedicineBill();
  const printBill = usePrintMedicineBill();

  const grandTotal = items.reduce((sum, item) => sum + Number(item.unit_price) * item.quantity, 0);

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

  async function handleFinalize() {
    setFinalizeError(null);
    try {
      const response = await createBill.mutateAsync({
        visit_id: selectedVisit ? selectedVisit.id : null,
        items: items.map((item) => ({ medicine_id: item.medicine_id, quantity: item.quantity })),
      });
      const billId = response.data.id;
      setItems([]);
      setSelectedPatient(null);
      setSelectedVisit(null);
      toast.success({
        title: 'Medicine bill finalized',
        description: `Total ${money(response.data.total_amount)}`,
      });
      await printBill.mutateAsync(billId);
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
          Search the price list, build a bill, then finalize and print the slip.
        </p>
      </div>

      <VisitLinkPanel
        selectedPatient={selectedPatient}
        selectedVisit={selectedVisit}
        onSelectPatient={setSelectedPatient}
        onSelectVisit={setSelectedVisit}
        onClear={() => {
          setSelectedPatient(null);
          setSelectedVisit(null);
        }}
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
            <>
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
              <Button
                type="button"
                size="lg"
                onClick={handleFinalize}
                disabled={createBill.isPending || printBill.isPending}
                className="w-full sm:w-auto sm:self-end"
              >
                {createBill.isPending || printBill.isPending ? (
                  <>
                    <PackagePlus className="h-4 w-4" />
                    Finalizing…
                  </>
                ) : (
                  <>
                    <Printer className="h-4 w-4" />
                    Finalize &amp; Print
                  </>
                )}
              </Button>
              {finalizeError ? <p className="text-sm text-destructive">{finalizeError}</p> : null}
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
