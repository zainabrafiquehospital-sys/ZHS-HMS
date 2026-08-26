"""Permission codes for the Ward/Emergency Inventory Management module.

Split follows Pharmacy's exact "coarse manage vs. narrow per-actor"
convention (see app/modules/pharmacy/constants.py's own docstring) —
`inventory:manage` covers every action the Inventory Manager performs
(catalog CRUD, Main Stock receipts, transfers to Emergency Stock,
fulfilling/rejecting restock requests); splitting it further would only
serve a future-assignment purpose that doesn't exist here, since exactly
one role is ever expected to hold it (unlike Pharmacy's read/bill/manage
split, which exists because Receptionist and Admin genuinely need
different subsets). `inventory:record_usage`/`inventory:request_restock`
are Vitals' own two actions on this module, split by actor and by
action from `inventory:manage` and from each other. `inventory:read` is
shared visibility, granted to Inventory Manager, Vitals, and (via the
"admin holds every permission that exists" convention — see
scripts/seed_launch_bootstrap.py) Admin.

Doctor is granted nothing here — this module's design explicitly
excludes Doctor; the absence of any grant is itself the enforcement,
the same default-deny posture every other module already relies on."""

PERMISSION_INVENTORY_READ = "inventory:read"
PERMISSION_INVENTORY_MANAGE = "inventory:manage"
PERMISSION_INVENTORY_RECORD_USAGE = "inventory:record_usage"
PERMISSION_INVENTORY_REQUEST_RESTOCK = "inventory:request_restock"
