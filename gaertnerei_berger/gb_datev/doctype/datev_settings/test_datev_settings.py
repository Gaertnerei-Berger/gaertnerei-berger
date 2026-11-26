from unittest import TestCase
from unittest.mock import patch

import frappe

from gaertnerei_berger.gb_datev.report.datev.datev import (
	AMOUNT_BASIS_NET,
	PAYMENT_BELEGFELD_PAYMENT_ENTRY,
	PAYMENT_LINES_PER_INVOICE,
	UMSATZ_DECIMAL_COMMA,
	get_datev_export_filter_values,
)


class TestDATEVSettings(TestCase):
	def test_filter_values_from_settings_doc(self):
		settings = frappe._dict(
			{
				"temporary_against_account_number": "9090",
				"opening_against_account_number": "9000",
				"invoice_amount_basis": AMOUNT_BASIS_NET,
			}
		)

		with patch(
			"gaertnerei_berger.gb_datev.report.datev.datev.frappe.get_cached_doc",
			return_value=settings,
		):
			filter_values = get_datev_export_filter_values("_Test GmbH")

		self.assertEqual(filter_values["invoice_amount_basis"], AMOUNT_BASIS_NET)
		self.assertEqual(filter_values["against_account"], "9090")
		self.assertEqual(filter_values["opening_account"], "9000")
		self.assertEqual(filter_values["umsatz_decimal_separator"], UMSATZ_DECIMAL_COMMA)

	def test_stored_gl_mirror_value_keeps_amount_basis(self):
		# A value left from the removed gl_mirror mode no longer forces Net (GitLab #117)
		settings = frappe._dict(
			{
				"temporary_against_account_number": "9090",
				"opening_against_account_number": "",
				"buchungsstapel_export_mode": "gl_mirror",
				"invoice_amount_basis": "gross",
			}
		)

		with patch(
			"gaertnerei_berger.gb_datev.report.datev.datev.frappe.get_cached_doc",
			return_value=settings,
		):
			filter_values = get_datev_export_filter_values("_Test GmbH")

		self.assertEqual(filter_values["invoice_amount_basis"], "gross")
		self.assertEqual(filter_values["opening_account"], "9090")
		self.assertNotIn("buchungsstapel_export_mode", filter_values)

	def test_umsatz_decimal_separator_is_always_comma(self):
		settings = frappe._dict(
			{
				"temporary_against_account_number": "9090",
				"opening_against_account_number": "9000",
				"invoice_amount_basis": AMOUNT_BASIS_NET,
				"umsatz_decimal_separator": ".",
			}
		)

		with patch(
			"gaertnerei_berger.gb_datev.report.datev.datev.frappe.get_cached_doc",
			return_value=settings,
		):
			filter_values = get_datev_export_filter_values("_Test GmbH")

		self.assertEqual(filter_values["umsatz_decimal_separator"], UMSATZ_DECIMAL_COMMA)

	def test_payment_line_settings_default_when_blank(self):
		settings = frappe._dict(
			{
				"temporary_against_account_number": "9090",
			}
		)

		with patch(
			"gaertnerei_berger.gb_datev.report.datev.datev.frappe.get_cached_doc",
			return_value=settings,
		):
			filter_values = get_datev_export_filter_values("_Test GmbH")

		self.assertEqual(filter_values["payment_line_mode"], PAYMENT_LINES_PER_INVOICE)
		self.assertEqual(filter_values["payment_belegfeld_1"], PAYMENT_BELEGFELD_PAYMENT_ENTRY)

	def test_payment_line_settings_pass_through(self):
		settings = frappe._dict(
			{
				"temporary_against_account_number": "9090",
				"payment_line_mode": "per_payment",
				"payment_belegfeld_1": "invoice",
			}
		)

		with patch(
			"gaertnerei_berger.gb_datev.report.datev.datev.frappe.get_cached_doc",
			return_value=settings,
		):
			filter_values = get_datev_export_filter_values("_Test GmbH")

		self.assertEqual(filter_values["payment_line_mode"], "per_payment")
		self.assertEqual(filter_values["payment_belegfeld_1"], "invoice")
