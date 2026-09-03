# DATEV Buchungsstapel Export Modes

Configure export behaviour in **DATEV Settings** under **Buchungsstapel Export**.

Production mode is **Consultant Booking** only (Settings UI). Umsatz decimals are always **`,`**.

See also [accepted_export_contract.md](accepted_export_contract.md) for the frozen orientation matrix.

## DATEV Mapping direction (Receivable / Payable / Both)

DATEV Mapping is keyed by **Voucher Type** + **Party Account Type**:

| Party Account Type | Typical use |
|--------------------|-------------|
| **Receivable** | Payment Entry **Receive**, sales-like Journal Entry |
| **Payable** | Payment Entry **Pay**, purchase-like Journal Entry |
| **Both** | Direction-agnostic rows (SI/PI metadata, or fallback) |

Export picks the mapping for the voucher’s resolved type, then falls back to **Both**.

For **Payment Entry** and **Journal Entry**, Mapping owns **Konto / Gegenkonto / BU** (PE via `custom_datev_*` preview fields; party side = Personenkonto). Grouping collapses rows and sets S/H (+ Umsatz for JE).

## Accepted orientation (Consultant Booking)

| Voucher | Konto | Gegenkonto | S/H |
|---------|-------|------------|-----|
| Sales Invoice | Erlöskonto | Debitor | H |
| Purchase Invoice | Aufwand | Kreditor | S |
| PE Receive | Bank | Personenkonto | S |
| PE Pay | Personenkonto | Bank | S |
| JE sales | Erlöskonto | Debitor | H |
| JE purchase | Aufwand | Kreditor | S |

## Voucher status

The export includes only **submitted** vouchers (`docstatus = 1`). Draft and cancelled documents are excluded: cancelled GL entries (`is_cancelled = 1`) are filtered out; Sales/Purchase Invoice, Payment Entry, and Journal Entry queries require a submitted parent.

## Consultant Booking (`consultant_booking`)

Default for Berger. Matches live exports such as `RG-260020`.

- Groups Sales/Purchase Invoice lines by Erlöskonto + tax/BU key
- Groups simple Payment Entry (exactly 2 GL rows) and qualifying Journal Entry patterns
- **Konto / Gegenkonto** for PE/JE from DATEV Mapping; SI/PI from grouping (+ metadata Mapping)
- Temporary against account (**9090**) is **not** used on successfully grouped rows

### Fallthrough (raw GL + 9090)

Accepted for v1 when a voucher cannot be grouped (e.g. PE with ≠2 GL rows, non-party JE). Those rows keep temporary Gegenkonto and usually blank BU — document for Steuerberater review; export is not blocked.

### Amount Basis

| Setting | Umsatz source | Use when |
|---------|---------------|----------|
| **Net** (`net`) | Item / JE business-line net | Steuerberater BU keys expect net |
| **Gross** (`gross`) | Net × (1 + tax rate) | BU keys expect gross |

Per-company setting. Applies to grouped SI/PI/JE with Item Tax Template. JE GL stays net.

### Umsatz Decimal Separator

Hardcoded to **`,`** (German DATEV). Not configurable in Settings.

## Monthly handoff

Supported path: **DATEV page** → **DATEV Export** DocType (ZIP attachment). See [datev_workflow.md](datev_workflow.md).

The legacy DATEV query report remains available for **Preview / power users**, not as the documented monthly handoff.
