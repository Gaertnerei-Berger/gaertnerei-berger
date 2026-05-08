import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from gaertnerei_berger.datev_custom_fields import after_migrate as sync_datev_custom_fields


def after_install():
	make_custom_fields()
	sync_datev_custom_fields()


def make_custom_fields():
	custom_fields = {
		"Party Account": [
			dict(
				fieldname="debtor_creditor_number",
				label="Debtor/Creditor Number",
				fieldtype="Data",
				insert_after="account",
				translatable=0,
			)
		]
	}

	create_custom_fields(custom_fields)
