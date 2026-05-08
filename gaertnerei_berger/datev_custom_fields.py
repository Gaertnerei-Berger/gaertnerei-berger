import frappe


ITEM_TAX_TEMPLATE_DOCTYPE = "Item Tax Template"
SALES_INVOICE_ITEM_DOCTYPE = "Sales Invoice Item"
PURCHASE_INVOICE_ITEM_DOCTYPE = "Purchase Invoice Item"

ITEM_TAX_TEMPLATE_SECTION = "Item Tax Template-custom_datev_section"
ITEM_TAX_TEMPLATE_BU_FIELD = "Item Tax Template-custom_bu_schlussel"
JOURNAL_ENTRY_ACCOUNT_SECTION = "Journal Entry Account-custom_datev_section"
JOURNAL_ENTRY_ACCOUNT_ACCOUNT_NO_FIELD = "Journal Entry Account-custom_datev_account_no"
JOURNAL_ENTRY_ACCOUNT_CODE_FIELD = "Journal Entry Account-custom_datev_code"
SALES_INVOICE_ITEM_SECTION = "Sales Invoice Item-datev_settings_section"
SALES_INVOICE_ITEM_BU_FIELD = "Sales Invoice Item-custom_bu_schlussel"
SALES_INVOICE_ITEM_END_SECTION = "Sales Invoice Item-datev_settings_end_section"
PURCHASE_INVOICE_ITEM_SECTION = "Purchase Invoice Item-datev_settings_section"
PURCHASE_INVOICE_ITEM_BU_FIELD = "Purchase Invoice Item-custom_bu_schlussel"
PURCHASE_INVOICE_ITEM_END_SECTION = "Purchase Invoice Item-datev_settings_end_section"

BU_FIELDNAME = "custom_bu_schlussel"
BU_FETCH_FROM = "item_tax_template.custom_bu_schlussel"
DATEV_ACCOUNT_NO_FIELDNAME = "custom_datev_account_no"
DATEV_CODE_FIELDNAME = "custom_datev_code"


def after_migrate():
	sync_field_metadata()
	backfill_invoice_item_bu_schlussel(SALES_INVOICE_ITEM_DOCTYPE)
	backfill_invoice_item_bu_schlussel(PURCHASE_INVOICE_ITEM_DOCTYPE)
	frappe.clear_cache()


def sync_field_metadata():
	update_custom_field(
		ITEM_TAX_TEMPLATE_SECTION,
		{
			"fieldname": "custom_datev_section",
			"insert_after": "disabled",
			"label": "DATEV",
		},
	)
	update_custom_field(
		ITEM_TAX_TEMPLATE_BU_FIELD,
		{
			"fieldname": BU_FIELDNAME,
			"insert_after": "custom_datev_section",
			"label": "BU-Schlüssel",
		},
	)
	update_custom_field(
		JOURNAL_ENTRY_ACCOUNT_SECTION,
		{
			"fieldname": "custom_datev_section",
			"insert_after": "against_account",
			"label": "DATEV",
		},
	)
	update_custom_field(
		JOURNAL_ENTRY_ACCOUNT_ACCOUNT_NO_FIELD,
		{
			"fieldname": DATEV_ACCOUNT_NO_FIELDNAME,
			"fetch_from": "account.account_number",
			"fetch_if_empty": 1,
			"insert_after": "custom_datev_section",
			"label": "DATEV Account No",
			"read_only": 1,
		},
	)
	update_custom_field(
		JOURNAL_ENTRY_ACCOUNT_CODE_FIELD,
		{
			"fieldname": DATEV_CODE_FIELDNAME,
			"insert_after": DATEV_ACCOUNT_NO_FIELDNAME,
			"label": "DATEV Code",
		},
	)
	update_custom_field(
		SALES_INVOICE_ITEM_SECTION,
		{
			"label": "DATEV",
		},
	)
	update_custom_field(
		SALES_INVOICE_ITEM_BU_FIELD,
		{
			"fieldname": BU_FIELDNAME,
			"fetch_from": BU_FETCH_FROM,
			"fetch_if_empty": 1,
			"insert_after": "custom_datev_account_no",
			"label": "BU-Schlüssel",
			"read_only": 1,
		},
	)
	update_custom_field(
		SALES_INVOICE_ITEM_END_SECTION,
		{
			"insert_after": BU_FIELDNAME,
		},
	)
	update_custom_field(
		PURCHASE_INVOICE_ITEM_SECTION,
		{
			"label": "DATEV",
		},
	)
	update_custom_field(
		PURCHASE_INVOICE_ITEM_BU_FIELD,
		{
			"fieldname": BU_FIELDNAME,
			"fetch_from": BU_FETCH_FROM,
			"fetch_if_empty": 1,
			"insert_after": "custom_datev_account_no",
			"label": "BU-Schlüssel",
			"read_only": 1,
		},
	)
	update_custom_field(
		PURCHASE_INVOICE_ITEM_END_SECTION,
		{
			"insert_after": BU_FIELDNAME,
		},
	)


def update_custom_field(custom_field_name, values):
	if not frappe.db.exists("Custom Field", custom_field_name):
		return

	frappe.db.set_value("Custom Field", custom_field_name, values, update_modified=False)


def backfill_invoice_item_bu_schlussel(invoice_item_doctype):
	if not has_column(ITEM_TAX_TEMPLATE_DOCTYPE, BU_FIELDNAME):
		return

	if not has_column(invoice_item_doctype, BU_FIELDNAME):
		return

	if not has_column(invoice_item_doctype, "item_tax_template"):
		return

	frappe.db.sql(
		f"""
		UPDATE `tab{invoice_item_doctype}` invoice_item
		INNER JOIN `tab{ITEM_TAX_TEMPLATE_DOCTYPE}` itt
			ON itt.name = invoice_item.item_tax_template
		SET invoice_item.`{BU_FIELDNAME}` = itt.`{BU_FIELDNAME}`
		WHERE COALESCE(invoice_item.`{BU_FIELDNAME}`, '') = ''
			AND COALESCE(itt.`{BU_FIELDNAME}`, '') != ''
		"""
	)


def has_column(doctype, fieldname):
	return fieldname in frappe.db.get_table_columns(doctype)
