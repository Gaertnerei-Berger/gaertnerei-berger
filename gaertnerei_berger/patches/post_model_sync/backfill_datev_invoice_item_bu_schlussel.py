import frappe


ITEM_TAX_TEMPLATE_DOCTYPE = "Item Tax Template"
INVOICE_ITEM_DOCTYPES = ("Sales Invoice Item", "Purchase Invoice Item")
FIELDNAME = "custom_bu_schlussel"
ITEM_TAX_TEMPLATE_LINK_FIELDNAME = "item_tax_template"


def execute():
	for invoice_item_doctype in INVOICE_ITEM_DOCTYPES:
		backfill_invoice_item_bu_schlussel(invoice_item_doctype)

	frappe.clear_cache()


def backfill_invoice_item_bu_schlussel(invoice_item_doctype):
	if not has_column(ITEM_TAX_TEMPLATE_DOCTYPE, FIELDNAME):
		return

	if not has_column(invoice_item_doctype, FIELDNAME):
		return

	if not has_column(invoice_item_doctype, ITEM_TAX_TEMPLATE_LINK_FIELDNAME):
		return

	frappe.db.sql(
		f"""
		UPDATE `tab{invoice_item_doctype}` invoice_item
		INNER JOIN `tab{ITEM_TAX_TEMPLATE_DOCTYPE}` itt
			ON itt.name = invoice_item.{ITEM_TAX_TEMPLATE_LINK_FIELDNAME}
		SET invoice_item.`{FIELDNAME}` = itt.`{FIELDNAME}`
		WHERE COALESCE(invoice_item.`{FIELDNAME}`, '') = ''
			AND COALESCE(itt.`{FIELDNAME}`, '') != ''
		"""
	)


def has_column(doctype, fieldname):
	return fieldname in frappe.db.get_table_columns(doctype)
