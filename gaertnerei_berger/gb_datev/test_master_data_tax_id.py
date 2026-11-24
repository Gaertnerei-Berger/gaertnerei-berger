# Copyright (c) 2026, Gaertnerei Berger and contributors
# For license information, please see license.txt

"""Kunden/Lieferanten: Tax ID setting and Vorname/Nachname split (GitLab #114)."""

from unittest import TestCase
from unittest.mock import MagicMock, patch

from gaertnerei_berger.gb_datev.report.datev.datev import (
	PERSON_NAME_KEY,
	get_datev_export_filter_values,
	get_debtors_creditors,
	split_person_name,
	split_ust_idnr,
)
from gaertnerei_berger.utils.datev_constants import DebtorsCreditors

SQL = "gaertnerei_berger.gb_datev.report.datev.datev.frappe.db.sql"


def debtor_row(**values):
	row = {
		"Konto": "10006",
		"Name (Adressatentyp Unternehmen)": None,
		PERSON_NAME_KEY: None,
		"Adressatentyp": "2",
		"Land": "DE",
		"Steuernummer": None,
	}
	row.update(values)
	return row


def export_rows(rows, **filters):
	with patch(SQL, return_value=[dict(row) for row in rows]):
		return get_debtors_creditors({"company": "_Test", **filters}, "Customer")


class TestSplitPersonName(TestCase):
	def test_one_word_is_nachname(self):
		self.assertEqual(split_person_name("Mustermann"), (None, "Mustermann"))

	def test_two_words(self):
		self.assertEqual(split_person_name("Max Mustermann"), ("Max", "Mustermann"))

	def test_three_words_rest_is_nachname(self):
		self.assertEqual(split_person_name("Hanns-Peter von Berg"), ("Hanns-Peter", "von Berg"))

	def test_extra_spaces(self):
		self.assertEqual(split_person_name("  Max   Mustermann "), ("Max", "Mustermann"))

	def test_empty(self):
		self.assertEqual(split_person_name(None), (None, None))
		self.assertEqual(split_person_name("  "), (None, None))


class TestSplitUstIdnr(TestCase):
	def test_prefix_with_spaces(self):
		self.assertEqual(split_ust_idnr("DE 123 456 789"), {"EU-Land": "DE", "EU-USt-IdNr.": "123456789"})

	def test_austria_keeps_u(self):
		self.assertEqual(split_ust_idnr("ATU12345678"), {"EU-Land": "AT", "EU-USt-IdNr.": "U12345678"})

	def test_lower_case(self):
		self.assertEqual(split_ust_idnr("de123456789"), {"EU-Land": "DE", "EU-USt-IdNr.": "123456789"})

	def test_no_prefix_takes_address_country(self):
		self.assertEqual(split_ust_idnr("123456789", "de"), {"EU-Land": "DE", "EU-USt-IdNr.": "123456789"})

	def test_empty(self):
		self.assertEqual(split_ust_idnr(None), {})
		self.assertEqual(split_ust_idnr(" "), {})


class TestDebtorsCreditorsRows(TestCase):
	def test_individual_one_word_name_goes_to_nachname(self):
		(row,) = export_rows([debtor_row(**{PERSON_NAME_KEY: "Mustermann", "Adressatentyp": "1"})])
		self.assertEqual(row["Name (Adressatentyp natürl. Person)"], "Mustermann")
		self.assertIsNone(row["Vorname (Adressatentyp natürl. Person)"])
		self.assertNotIn(PERSON_NAME_KEY, row)

	def test_company_has_no_person_name(self):
		(row,) = export_rows([debtor_row(**{"Name (Adressatentyp Unternehmen)": "Berger GmbH"})])
		self.assertIsNone(row["Name (Adressatentyp natürl. Person)"])
		self.assertIsNone(row["Vorname (Adressatentyp natürl. Person)"])

	def test_default_keeps_steuernummer(self):
		(row,) = export_rows([debtor_row(Steuernummer="007/123/45678")])
		self.assertEqual(row["Steuernummer"], "007/123/45678")
		self.assertNotIn("EU-USt-IdNr.", row)

	def test_steuernummer_setting_keeps_steuernummer(self):
		(row,) = export_rows([debtor_row(Steuernummer="DE123456789")], master_data_tax_id="Steuernummer")
		self.assertEqual(row["Steuernummer"], "DE123456789")

	def test_ust_idnr_setting_fills_eu_fields(self):
		(row,) = export_rows([debtor_row(Steuernummer="DE 123 456 789")], master_data_tax_id="USt-IdNr")
		self.assertEqual(row["EU-Land"], "DE")
		self.assertEqual(row["EU-USt-IdNr."], "123456789")
		self.assertNotIn("Steuernummer", row)

	def test_ust_idnr_setting_without_tax_id(self):
		(row,) = export_rows([debtor_row()], master_data_tax_id="USt-IdNr")
		self.assertNotIn("EU-USt-IdNr.", row)

	def test_rows_only_have_datev_columns(self):
		rows = export_rows(
			[debtor_row(**{PERSON_NAME_KEY: "Max Mustermann"}, Steuernummer="DE1")],
			master_data_tax_id="USt-IdNr",
		)
		self.assertLessEqual(set(rows[0]), set(DebtorsCreditors.COLUMNS))


class TestSettingDefault(TestCase):
	def test_empty_setting_means_steuernummer(self):
		settings = MagicMock()
		settings.get.side_effect = lambda key, default=None: default
		with patch(
			"gaertnerei_berger.gb_datev.report.datev.datev.frappe.get_cached_doc", return_value=settings
		):
			self.assertEqual(get_datev_export_filter_values("_Test")["master_data_tax_id"], "Steuernummer")
