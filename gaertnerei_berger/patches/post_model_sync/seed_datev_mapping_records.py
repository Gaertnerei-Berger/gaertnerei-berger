import frappe

BUCHUNGSSTAPEL_REPORT = "EXTF_Buchungsstapel.csv"


def execute():
	for voucher_type, mappings in get_default_mappings().items():
		upsert_mapping(voucher_type, mappings)


def upsert_mapping(voucher_type, mappings):
	doc = frappe.get_doc("DATEV Mapping", voucher_type) if frappe.db.exists("DATEV Mapping", voucher_type) else None
	if not doc:
		doc = frappe.new_doc("DATEV Mapping")
		doc.voucher_type = voucher_type

	existing_pairs = {(row.report_type, row.map_to_field, row.map_to_column) for row in doc.mapping_fields}
	for mapping in mappings:
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

	doc.save(ignore_permissions=True)


def get_default_mappings():
	return {
		"Sales Invoice": [
			{"map_to_field": "due_date", "map_to_column": "Fälligkeit"},
		],
		"Purchase Invoice": [
			{"map_to_field": "bill_no", "map_to_column": "Beleginfo - Inhalt 5"},
			{"map_to_field": "bill_date", "map_to_column": "Beleginfo - Inhalt 6"},
			{"map_to_field": "due_date", "map_to_column": "Fälligkeit"},
		],
		"Payment Entry": [
			{"map_to_field": "reference_no", "map_to_column": "Beleginfo - Inhalt 5"},
			{"map_to_field": "reference_date", "map_to_column": "Beleginfo - Inhalt 6"},
		],
	}
