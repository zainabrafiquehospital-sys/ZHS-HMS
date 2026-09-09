"""Permission codes for the Ward/Emergency Inventory Management module.

Split follows Pharmacy's exact "coarse manage vs. narrow per-actor"
convention (see app/modules/pharmacy/constants.py's own docstring) —
`inventory:manage` covers the Inventory Manager's stock-custody actions
(Main Stock receipts, transfers to Emergency Stock, direct-to-Emergency
receipts, fulfilling/rejecting restock requests, and soft-deleting a
catalog item); `inventory:record_usage`/`inventory:request_restock` are
Vitals' own two actions on this module, split by actor and by action
from `inventory:manage` and from each other.

`inventory:create_item` (2026-09 addition) is a third such narrow
split: adding a new row to the catalog, and nothing else — granted to
BOTH Inventory Manager and Vitals (both legitimately discover a missing
item mid-task), but deliberately NOT carrying receive/transfer/
fulfill/delete the way `inventory:manage` does. `POST /inventory/items`
accepts `inventory:create_item` OR `inventory:manage` (so every
existing `inventory:manage` holder keeps creating items unchanged);
every other write endpoint stays `inventory:manage`-only. Item
soft-delete stays `inventory:manage`-only too — a more consequential
action than create (it can remove an item with real ledger history
from every picker), so it is not extended to the narrower permission.

`inventory:read` is shared visibility, granted to Inventory Manager,
Vitals, and (via the "admin holds every permission that exists"
convention — see scripts/seed_launch_bootstrap.py) Admin.

Doctor is granted nothing here — this module's design explicitly
excludes Doctor; the absence of any grant is itself the enforcement,
the same default-deny posture every other module already relies on."""

PERMISSION_INVENTORY_READ = "inventory:read"
PERMISSION_INVENTORY_MANAGE = "inventory:manage"
PERMISSION_INVENTORY_CREATE_ITEM = "inventory:create_item"
PERMISSION_INVENTORY_RECORD_USAGE = "inventory:record_usage"
PERMISSION_INVENTORY_REQUEST_RESTOCK = "inventory:request_restock"
