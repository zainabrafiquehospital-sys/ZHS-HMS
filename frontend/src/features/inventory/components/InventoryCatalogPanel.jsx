'use client';

import { useMemo, useState } from 'react';
import { Pencil, Power, PowerOff, Search, Trash2 } from 'lucide-react';
import {
  useInventoryItems,
  useDeleteInventoryItem,
  useUpdateInventoryItem,
} from '@/features/inventory/hooks/useInventory';
import { InventoryItemForm } from '@/features/inventory/components/InventoryItemForm';
import { Card, CardContent, CardHeader, CardTitle } from '@/shared/components/ui/Card';
import { Button } from '@/shared/components/ui/Button';
import { Input } from '@/shared/components/ui/Input';
import { Badge } from '@/shared/components/ui/Badge';
import { ConfirmDialog } from '@/shared/components/ui/ConfirmDialog';
import { PageLoader } from '@/shared/components/PageLoader';
import { PageError } from '@/shared/components/PageError';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/shared/components/ui/Table';
import { useDebouncedValue } from '@/shared/hooks/useDebouncedValue';
import { useToast } from '@/shared/components/toast/ToastProvider';

function ItemsListPanel({ items, onEdit }) {
  const { toast } = useToast();
  const updateItem = useUpdateInventoryItem();
  const deleteItem = useDeleteInventoryItem();
  const [toggleError, setToggleError] = useState(null);
  const [searchTerm, setSearchTerm] = useState('');
  const [deletingItem, setDeletingItem] = useState(null);
  const [deleteError, setDeleteError] = useState(null);
  const debouncedSearch = useDebouncedValue(searchTerm, 200);

  // Client-side name/category filter over the already-fetched catalog —
  // the same inline "<Search> icon + debounced <Input> + local filter"
  // pattern PatientDirectory.jsx / MyMedicineBills.jsx use; the catalog
  // is a single page_size=100 fetch, never server-paginated, so there's
  // nothing to wire this into.
  const filteredItems = useMemo(() => {
    const term = debouncedSearch.trim().toLowerCase();
    if (!term) return items;
    return items.filter(
      (item) =>
        item.name.toLowerCase().includes(term) || item.category.toLowerCase().includes(term),
    );
  }, [items, debouncedSearch]);

  async function handleToggleActive(item) {
    setToggleError(null);
    try {
      const nextActive = !item.is_active;
      await updateItem.mutateAsync({ itemId: item.id, payload: { is_active: nextActive } });
      toast.success({
        title: nextActive ? 'Item activated' : 'Item deactivated',
        description: item.name,
      });
    } catch (error) {
      const message = error.message || 'Unable to update this item.';
      setToggleError(message);
      toast.error({ title: 'Unable to update item', description: message });
    }
  }

  async function handleConfirmDelete() {
    if (!deletingItem) return;
    setDeleteError(null);
    try {
      await deleteItem.mutateAsync(deletingItem.id);
      toast.success({ title: 'Item deleted', description: deletingItem.name });
      setDeletingItem(null);
    } catch (error) {
      // Kept inline in the dialog (same "failure is a message, not a
      // separate UI state" shape AdminOverview.jsx's own delete
      // confirmations use) so the user can read it and retry/cancel.
      setDeleteError(error.message || 'Unable to delete this item.');
    }
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <CardTitle>Item Catalog</CardTitle>
          <div className="relative w-full sm:w-64">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={searchTerm}
              onChange={(event) => setSearchTerm(event.target.value)}
              placeholder="Search by name or category…"
              className="pl-8"
            />
          </div>
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {items.length === 0 ? (
          <p className="text-sm text-muted-foreground">No items added yet.</p>
        ) : filteredItems.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No items match &quot;{debouncedSearch}&quot;.
          </p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Category</TableHead>
                <TableHead>Unit</TableHead>
                <TableHead className="text-right">Main Stock</TableHead>
                <TableHead className="text-right">Emergency Stock</TableHead>
                <TableHead>Status</TableHead>
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {filteredItems.map((item) => (
                <TableRow key={item.id}>
                  <TableCell className="font-medium text-foreground">{item.name}</TableCell>
                  <TableCell className="capitalize">{item.category}</TableCell>
                  <TableCell className="capitalize">{item.unit}</TableCell>
                  <TableCell className="text-right tabular-nums">{item.main_stock_level}</TableCell>
                  <TableCell className="text-right tabular-nums">
                    <span className="inline-flex items-center gap-1.5">
                      {item.emergency_stock_level}
                      {item.is_low_stock ? <Badge variant="destructive">Low</Badge> : null}
                    </span>
                  </TableCell>
                  <TableCell>
                    <Badge variant={item.is_active ? 'success' : 'outline'}>
                      {item.is_active ? 'Active' : 'Inactive'}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <div className="flex justify-end gap-2">
                      <Button size="sm" variant="outline" onClick={() => onEdit(item)}>
                        <Pencil className="h-4 w-4" />
                        Edit
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => handleToggleActive(item)}
                        disabled={updateItem.isPending}
                      >
                        {item.is_active ? (
                          <>
                            <PowerOff className="h-4 w-4" />
                            Deactivate
                          </>
                        ) : (
                          <>
                            <Power className="h-4 w-4" />
                            Activate
                          </>
                        )}
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        className="text-destructive hover:text-destructive"
                        onClick={() => {
                          setDeleteError(null);
                          setDeletingItem(item);
                        }}
                      >
                        <Trash2 className="h-4 w-4" />
                        Delete
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
        {toggleError ? <p className="text-sm text-destructive">{toggleError}</p> : null}
      </CardContent>

      <ConfirmDialog
        open={Boolean(deletingItem)}
        variant="destructive"
        title={deletingItem ? `Delete ${deletingItem.name}?` : 'Delete item'}
        confirmLabel={deleteItem.isPending ? 'Deleting…' : 'Delete Item'}
        onConfirm={handleConfirmDelete}
        onCancel={() => setDeletingItem(null)}
        description={
          <div className="flex flex-col gap-2 text-sm text-muted-foreground">
            <p>
              This removes the item from the catalog and every item picker. Its history —
              receipts, transfers, usage entries, and restock requests — stays intact.
            </p>
            <p>To keep it on file but stop offering it, use Deactivate instead.</p>
            {deleteError ? <p className="text-destructive">{deleteError}</p> : null}
          </div>
        }
      />
    </Card>
  );
}

export function InventoryCatalogPanel() {
  const { data: items, isLoading, isError, error, refetch } = useInventoryItems();
  const [editing, setEditing] = useState(null);

  return (
    <div className="flex flex-col gap-6">
      <InventoryItemForm
        editing={editing}
        onDoneEditing={() => setEditing(null)}
        showInitialReceipt
      />

      {isLoading ? (
        <PageLoader label="Loading catalog" />
      ) : isError ? (
        <PageError error={error} reset={refetch} message="Couldn't load the item catalog." />
      ) : (
        <ItemsListPanel items={items ?? []} onEdit={setEditing} />
      )}
    </div>
  );
}
