import frappe


FIELD_RENAMES = (
	("Sales Invoice Item", "income_account.account_number"),
	("Purchase Invoice Item", "expense_account.account_number"),
)

OLD_FIELDNAME = "datev_account_no"
NEW_FIELDNAME = "custom_datev_account_no"
SECTION_FIELDNAME = "datev_settings_section"
END_SECTION_FIELDNAME = "datev_settings_end_section"


def execute():
	for doctype, fetch_from in FIELD_RENAMES:
		rename_or_merge_field(doctype, fetch_from)
		update_section_fields(doctype)

	frappe.clear_cache()


def rename_or_merge_field(doctype, fetch_from):
	old_name = f"{doctype}-{OLD_FIELDNAME}"
	new_name = f"{doctype}-{NEW_FIELDNAME}"
	old_exists = frappe.db.exists("Custom Field", old_name)
	new_exists = frappe.db.exists("Custom Field", new_name)
	old_column_exists = has_column(doctype, OLD_FIELDNAME)
	new_column_exists = has_column(doctype, NEW_FIELDNAME)

	if old_column_exists and new_column_exists:
		copy_field_values(doctype)
	elif old_column_exists and not new_column_exists:
		frappe.db.rename_column(doctype, OLD_FIELDNAME, NEW_FIELDNAME)

	if not old_exists and not new_exists:
		return

	if old_exists and not new_exists:
		frappe.rename_doc("Custom Field", old_name, new_name, force=True, merge=False)
		frappe.db.set_value(
			"Custom Field",
			new_name,
			{
				"fieldname": NEW_FIELDNAME,
				"fetch_from": fetch_from,
			},
			update_modified=False,
		)
		return

	if old_exists and new_exists:
		copy_field_values(doctype)
		frappe.delete_doc("Custom Field", old_name, force=True, ignore_permissions=True)

	frappe.db.set_value(
		"Custom Field",
		new_name,
		{
			"fieldname": NEW_FIELDNAME,
			"fetch_from": fetch_from,
		},
		update_modified=False,
	)


def update_section_fields(doctype):
	section_name = f"{doctype}-{SECTION_FIELDNAME}"
	if frappe.db.exists("Custom Field", section_name):
		frappe.db.set_value(
			"Custom Field",
			section_name,
			"label",
			"DATEV",
			update_modified=False,
		)

	end_section_name = f"{doctype}-{END_SECTION_FIELDNAME}"
	if frappe.db.exists("Custom Field", end_section_name):
		frappe.db.set_value(
			"Custom Field",
			end_section_name,
			"insert_after",
			NEW_FIELDNAME,
			update_modified=False,
		)


def copy_field_values(doctype):
	if not has_column(doctype, OLD_FIELDNAME) or not has_column(doctype, NEW_FIELDNAME):
		return

	table = f"`tab{doctype}`"
	frappe.db.sql(
		f"""
		UPDATE {table}
		SET `{NEW_FIELDNAME}` = `{OLD_FIELDNAME}`
		WHERE COALESCE(`{NEW_FIELDNAME}`, '') = ''
			AND COALESCE(`{OLD_FIELDNAME}`, '') != ''
		"""
	)


def has_column(doctype, fieldname):
	return fieldname in frappe.db.get_table_columns(doctype)
