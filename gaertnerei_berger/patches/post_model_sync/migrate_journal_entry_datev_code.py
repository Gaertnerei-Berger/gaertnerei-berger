import frappe


def execute():
	"""Copy Journal Entry Account custom_datev_code → custom_bu_schlussel where empty."""
	if not frappe.db.has_column("Journal Entry Account", "custom_datev_code"):
		return
	if not frappe.db.has_column("Journal Entry Account", "custom_bu_schlussel"):
		return

	frappe.db.sql(
		"""
		UPDATE `tabJournal Entry Account`
		SET custom_bu_schlussel = custom_datev_code
		WHERE IFNULL(custom_bu_schlussel, '') = ''
			AND IFNULL(custom_datev_code, '') != ''
		"""
	)
