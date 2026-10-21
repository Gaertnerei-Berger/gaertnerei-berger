# Copyright (c) 2026, Gaertnerei Berger and contributors
# For license information, please see license.txt

import frappe
from frappe import _


# Party, money and tax accounts never derive tax in DATEV; flagging one would
# strip the BU from payments
NON_AUTOMATIC_ACCOUNT_TYPES = frozenset({"Receivable", "Payable", "Bank", "Cash", "Tax"})


def validate_automatic_account(doc, method=None):
	if doc.get("is_group") or not doc.get("custom_datev_automatic_account"):
		return

	if doc.get("account_type") in NON_AUTOMATIC_ACCOUNT_TYPES:
		frappe.throw(
			_("A {0} account cannot be a DATEV Automatikkonto.").format(_(doc.account_type)),
			title=_("DATEV Automatikkonto"),
		)

	warn_automatic_account_amount_basis(doc)


def warn_automatic_account_amount_basis(doc):
	"""Warn when an Automatikkonto is flagged while the company exports net Umsatz."""
	if not frappe.db.exists("DATEV Settings", doc.company):
		return

	amount_basis = frappe.db.get_value("DATEV Settings", doc.company, "invoice_amount_basis")
	if amount_basis != "gross":
		msgprint_net_amount_basis_warning()


def has_automatic_accounts(company):
	return bool(
		frappe.db.exists(
			"Account",
			{"company": company, "is_group": 0, "custom_datev_automatic_account": 1},
		)
	)


def msgprint_net_amount_basis_warning():
	frappe.msgprint(
		_(
			"DATEV calculates the tax on an Automatikkonto from the gross amount, but the Amount Basis in DATEV Settings is Net. Please check the Amount Basis with your Steuerberater."
		),
		title=_("DATEV Automatikkonto"),
		indicator="orange",
	)
