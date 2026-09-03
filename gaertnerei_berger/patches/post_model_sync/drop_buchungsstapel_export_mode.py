import frappe


def execute():
	"""Drop obsolete buchungsstapel_export_mode; export is always Consultant Booking."""
	if frappe.db.has_column("DATEV Settings", "buchungsstapel_export_mode"):
		frappe.db.sql_ddl("ALTER TABLE `tabDATEV Settings` DROP COLUMN `buchungsstapel_export_mode`")
