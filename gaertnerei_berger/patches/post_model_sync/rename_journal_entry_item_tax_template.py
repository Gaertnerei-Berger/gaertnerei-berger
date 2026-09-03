import frappe
from frappe.model.utils.rename_field import rename_field


def execute():
	"""Rename Journal Entry Account custom_datev_tax_template → custom_item_tax_template."""
	old_fieldname = "custom_datev_tax_template"
	new_fieldname = "custom_item_tax_template"
	old_cf = "Journal Entry Account-custom_datev_tax_template"
	new_cf = "Journal Entry Account-custom_item_tax_template"

	has_old_col = frappe.db.has_column("Journal Entry Account", old_fieldname)
	has_new_col = frappe.db.has_column("Journal Entry Account", new_fieldname)
	old_cf_exists = frappe.db.exists("Custom Field", old_cf)
	new_cf_exists = frappe.db.exists("Custom Field", new_cf)

	# Both custom fields present: copy data, drop old CF (+ orphan column)
	if old_cf_exists and new_cf_exists:
		if has_old_col and has_new_col:
			frappe.db.sql(
				f"""
				UPDATE `tabJournal Entry Account`
				SET `{new_fieldname}` = `{old_fieldname}`
				WHERE IFNULL(`{new_fieldname}`, '') = ''
					AND IFNULL(`{old_fieldname}`, '') != ''
				"""
			)
		frappe.delete_doc("Custom Field", old_cf, force=True, ignore_permissions=True)
		_drop_orphan_column(old_fieldname)

	# Orphan column left after CF rename/delete on a prior migrate attempt
	elif not old_cf_exists and has_old_col and has_new_col:
		frappe.db.sql(
			f"""
			UPDATE `tabJournal Entry Account`
			SET `{new_fieldname}` = `{old_fieldname}`
			WHERE IFNULL(`{new_fieldname}`, '') = ''
				AND IFNULL(`{old_fieldname}`, '') != ''
			"""
		)
		_drop_orphan_column(old_fieldname)

	# Only old CF: rename field + custom field doc
	elif old_cf_exists and not new_cf_exists:
		if has_old_col and not has_new_col:
			rename_field("Journal Entry Account", old_fieldname, new_fieldname)
		elif has_old_col and has_new_col:
			frappe.db.sql(
				f"""
				UPDATE `tabJournal Entry Account`
				SET `{new_fieldname}` = `{old_fieldname}`
				WHERE IFNULL(`{new_fieldname}`, '') = ''
					AND IFNULL(`{old_fieldname}`, '') != ''
				"""
			)
			_drop_orphan_column(old_fieldname)

		# rename_field updates fieldname on Custom Field but may leave name as old
		if frappe.db.exists("Custom Field", old_cf):
			frappe.rename_doc("Custom Field", old_cf, new_cf, force=True)
			frappe.db.set_value(
				"Custom Field",
				new_cf,
				{"fieldname": new_fieldname, "label": "Item Tax Template"},
				update_modified=False,
			)
		elif frappe.db.exists("Custom Field", new_cf):
			frappe.db.set_value(
				"Custom Field",
				new_cf,
				{"fieldname": new_fieldname, "label": "Item Tax Template"},
				update_modified=False,
			)

	# Update BU fetch_from / insert_after regardless
	bu_field = "Journal Entry Account-custom_bu_schlussel"
	if frappe.db.exists("Custom Field", bu_field):
		frappe.db.set_value(
			"Custom Field",
			bu_field,
			{
				"fetch_from": f"{new_fieldname}.custom_bu_schlussel",
				"insert_after": new_fieldname,
			},
			update_modified=False,
		)

	frappe.clear_cache(doctype="Journal Entry Account")


def _drop_orphan_column(fieldname):
	if not frappe.db.has_column("Journal Entry Account", fieldname):
		return
	frappe.db.commit()
	frappe.db.sql_ddl(f"ALTER TABLE `tabJournal Entry Account` DROP COLUMN `{fieldname}`")
