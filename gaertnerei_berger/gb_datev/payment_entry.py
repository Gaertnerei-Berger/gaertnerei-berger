# Copyright (c) 2026, Gaertnerei Berger and contributors
# For license information, please see license.txt

import frappe

PAYMENT_ENTRY_BU_SCHLUESSEL = {
	"Receive": "80",
	"Pay": "90",
}


def set_datev_fields(doc, method=None):
	"""Populate DATEV export fields on Payment Entry before save."""
	doc.custom_bu_schlussel = PAYMENT_ENTRY_BU_SCHLUESSEL.get(doc.payment_type, "")

	if doc.payment_type == "Receive":
		doc.custom_datev_account_no = get_account_number(doc.paid_from)
		doc.custom_datev_against_account_no = get_account_number(doc.paid_to)
	elif doc.payment_type == "Pay":
		doc.custom_datev_account_no = get_account_number(doc.paid_to)
		doc.custom_datev_against_account_no = get_account_number(doc.paid_from)
	else:
		doc.custom_datev_account_no = ""
		doc.custom_datev_against_account_no = ""


def get_account_number(account):
	if not account:
		return ""

	return frappe.db.get_value("Account", account, "account_number") or ""
