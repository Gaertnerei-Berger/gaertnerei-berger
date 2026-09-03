# Copyright (c) 2026, Gaertnerei Berger and contributors
# For license information, please see license.txt

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from gaertnerei_berger.gb_datev.payment_entry import set_datev_fields
from gaertnerei_berger.gb_datev.report.datev.datev import apply_buchungsstapel_mapping


class TestPaymentEntryDatevFields(FrappeTestCase):
	def test_receive_sets_bank_debitor_and_bu_from_settings(self):
		doc = frappe._dict(
			{
				"payment_type": "Receive",
				"company": "_Test GmbH",
				"party_type": "Customer",
				"party": "Test Customer",
				"paid_from": "10483 - Customer - GB",
				"paid_to": "1200 - Bank - GB",
			}
		)

		with (
			patch(
				"gaertnerei_berger.gb_datev.payment_entry.get_payment_bu_schluessel",
				return_value="80",
			),
			patch(
				"gaertnerei_berger.gb_datev.payment_entry.get_account_number",
				return_value="1200",
			),
			patch(
				"gaertnerei_berger.gb_datev.payment_entry.get_party_personenkonto",
				return_value="10483",
			),
		):
			set_datev_fields(doc)

		self.assertEqual(doc.custom_bu_schlussel, "80")
		self.assertEqual(doc.custom_datev_account_no, "1200")
		self.assertEqual(doc.custom_datev_against_account_no, "10483")

	def test_pay_sets_kreditor_bank_and_bu_from_settings(self):
		doc = frappe._dict(
			{
				"payment_type": "Pay",
				"company": "_Test GmbH",
				"party_type": "Supplier",
				"party": "Test Supplier",
				"paid_from": "1200 - Bank - GB",
				"paid_to": "70001 - Supplier - GB",
			}
		)

		with (
			patch(
				"gaertnerei_berger.gb_datev.payment_entry.get_payment_bu_schluessel",
				return_value="90",
			),
			patch(
				"gaertnerei_berger.gb_datev.payment_entry.get_account_number",
				return_value="1200",
			),
			patch(
				"gaertnerei_berger.gb_datev.payment_entry.get_party_personenkonto",
				return_value="70001",
			),
		):
			set_datev_fields(doc)

		self.assertEqual(doc.custom_bu_schlussel, "90")
		self.assertEqual(doc.custom_datev_account_no, "70001")
		self.assertEqual(doc.custom_datev_against_account_no, "1200")

	def test_reads_receive_bu_from_datev_settings(self):
		from gaertnerei_berger.gb_datev.payment_entry import get_payment_bu_schluessel

		doc = frappe._dict({"payment_type": "Receive", "company": "_Test GmbH"})

		with (
			patch(
				"gaertnerei_berger.gb_datev.payment_entry.frappe.db.exists",
				return_value=True,
			),
			patch(
				"gaertnerei_berger.gb_datev.payment_entry.frappe.db.get_value",
				return_value="80",
			) as get_value,
		):
			self.assertEqual(get_payment_bu_schluessel(doc), "80")
			get_value.assert_called_once_with("DATEV Settings", "_Test GmbH", "receive_bu_schluessel")

	def test_reads_pay_bu_from_datev_settings(self):
		from gaertnerei_berger.gb_datev.payment_entry import get_payment_bu_schluessel

		doc = frappe._dict({"payment_type": "Pay", "company": "_Test GmbH"})

		with (
			patch(
				"gaertnerei_berger.gb_datev.payment_entry.frappe.db.exists",
				return_value=True,
			),
			patch(
				"gaertnerei_berger.gb_datev.payment_entry.frappe.db.get_value",
				return_value="90",
			) as get_value,
		):
			self.assertEqual(get_payment_bu_schluessel(doc), "90")
			get_value.assert_called_once_with("DATEV Settings", "_Test GmbH", "pay_bu_schluessel")

	def test_blank_bu_when_datev_settings_missing(self):
		from gaertnerei_berger.gb_datev.payment_entry import get_payment_bu_schluessel

		doc = frappe._dict({"payment_type": "Receive", "company": "_Test GmbH"})

		with patch(
			"gaertnerei_berger.gb_datev.payment_entry.frappe.db.exists",
			return_value=False,
		):
			self.assertEqual(get_payment_bu_schluessel(doc), "")


class TestPaymentEntryDatevMapping(FrappeTestCase):
	def test_applies_custom_bu_schlussel_from_mapping(self):
		transactions = [
			{
				"Konto": "",
				"Gegenkonto (ohne BU-Schlüssel)": "",
				"BU-Schlüssel": "",
				"Belegfeld 1": "ACC-PAY-2026-00002",
				"Beleginfo - Art 1": "Payment Entry",
			}
		]

		with (
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.get_buchungsstapel_mappings",
				return_value={
					"Payment Entry": {
						"Receivable": [
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
					}
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
						"payment_type": "Receive",
						"custom_bu_schlussel": "80",
						"custom_datev_account_no": "1200",
						"custom_datev_against_account_no": "10483",
					}
				),
			),
		):
			mapped = apply_buchungsstapel_mapping(transactions, {"company": "_Test GmbH"})

		self.assertEqual(mapped[0]["BU-Schlüssel"], "80")
		self.assertEqual(mapped[0]["Konto"], "1200")
		self.assertEqual(mapped[0]["Gegenkonto (ohne BU-Schlüssel)"], "10483")
