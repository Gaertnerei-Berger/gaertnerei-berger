# Tax Category (USt / VSt) — internal checklist

Use this when setting up or reviewing **Customer**, **Supplier**, and **Address** records.

## Direction rules

| Record | Allowed Tax Categories | Example |
|--------|------------------------|---------|
| Customer | `* Ust` only | `Inland Ust` |
| Customer address | `* Ust` only | `Inland Ust`, later `EU Ust` |
| Supplier | `* Vst` only | `Inland Vst` |
| Supplier address | `* Vst` only | `Inland Vst`, later `EU Vst` |

Never set `Inland Vst` on a customer or `Inland Ust` on a supplier.

Each Tax Category has a **Tax Category Type**: `Sales` for `* Ust`, `Purchase` for `* Vst`. Sales forms (Quotation, Sales Order, Delivery Note, Sales Invoice, POS, Customer, Sales Taxes Template) only offer Sales categories; purchase forms only offer Purchase categories; Tax Rule follows its own Tax Type. A category with an empty type shows on both sides. This only filters the dropdown; it does not block saving.

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

1. Add Tax Categories: `EU Ust` (Tax Category Type `Sales`), `EU Vst` (`Purchase`).
2. Create direction-specific Item Tax Templates with the correct BU.
3. Add matching rows on Item Group taxes.
4. Set address/party Tax Category on affected customers and suppliers.

## Automatikkonten

Some DATEV accounts already imply the tax (Automatikkonto, marked AM/AV in the Steuerberater's chart, e.g. SKR03 8400 Erlöse 19 % USt or 3300 Wareneingang 7 % VSt). DATEV calculates the tax from the account, so the booking must **not** carry a BU-Schlüssel as well.

1. Get the list of Automatikkonten from the Steuerberater. Do not guess.
2. Open each **Account** and tick **DATEV Automatikkonto**.
3. Keep **Amount Basis = Gross** in DATEV Settings. Saving the account or the settings warns when it is Net.

The Item Tax Template keeps its BU-Schlüssel. The export leaves the BU empty on every row whose Konto or Gegenkonto is a flagged account, also when a DATEV Mapping fills the BU. Receivable, Payable, Bank, Cash and Tax accounts cannot be flagged.

The template's tax rate must match the rate the Automatikkonto implies (no 7 % template on an Erlöse 19 % account). The export does not check this yet.

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

### Transfer without party

A Journal Entry with exactly two rows, no party and no tax row, where both accounts are balance-sheet accounts (Asset/Liability/Equity), exports as **one** DATEV row — for example *Bank an Kasse*: Konto = Soll account (1800), Gegenkonto = Haben account (1600), S/H = S, BU blank. On save the system fills **DATEV Account No** and **DATEV Against Account No** on the header, and **DATEV Mapping** `Journal Entry - Both` maps them to Konto / Gegenkonto. No Item Tax Template is needed. Other party-less shapes (one-to-many, Income/Expense or tax accounts) still export as raw GL rows against the temporary account 9090; the form warns about this in an orange headline.
