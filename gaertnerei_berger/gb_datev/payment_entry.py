# Copyright (c) 2026, Gaertnerei Berger and contributors
# For license information, please see license.txt

import frappe


def set_datev_fields(doc, method=None):
	"""Populate DATEV export fields on Payment Entry before save.

	Mapping reads custom_datev_* so preview ≡ export. Party side uses Personenkonto.
	"""
	doc.custom_bu_schlussel = get_payment_bu_schluessel(doc)

	if doc.payment_type == "Receive":
		# Bank on Konto, Debitor (Personenkonto) on Gegenkonto
		doc.custom_datev_account_no = get_account_number(doc.paid_to)
		doc.custom_datev_against_account_no = get_party_personenkonto(doc, fallback_account=doc.paid_from)
	elif doc.payment_type == "Pay":
		# Kreditor (Personenkonto) on Konto, Bank on Gegenkonto
		doc.custom_datev_account_no = get_party_personenkonto(doc, fallback_account=doc.paid_to)
		doc.custom_datev_against_account_no = get_account_number(doc.paid_from)
	else:
		doc.custom_datev_account_no = ""
		doc.custom_datev_against_account_no = ""


def get_party_personenkonto(doc, fallback_account=None):
	"""Prefer Party Account debtor/creditor number, else GL account number."""
	if doc.get("party_type") in {"Customer", "Supplier"} and doc.get("party") and doc.get("company"):
		number = frappe.db.get_value(
			"Party Account",
			{
				"parent": doc.party,
				"parenttype": doc.party_type,
				"company": doc.company,
			},
			"debtor_creditor_number",
		)
		if number:
			return number

	return get_account_number(fallback_account)


def get_payment_bu_schluessel(doc):
	"""Resolve payment BU-Schlüssel from DATEV Settings for the company."""
	if doc.payment_type not in {"Receive", "Pay"}:
		return ""

	company = doc.get("company")
	if not company or not frappe.db.exists("DATEV Settings", company):
		return ""

	fieldname = "receive_bu_schluessel" if doc.payment_type == "Receive" else "pay_bu_schluessel"
	return frappe.db.get_value("DATEV Settings", company, fieldname) or ""


def get_account_number(account):
	if not account:
		return ""

	return frappe.db.get_value("Account", account, "account_number") or ""
