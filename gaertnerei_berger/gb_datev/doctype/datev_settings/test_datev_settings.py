from unittest import TestCase
from unittest.mock import patch

import frappe

from gaertnerei_berger.gb_datev.report.datev.datev import (
	AMOUNT_BASIS_NET,
	EXPORT_MODE_CONSULTANT,
	EXPORT_MODE_GL_MIRROR,
	UMSATZ_DECIMAL_COMMA,
	get_datev_export_filter_values,
)


class TestDATEVSettings(TestCase):
	def test_export_mode_defaults_from_settings_doc(self):
		settings = frappe._dict(
			{
				"temporary_against_account_number": "9090",
				"opening_against_account_number": "9000",
				"buchungsstapel_export_mode": EXPORT_MODE_CONSULTANT,
				"invoice_amount_basis": AMOUNT_BASIS_NET,
			}
		)

		with patch(
			"gaertnerei_berger.gb_datev.report.datev.datev.frappe.get_cached_doc",
			return_value=settings,
		):
			filter_values = get_datev_export_filter_values("_Test GmbH")

		self.assertEqual(filter_values["buchungsstapel_export_mode"], EXPORT_MODE_CONSULTANT)
		self.assertEqual(filter_values["invoice_amount_basis"], AMOUNT_BASIS_NET)
		self.assertEqual(filter_values["against_account"], "9090")
		self.assertEqual(filter_values["opening_account"], "9000")
		self.assertEqual(filter_values["umsatz_decimal_separator"], UMSATZ_DECIMAL_COMMA)

	def test_gl_mirror_mode_ignores_invoice_amount_basis(self):
		settings = frappe._dict(
			{
				"temporary_against_account_number": "9090",
				"opening_against_account_number": "",
				"buchungsstapel_export_mode": EXPORT_MODE_GL_MIRROR,
				"invoice_amount_basis": "gross",
			}
		)

		with patch(
			"gaertnerei_berger.gb_datev.report.datev.datev.frappe.get_cached_doc",
			return_value=settings,
		):
			filter_values = get_datev_export_filter_values("_Test GmbH")

		self.assertEqual(filter_values["buchungsstapel_export_mode"], EXPORT_MODE_GL_MIRROR)
		self.assertEqual(filter_values["invoice_amount_basis"], AMOUNT_BASIS_NET)
		self.assertEqual(filter_values["umsatz_decimal_separator"], UMSATZ_DECIMAL_COMMA)

	def test_umsatz_decimal_separator_is_always_comma(self):
		settings = frappe._dict(
			{
				"temporary_against_account_number": "9090",
				"opening_against_account_number": "9000",
				"buchungsstapel_export_mode": EXPORT_MODE_CONSULTANT,
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
