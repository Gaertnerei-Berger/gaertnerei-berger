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
| **Both** | Direction-agnostic rows (SI/PI metadata, party-less Journal Entry transfers, or fallback) |

Export picks the mapping for the voucher’s resolved type, then falls back to **Both**.

For **Payment Entry** and **Journal Entry**, Mapping owns **Konto / Gegenkonto / BU** (PE via `custom_datev_*` preview fields; party side = Personenkonto). Grouping collapses rows and sets S/H (+ Umsatz for JE).

## Accepted orientation (Consultant Booking)

| Voucher | Konto | Gegenkonto | S/H |
|---------|-------|------------|-----|
| Sales Invoice | Erlöskonto | Debitor | H |
| Purchase Invoice | Aufwand | Kreditor | S |
| PI Is Paid payment | Kreditor | Kasse/Bank | S |
| PI write-off | Kreditor | Write-off account | S |
| PE Receive | Bank | Personenkonto | S |
| PE Pay | Personenkonto | Bank | S |
| JE sales | Erlöskonto | Debitor | H |
| JE purchase | Aufwand | Kreditor | S |
| JE transfer (no party) | Soll-Konto | Haben-Konto | S |

## Voucher status

The export includes only **submitted** vouchers (`docstatus = 1`). Draft and cancelled documents are excluded: cancelled GL entries (`is_cancelled = 1`) are filtered out; Sales/Purchase Invoice, Payment Entry, and Journal Entry queries require a submitted parent.

## Consultant Booking (`consultant_booking`)

Default for Berger. Matches live exports such as `RG-260020`.

- Groups Sales/Purchase Invoice lines by Erlöskonto + tax/BU key
- Adds settlement rows for **Is Paid** payments and write-offs on Purchase Invoice (BU = Settings pay BU for the payment, blank for write-off)
- Groups Payment Entry whose party rows (one per allocated invoice / credit note, plus unallocated) net exactly to one bank row, see [Payment Lines](#payment-lines)
- Groups qualifying Journal Entry patterns, including party-less two-row transfers between balance-sheet accounts (Bank an Kasse)
- **Konto / Gegenkonto** for PE/JE from DATEV Mapping; SI/PI from grouping (+ metadata Mapping)
- Temporary against account (**9090**) is **not** used on successfully grouped rows

### Fallthrough (raw GL + 9090)

Accepted for v1 when a voucher cannot be grouped (e.g. PE with deductions or exchange differences, so more than one non-party GL row, a party-less JE with more than two rows, a tax row, or an Income/Expense account). Those rows keep temporary Gegenkonto and usually blank BU — document for Steuerberater review; export is not blocked. The Journal Entry form shows an orange DATEV headline for party-less entries that will fall through. An empty mapped header field never overwrites Konto or Gegenkonto, so fallthrough rows keep 9090.

### Amount Basis

| Setting | Umsatz source | Use when |
|---------|---------------|----------|
| **Net** (`net`) | Item / JE business-line net | Steuerberater BU keys expect net |
| **Gross** (`gross`) | Net × (1 + tax rate) | BU keys expect gross |

Per-company setting. Applies to grouped SI/PI/JE with Item Tax Template. JE GL stays net.

### Payment Lines

Two per-company DATEV Settings decide how payments look. Agree both with the Steuerberater.

**Lines per Payment** applies when one Payment Entry settles several invoices or credit notes. A payment for a single invoice is always one line.

| Setting | Export | Example: 152,30 invoice − 34,50 credit note = 117,80 bank |
|---------|--------|-----------------------------------------------------------|
| **per_invoice** (default) | One line per allocated invoice / credit note; credit notes take the opposite S/H | 152,30 S and 34,50 H |
| **per_payment** | One line with the net bank amount | 117,80 S |

Per-invoice lines keep their allocated amount; the `paid_amount` Mapping row does not overwrite it. Konto, Gegenkonto and BU still come from Mapping.

**Belegfeld 1 on Payment Lines** sets the document number of a payment line that belongs to one invoice.

| Setting | Belegfeld 1 | Use when |
|---------|-------------|----------|
| **payment_entry** (default) | Payment Entry number | Steuerberater clears open items by hand |
| **invoice** | Invoice / credit note number | DATEV OPOS should match payment and open item automatically |

The Payment Entry number stays in Beleginfo - Inhalt 1 in both cases. Lines that settle no single invoice (an unallocated amount, or a `per_payment` net line for several invoices) keep the Payment Entry number.

### Umsatz Decimal Separator

Hardcoded to **`,`** (German DATEV). Not configurable in Settings.

## Monthly handoff

Supported path: **DATEV page** → **DATEV Export** DocType (ZIP attachment). See [datev_workflow.md](datev_workflow.md).

The legacy DATEV query report remains available for **Preview / power users**, not as the documented monthly handoff.
