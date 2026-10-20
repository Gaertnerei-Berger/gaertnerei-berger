import frappe

from gaertnerei_berger.patches.post_model_sync.seed_datev_mapping_records import (
	BUCHUNGSSTAPEL_REPORT,
	get_default_mappings,
	mapping_name,
)

KEY = ("Journal Entry", "Both")
OWNED_COLUMNS = {
	"Konto",
	"Gegenkonto (ohne BU-Schlüssel)",
	"BU-Schlüssel",
	"Umsatz (ohne Soll/Haben-Kz)",
}


def execute():
	"""
	Seed 'Journal Entry - Both' for party-less two-row transfers (GitLab #101).

	Header custom_datev_account_no / custom_datev_against_account_no map to
	Konto / Gegenkonto. Any older Konto/Gegenkonto/BU/Umsatz rows on an existing
	Both mapping are replaced so the transfer row stays deterministic; other
	columns are kept.
	"""
	frappe.reload_doc("gb_datev", "doctype", "datev_mapping")
	frappe.reload_doc("gb_datev", "doctype", "datev_mapping_field")

	voucher_type, party_account_type = KEY
	# Reuse a custom-named Both mapping too; DATEV Mapping is unique per direction
	name = frappe.db.exists("DATEV Mapping", mapping_name(voucher_type, party_account_type)) or (
		frappe.db.get_value(
			"DATEV Mapping",
			{"voucher_type": voucher_type, "party_account_type": party_account_type},
			"name",
		)
	)
	doc = frappe.get_doc("DATEV Mapping", name) if name else frappe.new_doc("DATEV Mapping")

	doc.voucher_type = voucher_type
	doc.party_account_type = party_account_type

	kept = [
		row
		for row in doc.mapping_fields
		if not (row.report_type == BUCHUNGSSTAPEL_REPORT and row.map_to_column in OWNED_COLUMNS)
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

	for mapping in get_default_mappings()[KEY]:
		doc.append(
			"mapping_fields",
			{
				"report_type": BUCHUNGSSTAPEL_REPORT,
				"map_to_field": mapping["map_to_field"],
				"map_to_column": mapping["map_to_column"],
			},
		)

	doc.save(ignore_permissions=True)
