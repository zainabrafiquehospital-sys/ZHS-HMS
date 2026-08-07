"""Shared helper for `Numeric(10, 2)` money columns (Billing, Visit).

A `Decimal` a caller supplies (e.g. `Decimal("20000")` from a request
body) is mathematically equal to but not identically-formatted as the
DB column's stored scale (`Decimal("20000.00")`). That mismatch is
invisible after any request that re-queries the row in a fresh
session/transaction (Postgres always returns the column at its declared
scale) — but it *is* visible in the same request that just inserted the
row: SQLAlchemy's identity map returns the in-memory object as-is
without an automatic refresh, so an immediate response can show the
caller's original, unpadded precision (e.g. `"20000"` instead of
`"20000.00"`). Quantizing at construction time — before the value ever
touches the ORM — makes the in-memory value already match what the
column would return on a fresh fetch, so the immediate response is
correct without depending on any refresh/re-fetch behavior."""

from decimal import ROUND_HALF_UP, Decimal

_MONEY_SCALE = Decimal("0.01")


def quantize_money(value: Decimal) -> Decimal:
    return value.quantize(_MONEY_SCALE, rounding=ROUND_HALF_UP)
