import frappe


def execute():
	"""Ensure SI/PI directional mapping docs use party_account_type Both."""
	for name in ("Sales Invoice - Both", "Purchase Invoice - Both"):
		if frappe.db.exists("DATEV Mapping", name):
			frappe.db.set_value("DATEV Mapping", name, "party_account_type", "Both")
