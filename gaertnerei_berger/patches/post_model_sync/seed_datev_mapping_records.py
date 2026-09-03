import frappe

BUCHUNGSSTAPEL_REPORT = "EXTF_Buchungsstapel.csv"


def execute():
	for (voucher_type, party_account_type), mappings in get_default_mappings().items():
		upsert_mapping(voucher_type, mappings, party_account_type=party_account_type)


def mapping_name(voucher_type, party_account_type="Both"):
	return f"{voucher_type} - {party_account_type}"


def upsert_mapping(voucher_type, mappings, party_account_type="Both"):
	name = mapping_name(voucher_type, party_account_type)
	doc = frappe.get_doc("DATEV Mapping", name) if frappe.db.exists("DATEV Mapping", name) else None
	if not doc:
		# Legacy name was voucher_type only
		if frappe.db.exists("DATEV Mapping", voucher_type) and party_account_type == "Both":
			doc = frappe.get_doc("DATEV Mapping", voucher_type)
		else:
			doc = frappe.new_doc("DATEV Mapping")

	doc.voucher_type = voucher_type
	doc.party_account_type = party_account_type

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
	"""Keys are (voucher_type, party_account_type)."""
	return {
		("Sales Invoice", "Both"): [
			{"map_to_field": "due_date", "map_to_column": "Fälligkeit"},
		],
		("Purchase Invoice", "Both"): [
			{"map_to_field": "bill_no", "map_to_column": "Beleginfo - Inhalt 5"},
			{"map_to_field": "bill_date", "map_to_column": "Beleginfo - Inhalt 6"},
			{"map_to_field": "due_date", "map_to_column": "Fälligkeit"},
		],
		("Payment Entry", "Receivable"): [
			{"map_to_field": "paid_amount", "map_to_column": "Umsatz (ohne Soll/Haben-Kz)"},
			{"map_to_field": "custom_datev_account_no", "map_to_column": "Konto"},
			{
				"map_to_field": "custom_datev_against_account_no",
				"map_to_column": "Gegenkonto (ohne BU-Schlüssel)",
			},
			{"map_to_field": "custom_bu_schlussel", "map_to_column": "BU-Schlüssel"},
			{"map_to_field": "reference_no", "map_to_column": "Beleginfo - Inhalt 5"},
			{"map_to_field": "reference_date", "map_to_column": "Beleginfo - Inhalt 6"},
		],
		("Payment Entry", "Payable"): [
			{"map_to_field": "paid_amount", "map_to_column": "Umsatz (ohne Soll/Haben-Kz)"},
			{"map_to_field": "custom_datev_account_no", "map_to_column": "Konto"},
			{
				"map_to_field": "custom_datev_against_account_no",
				"map_to_column": "Gegenkonto (ohne BU-Schlüssel)",
			},
			{"map_to_field": "custom_bu_schlussel", "map_to_column": "BU-Schlüssel"},
			{"map_to_field": "reference_no", "map_to_column": "Beleginfo - Inhalt 5"},
			{"map_to_field": "reference_date", "map_to_column": "Beleginfo - Inhalt 6"},
		],
		("Journal Entry", "Receivable"): [
			{
				"map_to_field": "accounts.custom_datev_account_no",
				"map_to_column": "Konto",
			},
			{"map_to_field": "custom_datev_account_no", "map_to_column": "Gegenkonto (ohne BU-Schlüssel)"},
			{"map_to_field": "accounts.custom_bu_schlussel", "map_to_column": "BU-Schlüssel"},
		],
		("Journal Entry", "Payable"): [
			{
				"map_to_field": "accounts.custom_datev_account_no",
				"map_to_column": "Konto",
			},
			{"map_to_field": "custom_datev_account_no", "map_to_column": "Gegenkonto (ohne BU-Schlüssel)"},
			{"map_to_field": "accounts.custom_bu_schlussel", "map_to_column": "BU-Schlüssel"},
		],
	}
