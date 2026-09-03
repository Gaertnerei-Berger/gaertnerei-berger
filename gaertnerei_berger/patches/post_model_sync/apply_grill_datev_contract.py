import frappe

from gaertnerei_berger.patches.post_model_sync.seed_datev_mapping_records import (
	BUCHUNGSSTAPEL_REPORT,
	get_default_mappings,
	mapping_name,
)


REPLACE_COLUMNS = {
	"Konto",
	"Gegenkonto (ohne BU-Schlüssel)",
	"BU-Schlüssel",
	"Umsatz (ohne Soll/Haben-Kz)",
	"Beleginfo - Inhalt 5",
	"Beleginfo - Inhalt 6",
}


def execute():
	"""Align PE/JE Mapping fields to grill decisions and drop orphan Settings column."""
	_replace_directional_mapping_fields()
	_fix_invoice_both_party_account_type()
	_drop_sales_konto_perspective_column()


def _fix_invoice_both_party_account_type():
	for name in ("Sales Invoice - Both", "Purchase Invoice - Both"):
		if frappe.db.exists("DATEV Mapping", name):
			frappe.db.set_value("DATEV Mapping", name, "party_account_type", "Both")


def _replace_directional_mapping_fields():
	defaults = get_default_mappings()
	for key in (
		("Payment Entry", "Receivable"),
		("Payment Entry", "Payable"),
		("Journal Entry", "Receivable"),
		("Journal Entry", "Payable"),
	):
		voucher_type, party_account_type = key
		name = mapping_name(voucher_type, party_account_type)
		if not frappe.db.exists("DATEV Mapping", name):
			continue

		doc = frappe.get_doc("DATEV Mapping", name)
		desired = defaults.get(key) or []

		kept = [
			row
			for row in doc.mapping_fields
			if not (row.report_type == BUCHUNGSSTAPEL_REPORT and row.map_to_column in REPLACE_COLUMNS)
		]

		doc.set("mapping_fields", [])
		for row in kept:
			doc.append(
				"mapping_fields",
				{
					"report_type": row.report_type,
					"map_to_field": row.map_to_field,
					"map_to_column": row.map_to_column,
				},
			)

		for mapping in desired:
			doc.append(
				"mapping_fields",
				{
					"report_type": BUCHUNGSSTAPEL_REPORT,
					"map_to_field": mapping["map_to_field"],
					"map_to_column": mapping["map_to_column"],
				},
			)

		doc.save(ignore_permissions=True)


def _drop_sales_konto_perspective_column():
	if frappe.db.has_column("DATEV Settings", "sales_konto_perspective"):
		frappe.db.sql_ddl("ALTER TABLE `tabDATEV Settings` DROP COLUMN `sales_konto_perspective`")
