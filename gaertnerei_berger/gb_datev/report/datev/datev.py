"""
Provide a report and downloadable CSV according to the German DATEV format.

- Query report showing only the columns that contain data, formatted nicely for
	dispay to the user.
- CSV download functionality `download_datev_csv` that provides a CSV file with
	all required columns. Used to import the data into the DATEV Software.
"""

import json
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP

import frappe
from erpnext.accounts.utils import get_fiscal_year
from frappe import _

from gaertnerei_berger.utils.datev_constants import (
	AccountNames,
	DebtorsCreditors,
	Transactions,
)
from gaertnerei_berger.utils.datev_csv import get_datev_csv, zip_and_download

BUCHUNGSSTAPEL_REPORT = "EXTF_Buchungsstapel.csv"

COLUMNS = [
	{
		"label": "Umsatz (ohne Soll/Haben-Kz)",
		"fieldname": "Umsatz (ohne Soll/Haben-Kz)",
		"fieldtype": "Currency",
		"width": 100,
	},
	{
		"label": "Soll/Haben-Kennzeichen",
		"fieldname": "Soll/Haben-Kennzeichen",
		"fieldtype": "Data",
		"width": 100,
	},
	{"label": "Konto", "fieldname": "Konto", "fieldtype": "Data", "width": 100},
	{
		"label": "Gegenkonto (ohne BU-Schlüssel)",
		"fieldname": "Gegenkonto (ohne BU-Schlüssel)",
		"fieldtype": "Data",
		"width": 100,
	},
	{
		"label": "BU-Schlüssel",
		"fieldname": "BU-Schlüssel",
		"fieldtype": "Data",
		"width": 100,
	},
	{
		"label": "Belegdatum",
		"fieldname": "Belegdatum",
		"fieldtype": "Date",
		"width": 100,
	},
	{
		"label": "Belegfeld 1",
		"fieldname": "Belegfeld 1",
		"fieldtype": "Data",
		"width": 150,
	},
	{
		"label": "Buchungstext",
		"fieldname": "Buchungstext",
		"fieldtype": "Text",
		"width": 300,
	},
	{
		"label": "Beleginfo - Art 1",
		"fieldname": "Beleginfo - Art 1",
		"fieldtype": "Link",
		"options": "DocType",
		"width": 100,
	},
	{
		"label": "Beleginfo - Inhalt 1",
		"fieldname": "Beleginfo - Inhalt 1",
		"fieldtype": "Dynamic Link",
		"options": "Beleginfo - Art 1",
		"width": 150,
	},
	{
		"label": "Beleginfo - Art 2",
		"fieldname": "Beleginfo - Art 2",
		"fieldtype": "Link",
		"options": "DocType",
		"width": 100,
	},
	{
		"label": "Beleginfo - Inhalt 2",
		"fieldname": "Beleginfo - Inhalt 2",
		"fieldtype": "Dynamic Link",
		"options": "Beleginfo - Art 2",
		"width": 150,
	},
	{
		"label": "Beleginfo - Art 3",
		"fieldname": "Beleginfo - Art 3",
		"fieldtype": "Link",
		"options": "DocType",
		"width": 100,
	},
	{
		"label": "Beleginfo - Inhalt 3",
		"fieldname": "Beleginfo - Inhalt 3",
		"fieldtype": "Dynamic Link",
		"options": "Beleginfo - Art 3",
		"width": 150,
	},
	{
		"label": "Beleginfo - Art 4",
		"fieldname": "Beleginfo - Art 4",
		"fieldtype": "Data",
		"width": 100,
	},
	{
		"label": "Beleginfo - Inhalt 4",
		"fieldname": "Beleginfo - Inhalt 4",
		"fieldtype": "Data",
		"width": 150,
	},
	{
		"label": "Beleginfo - Art 5",
		"fieldname": "Beleginfo - Art 5",
		"fieldtype": "Data",
		"width": 150,
	},
	{
		"label": "Beleginfo - Inhalt 5",
		"fieldname": "Beleginfo - Inhalt 5",
		"fieldtype": "Data",
		"width": 100,
	},
	{
		"label": "Beleginfo - Art 6",
		"fieldname": "Beleginfo - Art 6",
		"fieldtype": "Data",
		"width": 150,
	},
	{
		"label": "Beleginfo - Inhalt 6",
		"fieldname": "Beleginfo - Inhalt 6",
		"fieldtype": "Date",
		"width": 100,
	},
	{
		"label": "Fälligkeit",
		"fieldname": "Fälligkeit",
		"fieldtype": "Date",
		"width": 100,
	},
]


def execute(filters=None):
	"""Entry point for frappe."""
	data = []
	if filters and validate(filters):
		temp, opening = frappe.get_value(
			"DATEV Settings",
			filters.get("company"),
			["temporary_against_account_number", "opening_against_account_number"],
		)
		filters.update({"against_account": temp, "opening_account": opening or temp})
		data = get_transactions(filters)
		data = group_sales_invoice_buchungsstapel(data, filters)
		data = group_payment_entry_buchungsstapel(data, filters)
		data = group_journal_entry_buchungsstapel(data, filters)
		data = apply_buchungsstapel_mapping(data, filters)
		data = [[row.get(column.get("fieldname")) for column in COLUMNS] for row in data]

	return COLUMNS, data


def validate(filters):
	"""Make sure all mandatory filters and settings are present."""
	company = filters.get("company")
	if not company:
		frappe.throw(_("<b>Company</b> is a mandatory filter."))

	from_date = filters.get("from_date")
	if not from_date:
		frappe.throw(_("<b>From Date</b> is a mandatory filter."))

	to_date = filters.get("to_date")
	if not to_date:
		frappe.throw(_("<b>To Date</b> is a mandatory filter."))

	validate_fiscal_year(from_date, to_date, company)

	if not frappe.db.exists("DATEV Settings", filters.get("company")):
		msg = _("Please create DATEV Settings for Company {}").format(filters.get("company"))
		frappe.log_error(message=msg, title=_("DATEV Settings missing"))
		return False

	return True


def validate_fiscal_year(from_date, to_date, company):
	from_fiscal_year = get_fiscal_year(date=from_date, company=company)
	to_fiscal_year = get_fiscal_year(date=to_date, company=company)
	if from_fiscal_year != to_fiscal_year:
		frappe.throw(_("Dates {} and {} are not in the same fiscal year.").format(from_date, to_date))


def get_transactions(filters, as_dict=1):
	def run(params_method, filters):
		extra_fields, extra_joins, extra_filters = params_method(filters)
		return run_query(filters, extra_fields, extra_joins, extra_filters, as_dict=as_dict)

	def sort_by(row):
		# "Belegdatum" is in the fifth column when list format is used
		return row["Belegdatum" if as_dict else 5]

	type_map = {
		# specific query methods for some voucher types
		"Payment Entry": get_payment_entry_params,
		"Sales Invoice": get_sales_invoice_params,
		"Purchase Invoice": get_purchase_invoice_params,
	}

	only_voucher_type = filters.get("voucher_type")
	transactions = []

	for voucher_type, get_voucher_params in type_map.items():
		if only_voucher_type and only_voucher_type != voucher_type:
			continue

		transactions.extend(run(params_method=get_voucher_params, filters=filters))

	if not only_voucher_type or only_voucher_type not in type_map:
		# generic query method for all other voucher types
		filters["exclude_voucher_types"] = type_map.keys()
		transactions.extend(run(params_method=get_generic_params, filters=filters))

	return sorted(transactions, key=sort_by)


def group_sales_invoice_buchungsstapel(transactions, filters):
	"""
	Replace raw invoice GL rows with grouped invoice-item rows.

	The customer expects one Buchungsstapel row per invoice item account group,
	not one row per GL Entry row. Items sharing the same DATEV account and BU key
	are combined into one export line.
	"""
	if not transactions:
		return transactions

	grouped_transactions = []
	invoice_rows_by_voucher = {}

	for row in transactions:
		voucher_type = row.get("Beleginfo - Art 1")
		if voucher_type in {"Sales Invoice", "Purchase Invoice"} and row.get("Belegfeld 1"):
			invoice_rows_by_voucher.setdefault((voucher_type, row.get("Belegfeld 1")), []).append(row)
			continue

		grouped_transactions.append(row)

	for (voucher_type, voucher_no), voucher_rows in invoice_rows_by_voucher.items():
		grouped_transactions.extend(
			get_grouped_invoice_rows(voucher_type, voucher_no, voucher_rows, filters)
		)

	return sorted(grouped_transactions, key=lambda row: row.get("Belegdatum"))


def get_grouped_invoice_rows(voucher_type, voucher_no, voucher_rows, filters):
	voucher_doc = load_voucher_doc(voucher_type, voucher_no)
	if not voucher_doc:
		return voucher_rows

	base_row = get_invoice_base_row(voucher_rows)
	gegenkonto = get_invoice_gegenkonto(voucher_type, voucher_doc, base_row, filters)
	grouped_rows = {}

	for item in voucher_doc.get("items") or []:
		konto = get_invoice_item_konto(voucher_type, item, filters.get("company"))
		if not konto:
			continue

		amount = get_invoice_item_amount(item)
		if amount == 0:
			continue

		bu_schluessel = item.get("custom_bu_schlussel") or ""
		tax_grouping_key = get_invoice_item_tax_grouping_key(item)
		group_key = (konto, tax_grouping_key)

		if group_key not in grouped_rows:
			grouped_rows[group_key] = make_grouped_invoice_row(
				voucher_type=voucher_type,
				base_row=base_row,
				konto=konto,
				gegenkonto=gegenkonto,
				bu_schluessel=bu_schluessel,
				amount=amount,
			)
			continue

		existing_amount = Decimal(str(grouped_rows[group_key]["Umsatz (ohne Soll/Haben-Kz)"]))
		total_amount = existing_amount + amount
		grouped_rows[group_key]["Umsatz (ohne Soll/Haben-Kz)"] = abs(total_amount)
		grouped_rows[group_key]["Soll/Haben-Kennzeichen"] = get_grouped_invoice_amount_indicator(
			voucher_type, total_amount
		)

	if grouped_rows:
		return list(grouped_rows.values())

	return voucher_rows


def get_invoice_base_row(voucher_rows):
	for row in voucher_rows:
		if row.get("Beleginfo - Art 3") in {"Customer", "Supplier"}:
			return dict(row)

	return dict(voucher_rows[0])


def get_invoice_gegenkonto(voucher_type, voucher_doc, base_row, filters):
	if voucher_type == "Sales Invoice":
		return get_party_account_number(
			party_type="Customer",
			party=voucher_doc.customer,
			company=voucher_doc.company,
			primary_account=voucher_doc.debit_to,
			base_row=base_row,
			filters=filters,
		)

	if voucher_type == "Purchase Invoice":
		return get_party_account_number(
			party_type="Supplier",
			party=voucher_doc.supplier,
			company=voucher_doc.company,
			primary_account=voucher_doc.credit_to,
			base_row=base_row,
			filters=filters,
		)

	return base_row.get("Gegenkonto (ohne BU-Schlüssel)") or filters.get("against_account") or ""


def get_party_account_number(party_type, party, company, primary_account, base_row, filters):
	debtor_or_creditor_number = frappe.db.get_value(
		"Party Account",
		{
			"parent": party,
			"parenttype": party_type,
			"company": company,
		},
		"debtor_creditor_number",
	)
	if debtor_or_creditor_number:
		return debtor_or_creditor_number

	account_number = frappe.db.get_value("Account", primary_account, "account_number")
	if account_number:
		return account_number

	return base_row.get("Gegenkonto (ohne BU-Schlüssel)") or filters.get("against_account") or ""


def get_invoice_item_konto(voucher_type, item, company):
	if item.get("custom_datev_account_no"):
		return item.get("custom_datev_account_no")

	account_field = "income_account" if voucher_type == "Sales Invoice" else "expense_account"
	if item.get(account_field):
		account_number = frappe.db.get_value("Account", item.get(account_field), "account_number")
		if account_number:
			return account_number

	if item.get("item_code") and company:
		default_account = frappe.db.get_value(
			"Item Default",
			{"parent": item.get("item_code"), "company": company},
			account_field,
		)
		if default_account:
			return frappe.db.get_value("Account", default_account, "account_number")

	return ""


def get_invoice_item_amount(item):
	amount = item.get("base_net_amount")
	if amount in (None, ""):
		amount = item.get("base_amount")
	if amount in (None, ""):
		amount = item.get("net_amount")
	if amount in (None, ""):
		amount = item.get("amount") or 0

	return Decimal(str(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def get_invoice_item_tax_grouping_key(item):
	parts = []
	for fieldname in ("item_tax_template", "item_tax_rate", "custom_bu_schlussel"):
		value = item.get(fieldname)
		if value in (None, "", {}, []):
			continue

		parts.append("{}:{}".format(fieldname, normalize_invoice_grouping_value(value)))

	return "|".join(parts)


def normalize_invoice_grouping_value(value):
	if isinstance(value, (dict, list)):
		return json.dumps(value, sort_keys=True, separators=(",", ":"))

	return str(value)


def make_grouped_invoice_row(voucher_type, base_row, konto, gegenkonto, bu_schluessel, amount):
	row = dict(base_row)
	row["Umsatz (ohne Soll/Haben-Kz)"] = abs(amount)
	row["Soll/Haben-Kennzeichen"] = get_grouped_invoice_amount_indicator(voucher_type, amount)
	row["Konto"] = konto
	row["Gegenkonto (ohne BU-Schlüssel)"] = gegenkonto
	row["BU-Schlüssel"] = bu_schluessel
	return row


def get_grouped_invoice_amount_indicator(voucher_type, amount):
	if voucher_type == "Purchase Invoice":
		return "S" if amount >= 0 else "H"

	return "H" if amount >= 0 else "S"


def group_payment_entry_buchungsstapel(transactions, filters):
	"""
	Replace raw Payment Entry GL rows with one export row per voucher when safe.

	Bank-driven receive/pay vouchers post one party row and one bank row. DATEV
	export expects those paired entries as one line with account numbers on both
	sides.
	"""
	if not transactions:
		return transactions

	grouped_transactions = []
	payment_rows_by_voucher = {}

	for row in transactions:
		if row.get("Beleginfo - Art 1") == "Payment Entry" and row.get("Belegfeld 1"):
			payment_rows_by_voucher.setdefault(row.get("Belegfeld 1"), []).append(row)
			continue

		grouped_transactions.append(row)

	for voucher_no, voucher_rows in payment_rows_by_voucher.items():
		grouped_transactions.extend(get_grouped_payment_entry_rows(voucher_no, voucher_rows, filters))

	return sorted(grouped_transactions, key=lambda row: row.get("Belegdatum"))


def get_grouped_payment_entry_rows(voucher_no, voucher_rows, filters):
	if len(voucher_rows) != 2:
		return voucher_rows

	voucher_doc = load_voucher_doc("Payment Entry", voucher_no)
	if not voucher_doc or voucher_doc.payment_type not in {"Receive", "Pay"}:
		return voucher_rows

	party_row = get_payment_entry_party_row(voucher_rows, voucher_doc)
	bank_row = next((row for row in voucher_rows if row is not party_row), None)

	konto, gegenkonto = get_payment_entry_export_accounts(
		voucher_doc, party_row, bank_row, filters
	)
	if not konto or not gegenkonto:
		return voucher_rows

	base_row = dict(party_row or voucher_rows[0])
	base_row["Konto"] = konto
	base_row["Gegenkonto (ohne BU-Schlüssel)"] = gegenkonto
	base_row["BU-Schlüssel"] = ""
	return [base_row]


def get_payment_entry_party_row(voucher_rows, voucher_doc):
	for row in voucher_rows:
		if row.get("Beleginfo - Art 3") == voucher_doc.party_type:
			return row

	return None


def get_payment_entry_export_accounts(voucher_doc, party_row, bank_row, filters):
	if voucher_doc.payment_type == "Receive":
		return (
			get_payment_entry_party_or_account_number(
				voucher_doc, voucher_doc.paid_from, party_row, filters
			),
			get_payment_entry_account_number(voucher_doc.paid_to, bank_row),
		)

	if voucher_doc.payment_type == "Pay":
		return (
			get_payment_entry_party_or_account_number(
				voucher_doc, voucher_doc.paid_to, party_row, filters
			),
			get_payment_entry_account_number(voucher_doc.paid_from, bank_row),
		)

	return "", ""


def get_payment_entry_account_number(account_name, fallback_row):
	account_number = ""
	if account_name:
		account_number = frappe.db.get_value("Account", account_name, "account_number")
	if account_number:
		return account_number

	if fallback_row:
		return fallback_row.get("Konto") or ""

	return ""


def get_payment_entry_party_or_account_number(voucher_doc, account_name, fallback_row, filters):
	if voucher_doc.party_type in {"Customer", "Supplier"} and voucher_doc.party:
		return get_party_account_number(
			party_type=voucher_doc.party_type,
			party=voucher_doc.party,
			company=voucher_doc.company,
			primary_account=account_name,
			base_row=fallback_row or {},
			filters=filters,
		)

	return get_payment_entry_account_number(account_name, fallback_row)


def group_journal_entry_buchungsstapel(transactions, filters):
	"""
	Collapse simple sales-like or purchase-like Journal Entries into one DATEV row.

	The supported shape is intentionally narrow: one party row, one revenue/expense
	row, and one tax row. Anything more complex stays as raw GL rows.
	"""
	if not transactions:
		return transactions

	grouped_transactions = []
	journal_rows_by_voucher = {}

	for row in transactions:
		if row.get("Beleginfo - Art 1") == "Journal Entry" and row.get("Belegfeld 1"):
			journal_rows_by_voucher.setdefault(row.get("Belegfeld 1"), []).append(row)
			continue

		grouped_transactions.append(row)

	for voucher_no, voucher_rows in journal_rows_by_voucher.items():
		grouped_transactions.extend(get_grouped_journal_entry_rows(voucher_no, voucher_rows, filters))

	return sorted(grouped_transactions, key=lambda row: row.get("Belegdatum"))


def get_grouped_journal_entry_rows(voucher_no, voucher_rows, filters):
	if len(voucher_rows) != 3:
		return voucher_rows

	voucher_doc = load_voucher_doc("Journal Entry", voucher_no)
	if not voucher_doc:
		return voucher_rows

	party_row, business_row, tax_row = get_qualifying_journal_entry_rows(voucher_doc)
	if not party_row or not business_row or not tax_row:
		return voucher_rows

	bu_schluessel = get_journal_entry_bu_schluessel(tax_row)

	base_row = get_journal_entry_base_row(voucher_rows, party_row)
	konto = get_journal_entry_export_account_number(business_row)
	gegenkonto = get_party_account_number(
		party_type=party_row.get("party_type"),
		party=party_row.get("party"),
		company=voucher_doc.company,
		primary_account=party_row.get("account"),
		base_row=base_row,
		filters=filters,
	)
	if not konto or not gegenkonto:
		return voucher_rows

	grouped_row = dict(base_row)
	grouped_row["Umsatz (ohne Soll/Haben-Kz)"] = abs(get_journal_entry_row_amount(business_row))
	grouped_row["Soll/Haben-Kennzeichen"] = (
		"H" if get_journal_entry_credit_amount(business_row) > 0 else "S"
	)
	grouped_row["Konto"] = konto
	grouped_row["Gegenkonto (ohne BU-Schlüssel)"] = gegenkonto
	grouped_row["BU-Schlüssel"] = bu_schluessel
	return [grouped_row]


def get_qualifying_journal_entry_rows(voucher_doc):
	account_rows = [row for row in (voucher_doc.get("accounts") or []) if has_journal_entry_amount(row)]
	if len(account_rows) != 3:
		return None, None, None

	sales_party_rows = [
		row
		for row in account_rows
		if is_sales_journal_entry_party_row(row)
	]
	if len(sales_party_rows) == 1:
		return match_sales_journal_entry_rows(account_rows, sales_party_rows[0])

	purchase_party_rows = [
		row
		for row in account_rows
		if is_purchase_journal_entry_party_row(row)
	]
	if len(purchase_party_rows) == 1:
		return match_purchase_journal_entry_rows(account_rows, purchase_party_rows[0])

	return None, None, None


def match_sales_journal_entry_rows(account_rows, party_row):
	counter_rows = [row for row in account_rows if row is not party_row and get_journal_entry_credit_amount(row) > 0]
	return match_journal_entry_counter_rows(party_row, counter_rows)


def match_purchase_journal_entry_rows(account_rows, party_row):
	counter_rows = [row for row in account_rows if row is not party_row and get_journal_entry_debit_amount(row) > 0]
	return match_journal_entry_counter_rows(party_row, counter_rows)


def match_journal_entry_counter_rows(party_row, counter_rows):
	if len(counter_rows) != 2:
		return None, None, None

	tax_rows = [row for row in counter_rows if is_journal_entry_tax_row(row)]
	if len(tax_rows) != 1:
		return None, None, None

	tax_row = tax_rows[0]
	business_rows = [row for row in counter_rows if row is not tax_row]
	if len(business_rows) != 1:
		return None, None, None

	return party_row, business_rows[0], tax_row


def is_sales_journal_entry_party_row(row):
	return (
		get_journal_entry_account_type(row.get("account")) == "Receivable"
		and row.get("party_type") == "Customer"
		and bool(row.get("party"))
		and get_journal_entry_debit_amount(row) > 0
		and get_journal_entry_credit_amount(row) == 0
	)


def is_purchase_journal_entry_party_row(row):
	return (
		get_journal_entry_account_type(row.get("account")) == "Payable"
		and row.get("party_type") == "Supplier"
		and bool(row.get("party"))
		and get_journal_entry_credit_amount(row) > 0
		and get_journal_entry_debit_amount(row) == 0
	)


def has_journal_entry_amount(row):
	return get_journal_entry_row_amount(row) > 0


def get_journal_entry_row_amount(row):
	return max(get_journal_entry_debit_amount(row), get_journal_entry_credit_amount(row))


def get_journal_entry_debit_amount(row):
	return Decimal(str(row.get("debit_in_account_currency") or row.get("debit") or 0))


def get_journal_entry_credit_amount(row):
	return Decimal(str(row.get("credit_in_account_currency") or row.get("credit") or 0))


def get_journal_entry_account_type(account_name):
	if not account_name:
		return ""

	return frappe.db.get_value("Account", account_name, "account_type") or ""


def get_journal_entry_export_account_number(row):
	if row.get("custom_datev_account_no"):
		return row.get("custom_datev_account_no")

	if not row.get("account"):
		return ""

	return frappe.db.get_value("Account", row.get("account"), "account_number") or ""


def get_journal_entry_bu_schluessel(row):
	if not row.get("account"):
		return ""

	bu_schluessel_by_account = get_item_tax_template_bu_schluessel_by_account()
	matches = bu_schluessel_by_account.get(row.get("account")) or set()
	if len(matches) != 1:
		return ""

	return next(iter(matches))


def is_journal_entry_tax_row(row):
	account_name = row.get("account")
	if not account_name:
		return False

	return account_name in get_item_tax_template_accounts()


def get_item_tax_template_accounts():
	return set(build_item_tax_template_bu_schluessel_by_account(include_blank=True))


def get_item_tax_template_bu_schluessel_by_account():
	return build_item_tax_template_bu_schluessel_by_account(include_blank=False)


def get_item_tax_template_bu_schluessel_by_tax_rate():
	return build_item_tax_template_bu_schluessel_by_tax_rate(include_blank=False)


def build_item_tax_template_bu_schluessel_by_account(include_blank=False):
	template_rows = frappe.get_all(
		"Item Tax Template",
		fields=["name", "custom_bu_schlussel"],
		limit_page_length=0,
	)
	if not template_rows:
		return {}

	template_meta = frappe.get_meta("Item Tax Template")
	table_fields = [df for df in template_meta.fields if df.fieldtype == "Table" and df.options]
	if not table_fields:
		return {}

	child_meta_cache = {}
	bu_schluessel_by_account = {}

	for template_row in template_rows:
		template_doc = load_voucher_doc("Item Tax Template", template_row.name)
		if not template_doc:
			continue

		for table_df in table_fields:
			if table_df.options not in child_meta_cache:
				child_meta_cache[table_df.options] = frappe.get_meta(table_df.options)
			child_meta = child_meta_cache[table_df.options]
			account_fields = [
				df.fieldname
				for df in child_meta.fields
				if df.fieldtype == "Link" and df.options == "Account"
			]
			if not account_fields:
				continue

			for child_row in template_doc.get(table_df.fieldname) or []:
				for account_field in account_fields:
					account_name = child_row.get(account_field)
					if not account_name:
						continue

					bu_schluessel = template_row.custom_bu_schlussel
					if bu_schluessel in (None, "") and not include_blank:
						continue

					bu_schluessel_by_account.setdefault(account_name, set()).add(
						"" if bu_schluessel in (None, "") else str(bu_schluessel)
					)

	return bu_schluessel_by_account


def build_item_tax_template_bu_schluessel_by_tax_rate(include_blank=False):
	template_rows = frappe.get_all(
		"Item Tax Template",
		fields=["name", "custom_bu_schlussel"],
		limit_page_length=0,
	)
	if not template_rows:
		return {}

	template_meta = frappe.get_meta("Item Tax Template")
	table_fields = [df for df in template_meta.fields if df.fieldtype == "Table" and df.options]
	if not table_fields:
		return {}

	bu_schluessel_by_tax_rate = {}

	for template_row in template_rows:
		template_doc = load_voucher_doc("Item Tax Template", template_row.name)
		if not template_doc:
			continue

		for table_df in table_fields:
			for child_row in template_doc.get(table_df.fieldname) or []:
				tax_rate = normalize_tax_rate_key(child_row.get("tax_rate"))
				if not tax_rate:
					continue

				bu_schluessel = template_row.custom_bu_schlussel
				if bu_schluessel in (None, "") and not include_blank:
					continue

				bu_schluessel_by_tax_rate.setdefault(tax_rate, set()).add(
					"" if bu_schluessel in (None, "") else str(bu_schluessel)
				)

	return bu_schluessel_by_tax_rate


def normalize_tax_rate_key(value):
	if value in (None, ""):
		return ""

	return str(Decimal(str(value)).normalize())


def get_journal_entry_base_row(voucher_rows, party_row):
	for row in voucher_rows:
		if (
			row.get("Beleginfo - Art 3") == party_row.get("party_type")
			and row.get("Beleginfo - Inhalt 3") == party_row.get("party")
		):
			return dict(row)

	return dict(voucher_rows[0])


def get_payment_entry_bu_schluessel(voucher_doc):
	bu_schluessel_values = set()

	for reference in voucher_doc.get("references") or []:
		reference_doctype = reference.get("reference_doctype")
		reference_name = reference.get("reference_name")
		if reference_doctype not in {"Sales Invoice", "Purchase Invoice"} or not reference_name:
			continue

		reference_doc = load_voucher_doc(reference_doctype, reference_name)
		if not reference_doc:
			continue

		for item in reference_doc.get("items") or []:
			bu_schluessel = item.get("custom_bu_schlussel")
			if bu_schluessel not in (None, ""):
				bu_schluessel_values.add(str(bu_schluessel))

	if len(bu_schluessel_values) == 1:
		return next(iter(bu_schluessel_values))

	return ""


def get_payment_entry_params(filters):
	extra_fields = """
		, 'Zahlungsreferenz' as 'Beleginfo - Art 5'
		, pe.reference_no as 'Beleginfo - Inhalt 5'
		, 'Buchungstag' as 'Beleginfo - Art 6'
		, pe.reference_date as 'Beleginfo - Inhalt 6'
		, '' as 'Fälligkeit'
	"""

	extra_joins = """
		LEFT JOIN `tabPayment Entry` pe
		ON gl.voucher_no = pe.name
	"""

	extra_filters = """
		AND gl.voucher_type = 'Payment Entry'
	"""

	return extra_fields, extra_joins, extra_filters


def get_sales_invoice_params(filters):
	extra_fields = """
		, '' as 'Beleginfo - Art 5'
		, '' as 'Beleginfo - Inhalt 5'
		, '' as 'Beleginfo - Art 6'
		, '' as 'Beleginfo - Inhalt 6'
		, si.due_date as 'Fälligkeit'
	"""

	extra_joins = """
		LEFT JOIN `tabSales Invoice` si
		ON gl.voucher_no = si.name
	"""

	extra_filters = """
		AND gl.voucher_type = 'Sales Invoice'
	"""

	return extra_fields, extra_joins, extra_filters


def get_purchase_invoice_params(filters):
	extra_fields = """
		, 'Lieferanten-Rechnungsnummer' as 'Beleginfo - Art 5'
		, pi.bill_no as 'Beleginfo - Inhalt 5'
		, 'Lieferanten-Rechnungsdatum' as 'Beleginfo - Art 6'
		, pi.bill_date as 'Beleginfo - Inhalt 6'
		, pi.due_date as 'Fälligkeit'
	"""

	extra_joins = """
		LEFT JOIN `tabPurchase Invoice` pi
		ON gl.voucher_no = pi.name
	"""

	extra_filters = """
		AND gl.voucher_type = 'Purchase Invoice'
	"""

	return extra_fields, extra_joins, extra_filters


def get_generic_params(filters):
	# produce empty fields so all rows will have the same length
	extra_fields = """
		, '' as 'Beleginfo - Art 5'
		, '' as 'Beleginfo - Inhalt 5'
		, '' as 'Beleginfo - Art 6'
		, '' as 'Beleginfo - Inhalt 6'
		, '' as 'Fälligkeit'
	"""
	extra_joins = ""

	if filters.get("exclude_voucher_types"):
		# exclude voucher types that are queried by a dedicated method
		exclude = "({})".format(", ".join("'{}'".format(key) for key in filters.get("exclude_voucher_types")))
		extra_filters = "AND gl.voucher_type NOT IN {}".format(exclude)

	# if voucher type filter is set, allow only this type
	if filters.get("voucher_type"):
		extra_filters += " AND gl.voucher_type = %(voucher_type)s"

	return extra_fields, extra_joins, extra_filters


def run_query(filters, extra_fields, extra_joins, extra_filters, as_dict=1):
	"""
	Get a list of accounting entries.

	Select GL Entries joined with Account and Party Account in order to get the
	account numbers. Returns a list of accounting entries.

	Arguments:
	filters -- dict of filters to be passed to the sql query
	as_dict -- return as list of dicts [0,1]
	"""
	query = """
		SELECT

			/* either debit or credit amount; always positive */
			case ROUND(gl.debit, 2) when 0 then ROUND(gl.credit, 2) else ROUND(gl.debit, 2) end as 'Umsatz (ohne Soll/Haben-Kz)',

			/* 'H' when credit, 'S' when debit */
			case ROUND(gl.debit, 2) when 0 then 'H' else 'S' end as 'Soll/Haben-Kennzeichen',

			/* account number or, if empty, party account number */
			acc.account_number as 'Konto',

			/* against number or, if empty, party against number */
			CASE gl.is_opening when 'Yes' then %(opening_account)s else %(against_account)s end as 'Gegenkonto (ohne BU-Schlüssel)',

			/* disable automatic VAT deduction */
			'' as 'BU-Schlüssel',

			gl.posting_date as 'Belegdatum',
			gl.voucher_no as 'Belegfeld 1',
			REPLACE(LEFT(gl.remarks, 60), '\n', ' ') as 'Buchungstext',
			gl.voucher_type as 'Beleginfo - Art 1',
			gl.voucher_no as 'Beleginfo - Inhalt 1',
			gl.against_voucher_type as 'Beleginfo - Art 2',
			gl.against_voucher as 'Beleginfo - Inhalt 2',
			gl.party_type as 'Beleginfo - Art 3',
			gl.party as 'Beleginfo - Inhalt 3',
			case gl.party_type when 'Customer' then 'Debitorennummer' when 'Supplier' then 'Kreditorennummer' else NULL end as 'Beleginfo - Art 4',
			par.debtor_creditor_number as 'Beleginfo - Inhalt 4'

			{extra_fields}

		FROM `tabGL Entry` gl

			/* Kontonummer */
			LEFT JOIN `tabAccount` acc
			ON gl.account = acc.name

			LEFT JOIN `tabParty Account` par
			ON par.parent = gl.party
			AND par.parenttype = gl.party_type
			AND par.company = %(company)s

			{extra_joins}

		WHERE gl.company = %(company)s
		AND DATE(gl.posting_date) >= %(from_date)s
		AND DATE(gl.posting_date) <= %(to_date)s

		{extra_filters}

		ORDER BY 'Belegdatum', gl.voucher_no""".format(
		extra_fields=extra_fields, extra_joins=extra_joins, extra_filters=extra_filters
	)

	gl_entries = frappe.db.sql(query, filters, as_dict=as_dict)

	return gl_entries


def apply_buchungsstapel_mapping(transactions, filters):
	"""
	Apply DATEV Mapping only for EXTF_Buchungsstapel export.

	The existing SQL-generated values remain the base behavior. Mapping rows
	override selected columns on a per-voucher basis.
	"""
	if not transactions:
		return transactions

	voucher_types = {
		row.get("Beleginfo - Art 1")
		for row in transactions
		if row.get("Beleginfo - Art 1") and row.get("Belegfeld 1")
	}
	if not voucher_types:
		return transactions

	mappings = get_buchungsstapel_mappings(voucher_types)
	if not mappings:
		return transactions

	account_number_to_name, account_name_to_number = get_account_maps(filters.get("company"))
	voucher_cache = {}
	child_meta_cache = {}

	for row in transactions:
		voucher_type = row.get("Beleginfo - Art 1")
		voucher_no = row.get("Belegfeld 1")
		if not voucher_type or not voucher_no:
			continue

		field_mappings = mappings.get(voucher_type) or []
		if not field_mappings:
			continue

		cache_key = (voucher_type, voucher_no)
		if cache_key not in voucher_cache:
			voucher_cache[cache_key] = load_voucher_doc(voucher_type, voucher_no)

		voucher_doc = voucher_cache.get(cache_key)
		if not voucher_doc:
			continue

		for mapping in field_mappings:
			if not mapping.get("map_to_column") or not mapping.get("map_to_field"):
				continue

			if should_preserve_existing_mapped_value(
				row=row,
				mapping=mapping,
			):
				continue

			value = resolve_map_to_value(
				voucher_doc=voucher_doc,
				map_to_field=mapping.get("map_to_field"),
				transaction_row=row,
				child_meta_cache=child_meta_cache,
				account_number_to_name=account_number_to_name,
				account_name_to_number=account_name_to_number,
			)
			if value is None:
				continue

			row[mapping.get("map_to_column")] = normalize_mapped_value(
				value,
				map_to_column=mapping.get("map_to_column"),
				account_name_to_number=account_name_to_number,
			)

	return transactions


def should_preserve_existing_mapped_value(row, mapping):
	if should_preserve_existing_item_bu_schluessel(row, mapping):
		return True

	return False


def should_preserve_existing_item_bu_schluessel(row, mapping):
	if mapping.get("map_to_column") != "BU-Schlüssel":
		return False

	if row.get("Beleginfo - Art 1") not in {"Sales Invoice", "Purchase Invoice"}:
		return False

	return bool(row.get("BU-Schlüssel"))


def get_buchungsstapel_mappings(voucher_types):
	parent_rows = frappe.get_all(
		"DATEV Mapping",
		filters={"voucher_type": ["in", list(voucher_types)]},
		fields=["name", "voucher_type"],
		limit_page_length=0,
	)
	if not parent_rows:
		return {}

	parents = [row.name for row in parent_rows]
	voucher_type_by_parent = {row.name: row.voucher_type for row in parent_rows}

	child_rows = frappe.get_all(
		"DATEV Mapping Field",
		filters={
			"parent": ["in", parents],
			"parenttype": "DATEV Mapping",
			"report_type": BUCHUNGSSTAPEL_REPORT,
		},
		fields=["parent", "map_to_field", "map_to_column"],
		order_by="idx asc",
		limit_page_length=0,
	)

	mappings = {}
	for row in child_rows:
		voucher_type = voucher_type_by_parent.get(row.parent, row.parent)
		mappings.setdefault(voucher_type, []).append(row)

	return mappings


def get_account_maps(company):
	rows = frappe.get_all(
		"Account",
		filters={"company": company, "is_group": 0},
		fields=["name", "account_number"],
		limit_page_length=0,
	)

	account_number_to_name = {}
	account_name_to_number = {}
	for row in rows:
		if row.account_number:
			account_number_to_name[row.account_number] = row.name
		if row.name and row.account_number:
			account_name_to_number[row.name] = row.account_number

	return account_number_to_name, account_name_to_number


def load_voucher_doc(voucher_type, voucher_no):
	try:
		return frappe.get_doc(voucher_type, voucher_no)
	except frappe.DoesNotExistError:
		return None


def resolve_map_to_value(
	voucher_doc,
	map_to_field,
	transaction_row,
	child_meta_cache,
	account_number_to_name,
	account_name_to_number,
):
	if "." not in map_to_field:
		return voucher_doc.get(map_to_field)

	table_field, child_field = map_to_field.split(".", 1)
	child_rows = voucher_doc.get(table_field) or []
	if not child_rows:
		return None

	table_df = voucher_doc.meta.get_field(table_field)
	if not table_df or not table_df.options:
		return child_rows[0].get(child_field)

	child_doctype = table_df.options
	if child_doctype not in child_meta_cache:
		child_meta_cache[child_doctype] = frappe.get_meta(child_doctype)
	child_meta = child_meta_cache[child_doctype]

	account_fields = [
		df.fieldname for df in child_meta.fields if df.fieldtype == "Link" and df.options == "Account"
	]

	selected_child = select_matching_child_row(
		child_rows=child_rows,
		child_field=child_field,
		account_fields=account_fields,
		transaction_row=transaction_row,
		account_number_to_name=account_number_to_name,
		account_name_to_number=account_name_to_number,
	)

	return selected_child.get(child_field) if selected_child else None


def select_matching_child_row(
	child_rows,
	child_field,
	account_fields,
	transaction_row,
	account_number_to_name,
	account_name_to_number,
):
	if len(child_rows) == 1:
		return child_rows[0]

	konto = transaction_row.get("Konto")
	gegenkonto = transaction_row.get("Gegenkonto (ohne BU-Schlüssel)")

	target_values = {
		konto,
		gegenkonto,
		account_number_to_name.get(konto),
		account_number_to_name.get(gegenkonto),
		account_name_to_number.get(konto),
		account_name_to_number.get(gegenkonto),
	}
	target_values.discard(None)
	target_values.discard("")

	best_row = None
	best_score = -1
	for row in child_rows:
		score = 0
		row_child_value = row.get(child_field)
		if row_child_value in target_values:
			score += 3

		for account_field in account_fields:
			if row.get(account_field) in target_values:
				score += 2

		if score > best_score:
			best_score = score
			best_row = row

	if best_row:
		return best_row

	for row in child_rows:
		if row.get(child_field) is not None:
			return row

	return child_rows[0]


def normalize_mapped_value(value, map_to_column=None, account_name_to_number=None):
	if isinstance(value, datetime):
		return value
	if isinstance(value, date):
		return value
	if (
		map_to_column in {"Konto", "Gegenkonto (ohne BU-Schlüssel)"}
		and account_name_to_number
		and value in account_name_to_number
	):
		return account_name_to_number[value]
	return str(value)


def get_customers(filters):
	"""
	Get a list of Customers.

	Arguments:
	filters -- dict of filters to be passed to the sql query
	"""
	return frappe.db.sql(
		"""
		SELECT

			par.debtor_creditor_number as 'Konto',
			CASE cus.customer_type
				WHEN 'Company' THEN cus.customer_name
				ELSE null
				END as 'Name (Adressatentyp Unternehmen)',
			CASE cus.customer_type
				WHEN 'Individual' THEN TRIM(SUBSTR(cus.customer_name, LOCATE(' ', cus.customer_name)))
				ELSE null
				END as 'Name (Adressatentyp natürl. Person)',
			CASE cus.customer_type
				WHEN 'Individual' THEN SUBSTRING_INDEX(SUBSTRING_INDEX(cus.customer_name, ' ', 1), ' ', -1)
				ELSE null
				END as 'Vorname (Adressatentyp natürl. Person)',
			CASE cus.customer_type
				WHEN 'Individual' THEN '1'
				WHEN 'Company' THEN '2'
				ELSE '0'
				END as 'Adressatentyp',
			adr.address_line1 as 'Straße',
			adr.pincode as 'Postleitzahl',
			adr.city as 'Ort',
			UPPER(country.code) as 'Land',
			adr.address_line2 as 'Adresszusatz',
			adr.email_id as 'E-Mail',
			adr.phone as 'Telefon',
			adr.fax as 'Fax',
			cus.website as 'Internet',
			cus.tax_id as 'Steuernummer'

		FROM `tabCustomer` cus

			left join `tabParty Account` par
			on par.parent = cus.name
			and par.parenttype = 'Customer'
			and par.company = %(company)s

			left join `tabDynamic Link` dyn_adr
			on dyn_adr.link_name = cus.name
			and dyn_adr.link_doctype = 'Customer'
			and dyn_adr.parenttype = 'Address'

			left join `tabAddress` adr
			on adr.name = dyn_adr.parent
			and adr.is_primary_address = '1'

			left join `tabCountry` country
			on country.name = adr.country

		WHERE adr.is_primary_address = '1'
		""",
		filters,
		as_dict=1,
	)


def get_suppliers(filters):
	"""
	Get a list of Suppliers.

	Arguments:
	filters -- dict of filters to be passed to the sql query
	"""
	return frappe.db.sql(
		"""
		SELECT

			par.debtor_creditor_number as 'Konto',
			CASE sup.supplier_type
				WHEN 'Company' THEN sup.supplier_name
				ELSE null
				END as 'Name (Adressatentyp Unternehmen)',
			CASE sup.supplier_type
				WHEN 'Individual' THEN TRIM(SUBSTR(sup.supplier_name, LOCATE(' ', sup.supplier_name)))
				ELSE null
				END as 'Name (Adressatentyp natürl. Person)',
			CASE sup.supplier_type
				WHEN 'Individual' THEN SUBSTRING_INDEX(SUBSTRING_INDEX(sup.supplier_name, ' ', 1), ' ', -1)
				ELSE null
				END as 'Vorname (Adressatentyp natürl. Person)',
			CASE sup.supplier_type
				WHEN 'Individual' THEN '1'
				WHEN 'Company' THEN '2'
				ELSE '0'
				END as 'Adressatentyp',
			adr.address_line1 as 'Straße',
			adr.pincode as 'Postleitzahl',
			adr.city as 'Ort',
			UPPER(country.code) as 'Land',
			adr.address_line2 as 'Adresszusatz',
			adr.email_id as 'E-Mail',
			adr.phone as 'Telefon',
			adr.fax as 'Fax',
			sup.website as 'Internet',
			sup.tax_id as 'Steuernummer',
			case sup.on_hold when 1 then sup.release_date else null end as 'Zahlungssperre bis'

		FROM `tabSupplier` sup

			left join `tabParty Account` par
			on par.parent = sup.name
			and par.parenttype = 'Supplier'
			and par.company = %(company)s

			left join `tabDynamic Link` dyn_adr
			on dyn_adr.link_name = sup.name
			and dyn_adr.link_doctype = 'Supplier'
			and dyn_adr.parenttype = 'Address'

			left join `tabAddress` adr
			on adr.name = dyn_adr.parent
			and adr.is_primary_address = '1'

			left join `tabCountry` country
			on country.name = adr.country

		WHERE adr.is_primary_address = '1'
		""",
		filters,
		as_dict=1,
	)


def get_account_names(filters):
	return frappe.db.sql(
		"""
		SELECT

			account_number as 'Konto',
			LEFT(account_name, 40) as 'Kontenbeschriftung',
			'de-DE' as 'Sprach-ID'

		FROM `tabAccount`
		WHERE company = %(company)s
		AND is_group = 0
		AND account_number != ''
	""",
		filters,
		as_dict=1,
	)


@frappe.whitelist()
def download_datev_csv(filters):
	"""
	Provide accounting entries for download in DATEV format.

	Validate the filters, get the data, produce the CSV file and provide it for
	download. Can be called like this:

	GET /api/method/gaertnerei_berger.gb_datev.report.datev.datev.download_datev_csv

	Arguments / Params:
	filters -- dict of filters to be passed to the sql query
	"""
	frappe.only_for(["Accounts User", "Accounts Manager"])

	if isinstance(filters, str):
		filters = json.loads(filters)

	validate(filters)

	company = filters.get("company")
	fiscal_year = get_fiscal_year(date=filters.get("from_date"), company=company)
	coa = frappe.get_value("Company", company, "chart_of_accounts")
	datev_settings = frappe.get_doc("DATEV Settings", company)

	filters.update(
		{
			"fiscal_year_start": fiscal_year[1],
			"skr": "04" if "SKR04" in coa else ("03" if "SKR03" in coa else ""),
			"account_number_length": datev_settings.account_number_length,
			"against_account": datev_settings.temporary_against_account_number,
			"opening_account": datev_settings.opening_against_account_number
			or datev_settings.temporary_against_account_number,
		}
	)

	transactions = get_transactions(filters)
	transactions = group_sales_invoice_buchungsstapel(transactions, filters)
	transactions = group_payment_entry_buchungsstapel(transactions, filters)
	transactions = group_journal_entry_buchungsstapel(transactions, filters)
	transactions = apply_buchungsstapel_mapping(transactions, filters)
	account_names = get_account_names(filters)
	customers = get_customers(filters)
	suppliers = get_suppliers(filters)

	zip_name = "{} DATEV.zip".format(frappe.utils.datetime.date.today())
	zip_and_download(
		zip_name,
		[
			{
				"file_name": "EXTF_Buchungsstapel.csv",
				"csv_data": get_datev_csv(transactions, filters, csv_class=Transactions),
			},
			{
				"file_name": "EXTF_Kontenbeschriftungen.csv",
				"csv_data": get_datev_csv(account_names, filters, csv_class=AccountNames),
			},
			{
				"file_name": "EXTF_Kunden.csv",
				"csv_data": get_datev_csv(customers, filters, csv_class=DebtorsCreditors),
			},
			{
				"file_name": "EXTF_Lieferanten.csv",
				"csv_data": get_datev_csv(suppliers, filters, csv_class=DebtorsCreditors),
			},
		],
	)
