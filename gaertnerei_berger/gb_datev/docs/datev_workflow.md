# DATEV Monthly Workflow

Use the **DATEV** page (`/app/datev`) as the main entry point for monthly Steuerberater handoffs.

## Monthly steps

1. Early in the new month, open **DATEV** from the GB DATEV workspace.
2. Confirm the period defaults to the **previous calendar month** (same as the legacy report).
3. Ensure all relevant vouchers for that month are submitted in ERPNext.
4. Review configuration links if needed:
   - DATEV Settings (export mode, 9090 account, BU keys)
   - DATEV Mapping (one or more docs per voucher type: Receivable / Payable / Both — see [export_modes.md](export_modes.md))
   - DATEV Unternehmen Online Settings
5. Click **Create DATEV Export**.
6. Download the ZIP from the created **DATEV Export** record and send it to your Steuerberater.

## Export tracking

Each handoff creates a **DATEV Export** document with:

- Company and period (`from_date` / `to_date`)
- Who exported and when
- Attached ZIP file
- Row count and export mode snapshot

If an export already exists for the same company and period, the page asks for confirmation before creating another file (for example after late voucher corrections).

## Preview

Use **Preview Transactions** on the DATEV page to open the legacy **DATEV** query report for row-level inspection before exporting. The monthly Steuerberater handoff is always the **DATEV Export** ZIP from this page — not a separate report download.

See also [export_modes.md](export_modes.md) and [accepted_export_contract.md](accepted_export_contract.md) for Consultant Booking orientation, Mapping direction, and 9090 fallthrough.
