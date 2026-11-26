# Copyright (c) 2026, Gaertnerei Berger and contributors
# For license information, please see license.txt

"""Customer/Supplier fields that DATEV Settings may name for the Steuernummer and USt-IdNr (GitLab #114)."""

import re

import frappe

PARTY_DOCTYPES = ("Customer", "Supplier")
TAX_ID_FIELDTYPES = ("Data", "Small Text")
FIELDNAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


def is_party_tax_id_field(fieldname):
	"""
	True if fieldname is a text field on both Customer and Supplier.

	The export reads the field from both doctypes with one query, so it must
	exist on both. The name goes into SQL as a column, hence the strict check.
	"""
	if not fieldname or not FIELDNAME_PATTERN.match(fieldname):
		return False

	for doctype in PARTY_DOCTYPES:
		field = frappe.get_meta(doctype).get_field(fieldname)
		if not field or field.fieldtype not in TAX_ID_FIELDTYPES:
			return False
	return True
