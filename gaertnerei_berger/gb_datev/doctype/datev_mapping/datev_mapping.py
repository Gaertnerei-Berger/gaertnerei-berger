# Copyright (c) 2026, Gaertnerei Berger and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

VOUCHER_TYPE_OPTIONS = [
	"Sales Invoice",
	"Purchase Invoice",
	"Payment Entry",
	"Expense Claim",
	"Payroll Entry",
	"Bank Reconciliation",
	"Asset",
	"Stock Entry",
	"Journal Entry",
]

PARTY_ACCOUNT_TYPE_RECEIVABLE = "Receivable"
PARTY_ACCOUNT_TYPE_PAYABLE = "Payable"
PARTY_ACCOUNT_TYPE_BOTH = "Both"

PARTY_ACCOUNT_TYPE_OPTIONS = [
	PARTY_ACCOUNT_TYPE_RECEIVABLE,
	PARTY_ACCOUNT_TYPE_PAYABLE,
	PARTY_ACCOUNT_TYPE_BOTH,
]

DATEV_REPORT_TYPES = [
	"EXTF_Buchungsstapel.csv",
	"EXTF_Kontenbeschriftungen.csv",
	"EXTF_Kunden.csv",
	"EXTF_Lieferanten.csv",
]

NON_VALUE_FIELD_TYPES = {
	"Section Break",
	"Column Break",
	"Tab Break",
	"Fold",
	"Button",
	"HTML",
	"Table",
	"Table MultiSelect",
	"Heading",
	"Read Only",
	"Image",
	"Geolocation",
}


class DATEVMapping(Document):
	def validate(self):
		self.party_account_type = self.party_account_type or PARTY_ACCOUNT_TYPE_BOTH
		self._validate_unique_voucher_direction()

	def _validate_unique_voucher_direction(self):
		existing = frappe.db.exists(
			"DATEV Mapping",
			{
				"voucher_type": self.voucher_type,
				"party_account_type": self.party_account_type,
				"name": ["!=", self.name],
			},
		)
		if existing:
			frappe.throw(
				_(
					"DATEV Mapping for {0} with Party Account Type {1} already exists ({2})."
				).format(self.voucher_type, self.party_account_type, existing)
			)


@frappe.whitelist()
def get_map_to_field_options(voucher_type: str) -> list[str]:
	"""Return `voucher.field` and `child_table.child_field` options for a voucher type."""
	if not voucher_type:
		return []

	meta = frappe.get_meta(voucher_type)
	options = []

	for field in meta.fields:
		if field.fieldtype in NON_VALUE_FIELD_TYPES:
			continue

		options.append(field.fieldname)

	for table_field in meta.fields:
		if table_field.fieldtype != "Table" or not table_field.options:
			continue

		child_meta = frappe.get_meta(table_field.options)
		for child_field in child_meta.fields:
			if child_field.fieldtype in NON_VALUE_FIELD_TYPES:
				continue
			options.append(f"{table_field.fieldname}.{child_field.fieldname}")

	return sorted(set(options))
