import frappe


def execute():
	"""
	Fill the Steuernummer/USt-IdNr fields of existing DATEV Settings (GitLab #114).

	Until now the export always sent Customer/Supplier Tax ID as Steuernummer,
	so that stays the default. A site that already ran the short-lived
	"Tax ID in Master Data" = USt-IdNr setting (!16, develop only) keeps
	sending Tax ID as USt-IdNr. Values already set stay.
	"""
	use_ust_idnr = frappe.db.has_column("DATEV Settings", "master_data_tax_id")
	fields = ["name", "steuernummer_field", "ust_idnr_field"] + (
		["master_data_tax_id"] if use_ust_idnr else []
	)

	for settings in frappe.get_all("DATEV Settings", fields=fields):
		if settings.steuernummer_field or settings.ust_idnr_field:
			continue

		if settings.get("master_data_tax_id") == "USt-IdNr":
			frappe.db.set_value("DATEV Settings", settings.name, "ust_idnr_field", "tax_id")
		else:
			frappe.db.set_value("DATEV Settings", settings.name, "steuernummer_field", "tax_id")
