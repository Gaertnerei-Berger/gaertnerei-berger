# Tax Category (USt / VSt) — internal checklist

Use this when setting up or reviewing **Customer**, **Supplier**, and **Address** records.

The app does **not** create Tax Categories on install. Create them manually in Desk before assigning them to parties or Item tax rows.

## Initial Tax Categories

Create at least:

| Title | Used for |
|-------|----------|
| `Inland Ust` | Customers / sales (USt) |
| `Inland Vst` | Suppliers / purchase (VSt) |

Add further categories (e.g. `EU Ust`, `EU Vst`) when needed.

## Direction rules

| Record | Allowed Tax Categories | Example |
|--------|------------------------|---------|
| Customer | `* Ust` only | `Inland Ust` |
| Customer address | `* Ust` only | `Inland Ust`, later `EU Ust` |
| Supplier | `* Vst` only | `Inland Vst` |
| Supplier address | `* Vst` only | `Inland Vst`, later `EU Vst` |

Never set `Inland Vst` on a customer or `Inland Ust` on a supplier.

## Party vs address

1. Set **Tax Category on Customer/Supplier** for the usual default.
2. Set **Tax Category on Address** only when this location needs a different tax situation (e.g. DE Inland vs EU B2B).
3. Which address wins is controlled in **Accounts Settings** → *Determine Address Tax Category From* (Billing or Shipping).

## Item / Item Group taxes

For items that are **bought and sold**, configure **Item Group taxes** (preferred) or **Item taxes** with one row per situation × direction:

| Tax Category | Item Tax Template | DATEV BU |
|--------------|-------------------|----------|
| Inland Ust | e.g. DE 19% USt | sales BU (e.g. 9) |
| Inland Vst | e.g. DE 19% VSt | purchase BU |

Each Item Tax Template carries **one** `custom_bu_schlussel`. Direction is selected by Tax Category, not by a separate sales/purchase BU field.

## New tax situation (e.g. EU)

1. Add Tax Categories: `EU Ust`, `EU Vst`.
2. Create direction-specific Item Tax Templates with the correct BU.
3. Add matching rows on Item Group taxes.
4. Set address/party Tax Category on affected customers and suppliers.

## Payment Entry

Payment direction BU (80 receive / 90 pay) is configured in **DATEV Settings**, not via Tax Category.

Export uses **DATEV Mapping** `Payment Entry - Receivable` (Receive) or `Payment Entry - Payable` (Pay) for Konto / Gegenkonto.

## Journal Entry

Journal Entries have no items. Use the same **Item Tax Template** master data on the revenue/expense line:

1. Add a **Customer** (Receivable) or **Supplier** (Payable) party row — this sets sales vs purchase direction and picks **DATEV Mapping** `Journal Entry - Receivable` or `… - Payable`.
2. On each **Income/Expense** line enter the **net** amount and choose **Item Tax Template**.
3. The system sets **BU-Schlüssel** from the template (never on Tax account rows).
4. The system creates/updates a **bundled Tax GL line** for that template and recalculates the party row to **gross**.

| Rule | Detail |
|------|--------|
| Same template on multiple lines | One combined tax posting (bundled) |
| BU-Schlüssel | Only on non-Tax accounts (business lines) |
| Export | One DATEV row per distinct Konto + BU (+ S/H); same key lines are summed |
| Konto / Gegenkonto | From direction-aware DATEV Mapping (same orientation as invoices): **Receivable** JE = Erlöskonto → Debitor; **Payable** JE = Aufwand → Kreditor |
| Amount Basis | DATEV Settings net/gross applies to JE Umsatz like invoices (GL stays net) |
| Template requirement | Prefer exactly one tax row on the Item Tax Template; multi-rate templates **warn** on save (export may be wrong) |

Party Tax Category still guides which template to pick (Inland Ust vs Inland Vst) — same names as on invoice items.
