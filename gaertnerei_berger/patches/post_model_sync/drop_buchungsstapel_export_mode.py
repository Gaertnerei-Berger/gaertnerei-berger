import frappe


def execute():
	"""Drop the DATEV Settings Export Mode column; the export is always Consultant Booking (GitLab #117)."""
	if frappe.db.has_column("DATEV Settings", "buchungsstapel_export_mode"):
		frappe.db.sql_ddl("ALTER TABLE `tabDATEV Settings` DROP COLUMN `buchungsstapel_export_mode`")
