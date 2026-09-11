"""Permission codes for the Pharmacy / Medicine Billing module.

Split the same way Billing's constants.py is (see that module's
docstring): `pharmacy:read` and `pharmacy:bill` are granted to the
Receptionist role (search the price list, build and print a medicine
bill), while `pharmacy:manage` — creating/editing/deactivating the
medicine price list itself — is granted only to `admin` (via the launch
bootstrap seed script's "admin gets every permission" rule; see
scripts/seed_launch_bootstrap.py). This module's code never enforces
*who* holds which permission — that is a role-assignment/deployment
concern (Phase 5 RBAC, frozen) — but the codes are split precisely along
this line so that assignment is possible in the first place."""

PERMISSION_PHARMACY_READ = "pharmacy:read"
PERMISSION_PHARMACY_BILL = "pharmacy:bill"
PERMISSION_PHARMACY_MANAGE = "pharmacy:manage"

# A single global "this medicine is running low" threshold (2026-09
# addition, medicine stock tracking) — a plain constant, deliberately
# NOT a per-`Medicine` column or a UI-configurable value for v1. Unlike
# Inventory's per-item `low_stock_threshold` (a real column, because
# ward supplies genuinely vary — a box of gloves vs. a single crash-cart
# item), the pharmacy price list is uniform enough that one number is
# the simpler, sufficient model. `MedicineOut.is_low_stock` is computed
# live as `stock_quantity <= PHARMACY_LOW_STOCK_THRESHOLD` (so a
# medicine at exactly the threshold, and one at zero, both read as low),
# never cached — same "a single-column comparison is cheaper to compute
# than to keep in sync" reasoning `InventoryItem`'s own docstring gives.
PHARMACY_LOW_STOCK_THRESHOLD = 10

# Admin-only data-correction actions (2026-08-20 addition) — mirrors
# app/modules/reception/constants.py's identical
# PERMISSION_RECEPTION_UPDATE_VISIT/PERMISSION_RECEPTION_DELETE_VISIT
# pair exactly: two separate, atomic permission codes (not folded into
# `pharmacy:manage`, which is about the medicine price list, a
# different resource entirely) so update/delete could be granted
# independently through the Roles/Permissions API without a code
# change. Neither is ever granted to the Receptionist role (see
# scripts/seed_launch_bootstrap.py's RECEPTIONIST_PERMISSION_CODES,
# which explicitly does not include these) — receptionists keep
# exactly the read/bill capability they had before; correcting or
# removing a mistakenly-created bill is an admin data-integrity tool,
# not a front-desk action.
PERMISSION_PHARMACY_UPDATE_BILL = "pharmacy:update_bill"
PERMISSION_PHARMACY_DELETE_BILL = "pharmacy:delete_bill"
