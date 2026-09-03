# Gaertnerei Berger

DATEV integration for [ERPNext](https://github.com/frappe/erpnext): Consultant Booking Buchungsstapel export for the Steuerberater, plus optional [DATEV Unternehmen Online](https://www.datev.de/web/de/mydatev/online-anwendungen/datev-unternehmen-online/) email handoff.

## Requirements

- [Frappe](https://github.com/frappe/frappe) / [ERPNext](https://github.com/frappe/erpnext)
- License: GPLv3

## Install

From your bench:

```bash
bench get-app https://github.com/Gaertnerei-Berger/gaertnerei-berger.git
bench --site <site> install-app gaertnerei_berger
bench --site <site> migrate
```

After install, configure in Desk (nothing is seeded automatically):

1. **DATEV Settings** — client/consultant numbers, temporary against account (9090), Amount Basis, Receive/Pay BU.
2. **DATEV Mapping** — field→column maps per voucher type × party account type (see [export_modes.md](gaertnerei_berger/gb_datev/docs/export_modes.md)).
3. **Tax Categories** — e.g. `Inland Ust` / `Inland Vst` (see [tax_category_training.md](gaertnerei_berger/gb_datev/docs/tax_category_training.md)).

## What you get

| Piece | Role |
|-------|------|
| **DATEV page** (`/app/datev`) + **DATEV Export** | Supported monthly Steuerberater handoff (tracked ZIP) |
| **DATEV Settings** | Client / consultant numbers, temporary against account (9090), Amount Basis (net/gross), Receive/Pay BU (80/90) |
| **DATEV Mapping** | Field→column maps keyed by voucher type + party account type (`Receivable` / `Payable` / `Both`) |
| Custom fields | SI / PI / PE / JE + Item Tax Template BU-Schlüssel |
| **GB DATEV** workspace | Desk entry point for settings, mapping, and the DATEV page |

The legacy **DATEV** query report remains available for preview / power users. Production handoff is the DATEV page → DATEV Export ZIP.

## Monthly workflow

1. Open **DATEV** from the GB DATEV workspace (`/app/datev`).
2. Confirm the period (defaults to the previous calendar month).
3. Ensure vouchers for that period are submitted.
4. Click **Create DATEV Export** and download the ZIP from the **DATEV Export** record.

Full steps: [datev_workflow.md](gaertnerei_berger/gb_datev/docs/datev_workflow.md).

## Export contract (v1)

Consultant Booking orientation (submitted vouchers only):

| Voucher | Konto | Gegenkonto | S/H |
|---------|-------|------------|-----|
| Sales Invoice | Erlöskonto | Debitor | H |
| Purchase Invoice | Aufwand | Kreditor | S |
| Payment Entry Receive | Bank | Personenkonto | S |
| Payment Entry Pay | Personenkonto | Bank | S |
| Journal Entry sales | Erlöskonto | Debitor | H |
| Journal Entry purchase | Aufwand | Kreditor | S |

- **SI / PI:** grouping owns Konto / Gegenkonto / BU / Umsatz; Mapping is mostly metadata (`Both`).
- **PE / JE:** Mapping owns Konto / Gegenkonto / BU; PE uses `custom_datev_*` (party side = Personenkonto).
- Ungrouped PE / JE (and other voucher types) may fall through to raw GL with temporary against account **9090** and blank BU — accepted for v1, not blocked.

Details: [accepted_export_contract.md](gaertnerei_berger/gb_datev/docs/accepted_export_contract.md), [export_modes.md](gaertnerei_berger/gb_datev/docs/export_modes.md).

Umsatz decimals in the CSV are always **`,`** (German DATEV).

## Further documentation

- [export_modes.md](gaertnerei_berger/gb_datev/docs/export_modes.md) — Mapping direction, Amount Basis, 9090 fallthrough
- [tax_category_training.md](gaertnerei_berger/gb_datev/docs/tax_category_training.md) — Tax Category / Item Tax Template / Journal Entry DATEV
- [accepted_export_contract.md](gaertnerei_berger/gb_datev/docs/accepted_export_contract.md) — frozen v1 orientation matrix
- [datev_workflow.md](gaertnerei_berger/gb_datev/docs/datev_workflow.md) — monthly handoff

## DATEV Unternehmen Online

Optional email handoff when vouchers are submitted:

1. Open **DATEV Unternehmen Online Settings**.
2. Enable the integration and choose the sending **Email Account**.
3. Add rows for voucher types (e.g. Sales Invoice, Purchase Invoice) with the DATEV target address and whether to add attachments or a print.

Sender address must match the configured Email Account. See the [DATEV Help Center](https://apps.datev.de/help-center/documents/1007550) for target addresses.

## Disclaimer

"DATEV" and "DATEV Unternehmen Online" are trademarks of [DATEV eG](https://www.datev.de/). This integration is not approved or endorsed by DATEV eG.

## License

GPLv3
