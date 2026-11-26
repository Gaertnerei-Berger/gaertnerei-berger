# Copyright (c) 2026, Gaertnerei Berger and contributors
# For license information, please see license.txt

"""Kunden/Lieferanten: Steuernummer/USt-IdNr fields and Vorname/Nachname split (GitLab #114)."""

from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch

import frappe

from gaertnerei_berger.gb_datev.master_data import is_party_tax_id_field
from gaertnerei_berger.gb_datev.report.datev.datev import (
	PERSON_NAME_KEY,
	STEUERNUMMER_KEY,
	UST_IDNR_KEY,
	get_datev_export_filter_values,
	get_debtors_creditors,
	get_tax_id_columns,
	get_tax_id_fields,
	split_person_name,
	split_ust_idnr,
)
from gaertnerei_berger.patches.post_model_sync import set_datev_tax_id_fields
from gaertnerei_berger.utils.datev_constants import DebtorsCreditors

DATEV = "gaertnerei_berger.gb_datev.report.datev.datev"


def debtor_row(**values):
	row = {
		"Konto": "10006",
		"Name (Adressatentyp Unternehmen)": None,
		PERSON_NAME_KEY: None,
		"Adressatentyp": "2",
		"Land": "DE",
	}
	row.update(values)
	return row


def export_rows(rows, **filters):
	"""Rows of get_debtors_creditors for mocked SQL rows; returns (rows, query)."""
	# frappe.db.sql is mocked, so the field metadata check is too
	with (
		patch(f"{DATEV}.frappe.db.sql", return_value=[dict(row) for row in rows]) as sql,
		patch(f"{DATEV}.is_party_tax_id_field", return_value=True),
	):
		result = get_debtors_creditors({"company": "_Test", **filters}, "Customer")
	return result, sql.call_args[0][0]


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


class TestTaxIdColumns(TestCase):
	def test_different_fields(self):
		self.assertEqual(
			get_tax_id_columns("007/123/45678", "DE 123 456 789"),
			{"Steuernummer": "007/123/45678", "EU-Land": "DE", "EU-USt-IdNr.": "123456789"},
		)

	def test_different_fields_only_steuernummer(self):
		self.assertEqual(get_tax_id_columns("007/123/45678", None), {"Steuernummer": "007/123/45678"})

	def test_same_field_ust_idnr_by_prefix(self):
		self.assertEqual(
			get_tax_id_columns("DE 123 456 789", "DE 123 456 789", same_field=True),
			{"EU-Land": "DE", "EU-USt-IdNr.": "123456789"},
		)
		self.assertEqual(
			get_tax_id_columns("ATU12345678", "ATU12345678", same_field=True),
			{"EU-Land": "AT", "EU-USt-IdNr.": "U12345678"},
		)

	def test_same_field_steuernummer_without_prefix(self):
		self.assertEqual(
			get_tax_id_columns("007/123/45678", "007/123/45678", same_field=True),
			{"Steuernummer": "007/123/45678"},
		)

	def test_same_field_empty(self):
		self.assertEqual(get_tax_id_columns(None, None, same_field=True), {"Steuernummer": None})


class TestTaxIdFields(TestCase):
	def test_no_settings_keys_means_tax_id_as_steuernummer(self):
		self.assertEqual(get_tax_id_fields({"company": "_Test"}), ("tax_id", None))

	def test_settings_fields(self):
		filters = {"steuernummer_field": "tax_id", "ust_idnr_field": None}
		self.assertEqual(get_tax_id_fields(filters), ("tax_id", None))

	def test_invalid_field_is_left_out(self):
		filters = {"steuernummer_field": "tax_id; DROP TABLE x", "ust_idnr_field": "customer_group"}
		self.assertEqual(get_tax_id_fields(filters), (None, None))


class TestDebtorsCreditorsRows(TestCase):
	def test_individual_one_word_name_goes_to_nachname(self):
		(row,), _query = export_rows([debtor_row(**{PERSON_NAME_KEY: "Mustermann", "Adressatentyp": "1"})])
		self.assertEqual(row["Name (Adressatentyp natürl. Person)"], "Mustermann")
		self.assertIsNone(row["Vorname (Adressatentyp natürl. Person)"])
		self.assertNotIn(PERSON_NAME_KEY, row)

	def test_company_has_no_person_name(self):
		(row,), _query = export_rows([debtor_row(**{"Name (Adressatentyp Unternehmen)": "Berger GmbH"})])
		self.assertIsNone(row["Name (Adressatentyp natürl. Person)"])
		self.assertIsNone(row["Vorname (Adressatentyp natürl. Person)"])

	def test_query_reads_the_configured_fields(self):
		_rows, query = export_rows([debtor_row()], steuernummer_field="tax_id", ust_idnr_field="tax_id")
		self.assertIn(f"cus.`tax_id` as '{STEUERNUMMER_KEY}'", query)
		self.assertIn(f"cus.`tax_id` as '{UST_IDNR_KEY}'", query)

	def test_query_without_ust_idnr_field(self):
		_rows, query = export_rows([debtor_row()], steuernummer_field="tax_id", ust_idnr_field=None)
		self.assertNotIn(UST_IDNR_KEY, query)

	def test_same_field_routes_by_format(self):
		rows, _query = export_rows(
			[
				debtor_row(**{STEUERNUMMER_KEY: "DE 123 456 789", UST_IDNR_KEY: "DE 123 456 789"}),
				debtor_row(**{STEUERNUMMER_KEY: "007/123/45678", UST_IDNR_KEY: "007/123/45678"}),
			],
			steuernummer_field="tax_id",
			ust_idnr_field="tax_id",
		)
		self.assertEqual((rows[0]["EU-Land"], rows[0]["EU-USt-IdNr."]), ("DE", "123456789"))
		self.assertNotIn("Steuernummer", rows[0])
		self.assertEqual(rows[1]["Steuernummer"], "007/123/45678")
		self.assertNotIn("EU-USt-IdNr.", rows[1])

	def test_rows_only_have_datev_columns(self):
		rows, _query = export_rows(
			[debtor_row(**{PERSON_NAME_KEY: "Max Mustermann", STEUERNUMMER_KEY: "1", UST_IDNR_KEY: "DE1"})],
			steuernummer_field="tax_id",
			ust_idnr_field="tax_id",
		)
		self.assertLessEqual(set(rows[0]), set(DebtorsCreditors.COLUMNS))


class TestPartyTaxIdField(TestCase):
	def test_tax_id_is_on_both(self):
		self.assertTrue(is_party_tax_id_field("tax_id"))

	def test_link_field_is_refused(self):
		self.assertFalse(is_party_tax_id_field("customer_group"))

	def test_unknown_or_unsafe_name_is_refused(self):
		self.assertFalse(is_party_tax_id_field("no_such_field"))
		self.assertFalse(is_party_tax_id_field("tax_id`; --"))
		self.assertFalse(is_party_tax_id_field(""))

	def test_custom_field_on_both(self):
		field = SimpleNamespace(fieldtype="Data")
		meta = MagicMock()
		meta.get_field.side_effect = lambda fieldname: field if fieldname == "custom_ust_idnr" else None
		with patch("gaertnerei_berger.gb_datev.master_data.frappe.get_meta", return_value=meta):
			self.assertTrue(is_party_tax_id_field("custom_ust_idnr"))

	def test_custom_field_only_on_customer(self):
		def get_meta(doctype):
			meta = MagicMock()
			meta.get_field.return_value = SimpleNamespace(fieldtype="Data") if doctype == "Customer" else None
			return meta

		with patch("gaertnerei_berger.gb_datev.master_data.frappe.get_meta", side_effect=get_meta):
			self.assertFalse(is_party_tax_id_field("custom_ust_idnr"))

	def test_settings_refuse_invalid_field(self):
		settings = frappe.new_doc("DATEV Settings")
		settings.update(
			{
				"invoice_amount_basis": "gross",
				"account_number_length": 4,
				"ust_idnr_field": "customer_group",
			}
		)
		with self.assertRaises(frappe.ValidationError):
			settings.validate()


class TestSettingValues(TestCase):
	def test_filter_values_pass_both_fields(self):
		values = {"steuernummer_field": "tax_id", "ust_idnr_field": "custom_ust_idnr"}
		settings = MagicMock()
		settings.get.side_effect = lambda key, default=None: values.get(key, default)
		with patch(f"{DATEV}.frappe.get_cached_doc", return_value=settings):
			result = get_datev_export_filter_values("_Test")
		self.assertEqual(result["steuernummer_field"], "tax_id")
		self.assertEqual(result["ust_idnr_field"], "custom_ust_idnr")


class TestPatch(TestCase):
	def run_patch(self, records, has_old_column=False):
		patch_module = "gaertnerei_berger.patches.post_model_sync.set_datev_tax_id_fields.frappe"
		with patch(patch_module) as mock_frappe:
			mock_frappe.db.has_column.return_value = has_old_column
			mock_frappe.get_all.return_value = [frappe._dict(record) for record in records]
			set_datev_tax_id_fields.execute()
			return [call.args for call in mock_frappe.db.set_value.call_args_list]

	def test_empty_settings_get_tax_id_as_steuernummer(self):
		calls = self.run_patch([{"name": "A"}])
		self.assertEqual(calls, [("DATEV Settings", "A", "steuernummer_field", "tax_id")])

	def test_old_ust_idnr_choice_is_kept(self):
		calls = self.run_patch([{"name": "A", "master_data_tax_id": "USt-IdNr"}], has_old_column=True)
		self.assertEqual(calls, [("DATEV Settings", "A", "ust_idnr_field", "tax_id")])

	def test_values_already_set_stay(self):
		self.assertEqual(self.run_patch([{"name": "A", "ust_idnr_field": "custom_x"}]), [])
