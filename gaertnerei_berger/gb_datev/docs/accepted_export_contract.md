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
| Journal Entry transfer (no party) | Soll-Konto | Haben-Konto | S | blank |

Ownership:

- **SI/PI:** grouping owns Konto/Gegenkonto/BU/Umsatz; Mapping is metadata (Both).
- **PI settlement rows:** ERPNext posts Is Paid payments and write-offs on the invoice itself; grouping emits them as extra rows (`base_paid_amount` / `base_write_off_amount`, same Belegfeld 1 as the invoice). Negative amounts (paid returns) flip to H.
- **PE/JE:** Mapping owns Konto/Gegenkonto/BU; PE uses `custom_datev_*` (party = Personenkonto). Grouping collapses rows and sets S/H (+ JE Umsatz).
- **PE for several invoices:** one line per allocated invoice / credit note (credit notes flip to H), or one net line, per DATEV Settings **Lines per Payment**. **Belegfeld 1 on Payment Lines** can put the invoice number in Belegfeld 1 for OPOS matching. See [export_modes.md](export_modes.md#payment-lines).
- **JE transfer (no party):** exactly two rows, no party, no tax row, both accounts Asset/Liability/Equity (e.g. Bank an Kasse). Validate fills header `custom_datev_account_no` (Soll) and `custom_datev_against_account_no` (Haben); Mapping `Journal Entry - Both` maps them to Konto/Gegenkonto, like Payment Entry.

See also [export_modes.md](export_modes.md) for fallthrough (9090), Amount Basis, and handoff UI.
