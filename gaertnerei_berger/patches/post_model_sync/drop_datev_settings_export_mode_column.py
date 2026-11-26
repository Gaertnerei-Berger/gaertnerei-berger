import frappe


def execute():
	"""Drop the DATEV Settings Export Mode column; the export is always Consultant Booking (GitLab #117).

	Not named drop_buchungsstapel_export_mode: the closed GitHub PR #22 used that name, and
	sites that ran it then got the column back, so the old Patch Log entry would skip this.
	"""
	if frappe.db.has_column("DATEV Settings", "buchungsstapel_export_mode"):
		frappe.db.sql_ddl("ALTER TABLE `tabDATEV Settings` DROP COLUMN `buchungsstapel_export_mode`")
