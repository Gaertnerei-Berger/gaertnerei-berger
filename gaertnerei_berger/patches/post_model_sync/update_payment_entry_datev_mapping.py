import frappe

BUCHUNGSSTAPEL_REPORT = "EXTF_Buchungsstapel.csv"

FIELD_REPLACEMENTS = {
	"payment_type": "custom_bu_schlussel",
	"paid_from": "custom_datev_account_no",
	"paid_to": "custom_datev_against_account_no",
}

DEFAULT_PAYMENT_ENTRY_MAPPINGS = [
	{"map_to_field": "paid_amount", "map_to_column": "Umsatz (ohne Soll/Haben-Kz)"},
	{"map_to_field": "custom_datev_account_no", "map_to_column": "Konto"},
	{
		"map_to_field": "custom_datev_against_account_no",
		"map_to_column": "Gegenkonto (ohne BU-Schlüssel)",
	},
	{"map_to_field": "custom_bu_schlussel", "map_to_column": "BU-Schlüssel"},
]


def execute():
	if not frappe.db.exists("DATEV Mapping", "Payment Entry"):
		return

	doc = frappe.get_doc("DATEV Mapping", "Payment Entry")
	changed = False

	for row in doc.mapping_fields:
		if row.report_type != BUCHUNGSSTAPEL_REPORT:
			continue

		replacement = FIELD_REPLACEMENTS.get(row.map_to_field)
		if not replacement:
			continue

		row.map_to_field = replacement
		changed = True

	existing_pairs = {
		(row.report_type, row.map_to_field, row.map_to_column) for row in doc.mapping_fields
	}
	for mapping in DEFAULT_PAYMENT_ENTRY_MAPPINGS:
		key = (BUCHUNGSSTAPEL_REPORT, mapping["map_to_field"], mapping["map_to_column"])
		if key in existing_pairs:
			continue

		doc.append(
			"mapping_fields",
			{
				"report_type": BUCHUNGSSTAPEL_REPORT,
				"map_to_field": mapping["map_to_field"],
				"map_to_column": mapping["map_to_column"],
			},
		)
		changed = True

	if changed:
		doc.save(ignore_permissions=True)
