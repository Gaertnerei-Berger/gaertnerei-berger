# Accepted DATEV export contract (v1)

Frozen orientation for **Consultant Booking**. Do not change without a new grill round.

| Voucher | Konto | Gegenkonto | S/H | BU |
|---------|-------|------------|-----|-----|
| Sales Invoice | Erlöskonto | Debitor | H | item `custom_bu_schlussel` |
| Purchase Invoice | Aufwand | Kreditor | S | item BU |
| Purchase Invoice – Is Paid payment | Kreditor | Kasse/Bank | S | Settings pay BU |
| Purchase Invoice – write-off | Kreditor | Write-off account | S | blank (Steuerberater review) |
| Payment Entry Receive | Bank | Personenkonto | S | Settings receive BU (via Mapping) |
| Payment Entry Pay | Personenkonto | Bank | S | Settings pay BU (via Mapping) |
| Journal Entry sales | Erlöskonto | Debitor | H | business-row BU |
| Journal Entry purchase | Aufwand | Kreditor | S | business-row BU |

Ownership:

- **SI/PI:** grouping owns Konto/Gegenkonto/BU/Umsatz; Mapping is metadata (Both).
- **PI settlement rows:** ERPNext posts Is Paid payments and write-offs on the invoice itself; grouping emits them as extra rows (`base_paid_amount` / `base_write_off_amount`, same Belegfeld 1 as the invoice). Negative amounts (paid returns) flip to H.
- **PE/JE:** Mapping owns Konto/Gegenkonto/BU; PE uses `custom_datev_*` (party = Personenkonto). Grouping collapses rows and sets S/H (+ JE Umsatz).

See also [export_modes.md](export_modes.md) for fallthrough (9090), Amount Basis, and handoff UI.
