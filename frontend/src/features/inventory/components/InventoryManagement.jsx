'use client';

import { useState } from 'react';
import { AlertTriangle, Bell } from 'lucide-react';
import { useInventoryStats } from '@/features/inventory/hooks/useInventory';
import { InventoryCatalogPanel } from '@/features/inventory/components/InventoryCatalogPanel';
import { InventoryReceivePanel } from '@/features/inventory/components/InventoryReceivePanel';
import { InventoryTransferPanel } from '@/features/inventory/components/InventoryTransferPanel';
import { InventoryRestockRequestsPanel } from '@/features/inventory/components/InventoryRestockRequestsPanel';
import { InventoryHistoryPanel } from '@/features/inventory/components/InventoryHistoryPanel';
import { Badge } from '@/shared/components/ui/Badge';
import { Tabs } from '@/shared/components/ui/Tabs';

const INVENTORY_TABS = [
  { value: 'catalog', label: 'Catalog' },
  { value: 'receive', label: 'Receive Stock' },
  { value: 'transfer', label: 'Transfer to Emergency' },
  { value: 'requests', label: 'Restock Requests' },
  { value: 'history', label: 'History' },
];

/** The Inventory Manager's landing screen — same top-level "Tabs switch
 * which panel renders" shape as features/admin/components/
 * AdminOverview.jsx's own OVERVIEW_TABS, extended to five panels instead
 * of two. The stats strip (pending requests / low-stock items) is this
 * role's own dashboard indicator — surfaced "proactively... on both
 * Inventory Manager's and Admin's dashboards" per the confirmed design;
 * Admin's own copy of these figures is a later step. */
export function InventoryManagement() {
  const [activeTab, setActiveTab] = useState('catalog');
  const { data: stats } = useInventoryStats();

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-start justify-between gap-3">
        <div className="flex flex-col gap-1">
          <h1 className="text-lg font-semibold text-foreground">Inventory</h1>
          <p className="text-sm text-muted-foreground">
            Ward/Emergency stock — Main Stock, Emergency Stock, and restock requests.
          </p>
        </div>
        {stats ? (
          <div className="flex flex-wrap items-center gap-2">
            {stats.pending_requests > 0 ? (
              <Badge variant="warning" className="inline-flex items-center gap-1">
                <Bell className="h-3 w-3" />
                {stats.pending_requests} Pending Request{stats.pending_requests === 1 ? '' : 's'}
              </Badge>
            ) : null}
            {stats.low_stock_items > 0 ? (
              <Badge variant="warning" className="inline-flex items-center gap-1">
                <AlertTriangle className="h-3 w-3" />
                {stats.low_stock_items} Low-Stock Item{stats.low_stock_items === 1 ? '' : 's'}
              </Badge>
            ) : null}
          </div>
        ) : null}
      </div>

      <Tabs value={activeTab} onValueChange={setActiveTab} tabs={INVENTORY_TABS} />

      {activeTab === 'catalog' ? (
        <InventoryCatalogPanel />
      ) : activeTab === 'receive' ? (
        <InventoryReceivePanel />
      ) : activeTab === 'transfer' ? (
        <InventoryTransferPanel />
      ) : activeTab === 'requests' ? (
        <InventoryRestockRequestsPanel />
      ) : (
        <InventoryHistoryPanel />
      )}
    </div>
  );
}
