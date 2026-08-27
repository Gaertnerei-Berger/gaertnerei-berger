# Copyright (c) 2026, Gaertnerei Berger and contributors
# For license information, please see license.txt

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from gaertnerei_berger.gb_datev.payment_entry import set_datev_fields
from gaertnerei_berger.gb_datev.report.datev.datev import apply_buchungsstapel_mapping


class TestPaymentEntryDatevFields(IntegrationTestCase):
	def test_receive_sets_debitor_bank_and_bu_80(self):
		doc = frappe._dict(
			{
				"payment_type": "Receive",
				"paid_from": "10483 - Customer - GB",
				"paid_to": "1200 - Bank - GB",
			}
		)

		with patch(
			"gaertnerei_berger.gb_datev.payment_entry.get_account_number",
			side_effect=["10483", "1200"],
		):
			set_datev_fields(doc)

		self.assertEqual(doc.custom_bu_schlussel, "80")
		self.assertEqual(doc.custom_datev_account_no, "10483")
		self.assertEqual(doc.custom_datev_against_account_no, "1200")

	def test_pay_sets_kreditor_bank_and_bu_90(self):
		doc = frappe._dict(
			{
				"payment_type": "Pay",
				"paid_from": "1200 - Bank - GB",
				"paid_to": "70001 - Supplier - GB",
			}
		)

		with patch(
			"gaertnerei_berger.gb_datev.payment_entry.get_account_number",
			side_effect=["70001", "1200"],
		):
			set_datev_fields(doc)

		self.assertEqual(doc.custom_bu_schlussel, "90")
		self.assertEqual(doc.custom_datev_account_no, "70001")
		self.assertEqual(doc.custom_datev_against_account_no, "1200")


class TestPaymentEntryDatevMapping(IntegrationTestCase):
	def test_applies_custom_bu_schlussel_from_mapping(self):
		transactions = [
			{
				"Konto": "10483",
				"Gegenkonto (ohne BU-Schlüssel)": "1200",
				"BU-Schlüssel": "",
				"Belegfeld 1": "ACC-PAY-2026-00002",
				"Beleginfo - Art 1": "Payment Entry",
			}
		]

		with (
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.get_buchungsstapel_mappings",
				return_value={
					"Payment Entry": [
						frappe._dict(
							{
								"map_to_field": "custom_bu_schlussel",
								"map_to_column": "BU-Schlüssel",
							}
						),
						frappe._dict(
							{
								"map_to_field": "custom_datev_account_no",
								"map_to_column": "Konto",
							}
						),
						frappe._dict(
							{
								"map_to_field": "custom_datev_against_account_no",
								"map_to_column": "Gegenkonto (ohne BU-Schlüssel)",
							}
						),
					]
				},
			),
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.get_account_maps",
				return_value=({}, {}),
			),
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.load_voucher_doc",
				return_value=frappe._dict(
					{
						"name": "ACC-PAY-2026-00002",
						"custom_bu_schlussel": "80",
						"custom_datev_account_no": "10483",
						"custom_datev_against_account_no": "1200",
					}
				),
			),
		):
			mapped = apply_buchungsstapel_mapping(transactions, {"company": "_Test GmbH"})

		self.assertEqual(mapped[0]["BU-Schlüssel"], "80")
		self.assertEqual(mapped[0]["Konto"], "10483")
		self.assertEqual(mapped[0]["Gegenkonto (ohne BU-Schlüssel)"], "1200")
