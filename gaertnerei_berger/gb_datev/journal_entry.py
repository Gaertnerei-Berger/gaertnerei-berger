# Copyright (c) 2026, Gaertnerei Berger and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import flt

from gaertnerei_berger.gb_datev.report.datev.datev import (
	get_journal_entry_account_type,
	get_journal_entry_credit_amount,
	get_journal_entry_debit_amount,
	get_journal_entry_row_amount,
	get_qualifying_journal_entry_grouping,
	is_purchase_journal_entry_party_row,
	is_sales_journal_entry_party_row,
)


BUSINESS_ACCOUNT_TYPES = {
	"Income",
	"Expense",
	"Direct Income",
	"Direct Expense",
	"Cost of Goods Sold",
}


def validate_datev_fields(doc, method=None):
	"""Sync auto tax lines, clear invalid BU/ITT on tax rows, validate DATEV readiness."""
	clear_datev_fields_on_tax_rows(doc)
	sync_datev_tax_lines(doc)
	clear_datev_fields_on_tax_rows(doc)
	sync_journal_entry_header_datev_account_no(doc)
	validate_item_tax_templates(doc)
	validate_grouped_journal_entry_bu(doc)


def clear_datev_fields_on_tax_rows(doc):
	for row in doc.get("accounts") or []:
		account_type = get_journal_entry_account_type(row.get("account"))
		if account_type == "Tax":
			row.custom_bu_schlussel = ""
			# Keep template on auto tax rows for bundling identity only
			if not cint_bool(row.get("custom_datev_auto_tax")):
				row.custom_item_tax_template = ""
		elif account_type in {"Receivable", "Payable"}:
			row.custom_item_tax_template = ""
			row.custom_bu_schlussel = ""
			row.custom_datev_auto_tax = 0


def cint_bool(value):
	return int(value or 0) == 1


def validate_item_tax_templates(doc):
	for row in doc.get("accounts") or []:
		template = row.get("custom_item_tax_template")
		if not template or cint_bool(row.get("custom_datev_auto_tax")):
			continue

		account_type = get_journal_entry_account_type(row.get("account"))
		if account_type == "Tax":
			frappe.throw(
				_("Row {0}: Item Tax Template cannot be set on Tax accounts.").format(row.idx)
			)

		details = get_item_tax_template_details(template, doc.company)
		if not details:
			frappe.throw(
				_("Row {0}: Item Tax Template {1} is invalid for company {2}.").format(
					row.idx, template, doc.company
				)
			)

		if details.get("tax_detail_count", 0) != 1:
			frappe.msgprint(
				_(
					"Row {0}: Item Tax Template {1} has {2} tax rows; DATEV export is best-effort and may be wrong. Prefer a single-rate template."
				).format(row.idx, template, details.get("tax_detail_count")),
				indicator="orange",
				alert=True,
			)

		if not row.get("custom_bu_schlussel"):
			row.custom_bu_schlussel = details.get("bu_schluessel") or ""


def validate_grouped_journal_entry_bu(doc):
	party_row, grouped_row_inputs = get_qualifying_journal_entry_grouping(doc)
	if not party_row or not grouped_row_inputs:
		return

	for business_row, _tax_row in grouped_row_inputs:
		if business_row.get("custom_bu_schlussel"):
			continue
		if business_row.get("custom_item_tax_template"):
			continue
		frappe.throw(
			_(
				"Row {0}: set Item Tax Template so BU-Schlüssel can be determined for DATEV export."
			).format(business_row.idx)
		)


def sync_journal_entry_header_datev_account_no(doc):
	"""Set header DATEV Account No from the party row (Debitor/Kreditor), like Sales Invoice."""
	direction = get_journal_entry_datev_direction(doc)
	if not direction:
		doc.custom_datev_account_no = ""
		return

	party_row = None
	for row in doc.get("accounts") or []:
		if direction == "sales" and is_sales_journal_entry_party_row(row):
			party_row = row
			break
		if direction == "purchase" and is_purchase_journal_entry_party_row(row):
			party_row = row
			break

	if not party_row:
		doc.custom_datev_account_no = ""
		return

	party_type = party_row.get("party_type")
	party = party_row.get("party")
	if party_type and party and doc.company:
		debtor_or_creditor_number = frappe.db.get_value(
			"Party Account",
			{
				"parent": party,
				"parenttype": party_type,
				"company": doc.company,
			},
			"debtor_creditor_number",
		)
		if debtor_or_creditor_number:
			doc.custom_datev_account_no = debtor_or_creditor_number
			return

	if party_row.get("account"):
		doc.custom_datev_account_no = (
			frappe.db.get_value("Account", party_row.get("account"), "account_number") or ""
		)
		return

	doc.custom_datev_account_no = ""


def sync_datev_tax_lines(doc):
	"""Rebuild bundled auto tax lines from business rows grouped by Item Tax Template."""
	direction = get_journal_entry_datev_direction(doc)
	business_rows = get_datev_business_rows(doc)

	if not direction or not business_rows:
		remove_auto_tax_rows(doc, keep_templates=set())
		return

	bundles = {}
	for row in business_rows:
		template = row.get("custom_item_tax_template")
		if not template:
			continue

		details = get_item_tax_template_details(template, doc.company)
		if not details or details.get("tax_detail_count", 0) != 1:
			continue

		if not row.get("custom_bu_schlussel"):
			row.custom_bu_schlussel = details.get("bu_schluessel") or ""

		net_amount = flt(get_journal_entry_row_amount(row))
		tax_amount = flt(net_amount * flt(details["tax_rate"]) / 100.0, 2)
		bundle = bundles.setdefault(
			template,
			{
				"template": template,
				"tax_account": details["tax_account"],
				"tax_rate": details["tax_rate"],
				"bu_schluessel": details.get("bu_schluessel") or "",
				"tax_amount": 0.0,
			},
		)
		bundle["tax_amount"] = flt(bundle["tax_amount"] + tax_amount, 2)

	upsert_auto_tax_rows(doc, bundles, direction)
	remove_auto_tax_rows(doc, keep_templates=set(bundles.keys()))
	update_party_row_gross(doc, direction, business_rows, bundles)


def get_journal_entry_datev_direction(doc):
	account_rows = [row for row in (doc.get("accounts") or []) if get_journal_entry_row_amount(row) > 0]
	sales_party_rows = [row for row in account_rows if is_sales_journal_entry_party_row(row)]
	if len(sales_party_rows) == 1:
		return "sales"

	purchase_party_rows = [row for row in account_rows if is_purchase_journal_entry_party_row(row)]
	if len(purchase_party_rows) == 1:
		return "purchase"

	return None


def get_datev_business_rows(doc):
	rows = []
	for row in doc.get("accounts") or []:
		if cint_bool(row.get("custom_datev_auto_tax")):
			continue
		account_type = get_journal_entry_account_type(row.get("account"))
		if account_type == "Tax" or account_type in {"Receivable", "Payable"}:
			continue
		if row.get("custom_item_tax_template") or account_type in BUSINESS_ACCOUNT_TYPES:
			rows.append(row)
	return rows


def upsert_auto_tax_rows(doc, bundles, direction):
	existing_by_template = {
		row.get("custom_item_tax_template"): row
		for row in doc.get("accounts") or []
		if cint_bool(row.get("custom_datev_auto_tax")) and row.get("custom_item_tax_template")
	}

	for template, bundle in bundles.items():
		tax_amount = flt(bundle["tax_amount"], 2)
		if tax_amount <= 0:
			continue

		row = existing_by_template.get(template)
		if not row:
			row = doc.append(
				"accounts",
				{
					"account": bundle["tax_account"],
					"custom_datev_auto_tax": 1,
					"custom_item_tax_template": template,
					"custom_bu_schlussel": "",
				},
			)

		row.account = bundle["tax_account"]
		row.custom_datev_auto_tax = 1
		row.custom_item_tax_template = template
		row.custom_bu_schlussel = ""
		row.party_type = ""
		row.party = ""

		if direction == "sales":
			row.debit_in_account_currency = 0
			row.credit_in_account_currency = tax_amount
			row.debit = 0
			row.credit = tax_amount
		else:
			row.debit_in_account_currency = tax_amount
			row.credit_in_account_currency = 0
			row.debit = tax_amount
			row.credit = 0


def remove_auto_tax_rows(doc, keep_templates):
	to_remove = [
		row
		for row in list(doc.get("accounts") or [])
		if cint_bool(row.get("custom_datev_auto_tax"))
		and row.get("custom_item_tax_template") not in keep_templates
	]
	for row in to_remove:
		doc.remove(row)


def update_party_row_gross(doc, direction, business_rows, bundles):
	party_row = None
	for row in doc.get("accounts") or []:
		if direction == "sales" and is_sales_journal_entry_party_row(row):
			party_row = row
			break
		if direction == "purchase" and is_purchase_journal_entry_party_row(row):
			party_row = row
			break

	# Party row amount check may fail mid-edit; fall back to first matching party type row
	if not party_row:
		for row in doc.get("accounts") or []:
			account_type = get_journal_entry_account_type(row.get("account"))
			if direction == "sales" and account_type == "Receivable" and row.get("party_type") == "Customer":
				party_row = row
				break
			if direction == "purchase" and account_type == "Payable" and row.get("party_type") == "Supplier":
				party_row = row
				break

	if not party_row:
		return

	net_total = sum(flt(get_journal_entry_row_amount(row)) for row in business_rows if row.get("custom_item_tax_template"))
	tax_total = sum(flt(bundle["tax_amount"]) for bundle in bundles.values())
	gross = flt(net_total + tax_total, 2)
	if gross <= 0:
		return

	if direction == "sales":
		party_row.debit_in_account_currency = gross
		party_row.credit_in_account_currency = 0
		party_row.debit = gross
		party_row.credit = 0
	else:
		party_row.debit_in_account_currency = 0
		party_row.credit_in_account_currency = gross
		party_row.debit = 0
		party_row.credit = gross


@frappe.whitelist()
def get_item_tax_template_details(template, company=None):
	"""Return tax account, rate and BU for a single-detail Item Tax Template."""
	if not template:
		return None

	filters = {"name": template}
	if company:
		filters["company"] = company

	template_doc = frappe.db.get_value(
		"Item Tax Template",
		filters,
		["name", "company", "custom_bu_schlussel"],
		as_dict=True,
	)
	if not template_doc:
		return None

	tax_rows = frappe.get_all(
		"Item Tax Template Detail",
		filters={"parent": template_doc.name},
		fields=["tax_type", "tax_rate"],
		order_by="idx asc",
	)

	result = {
		"name": template_doc.name,
		"company": template_doc.company,
		"bu_schluessel": template_doc.custom_bu_schlussel or "",
		"tax_detail_count": len(tax_rows),
		"tax_account": "",
		"tax_rate": 0,
	}
	if tax_rows:
		result["tax_account"] = tax_rows[0].tax_type
		result["tax_rate"] = flt(tax_rows[0].tax_rate)

	return result


@frappe.whitelist()
def sync_journal_entry_datev_tax_lines(doc):
	"""Whitelisted helper for client-side recalc before save."""
	if isinstance(doc, str):
		doc = frappe.parse_json(doc)

	journal_entry = frappe.get_doc(doc)
	sync_datev_tax_lines(journal_entry)
	clear_datev_fields_on_tax_rows(journal_entry)

	return {
		"accounts": [row.as_dict() for row in journal_entry.get("accounts") or []],
		"preview": get_journal_entry_datev_preview(journal_entry),
	}


@frappe.whitelist()
def get_journal_entry_datev_preview(doc):
	if isinstance(doc, str):
		doc = frappe.parse_json(doc)
		doc = frappe.get_doc(doc)

	party_row, grouped_row_inputs = get_qualifying_journal_entry_grouping(doc)
	missing_bu = []
	if grouped_row_inputs:
		for business_row, _tax_row in grouped_row_inputs:
			if not (business_row.get("custom_bu_schlussel") or business_row.get("custom_item_tax_template")):
				missing_bu.append(business_row.idx)

	return {
		"grouped": bool(party_row and grouped_row_inputs),
		"rows": len(grouped_row_inputs or []),
		"missing_bu": missing_bu,
		"direction": get_journal_entry_datev_direction(doc),
		"party_account_type": {
			"sales": "Receivable",
			"purchase": "Payable",
		}.get(get_journal_entry_datev_direction(doc) or "", "Both"),
	}
