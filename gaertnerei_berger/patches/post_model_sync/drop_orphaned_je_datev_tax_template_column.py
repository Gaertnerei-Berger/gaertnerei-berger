import frappe


def execute():
	"""Drop orphan custom_datev_tax_template column after rename to custom_item_tax_template."""
	old_fieldname = "custom_datev_tax_template"
	new_fieldname = "custom_item_tax_template"

	if not frappe.db.has_column("Journal Entry Account", old_fieldname):
		return

	if frappe.db.has_column("Journal Entry Account", new_fieldname):
		frappe.db.sql(
			f"""
			UPDATE `tabJournal Entry Account`
			SET `{new_fieldname}` = `{old_fieldname}`
			WHERE IFNULL(`{new_fieldname}`, '') = ''
				AND IFNULL(`{old_fieldname}`, '') != ''
			"""
		)

	frappe.db.commit()
	frappe.db.sql_ddl(f"ALTER TABLE `tabJournal Entry Account` DROP COLUMN `{old_fieldname}`")
