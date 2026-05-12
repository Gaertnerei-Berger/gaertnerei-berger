import json
import unittest
from pathlib import Path


FIXTURE_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "custom_field.json"


class TestDatevCustomFieldFixtures(unittest.TestCase):
	def test_fixture_contains_datev_field_configuration(self):
		data = json.loads(FIXTURE_PATH.read_text())
		rows = {row["name"]: row for row in data}

		item_tax_template_section = rows["Item Tax Template-custom_datev_section"]
		self.assertEqual(item_tax_template_section["label"], "DATEV")
		self.assertEqual(item_tax_template_section["insert_after"], "disabled")

		item_tax_template_field = rows["Item Tax Template-custom_bu_schlussel"]
		self.assertEqual(item_tax_template_field["fieldname"], "custom_bu_schlussel")
		self.assertEqual(item_tax_template_field["insert_after"], "custom_datev_section")

		journal_entry_section = rows["Journal Entry Account-custom_datev_section"]
		self.assertEqual(journal_entry_section["label"], "DATEV")
		self.assertEqual(journal_entry_section["insert_after"], "against_account")

		journal_entry_account_no = rows["Journal Entry Account-custom_datev_account_no"]
		self.assertEqual(journal_entry_account_no["fieldname"], "custom_datev_account_no")
		self.assertEqual(journal_entry_account_no["fetch_from"], "account.account_number")
		self.assertEqual(journal_entry_account_no["fetch_if_empty"], 1)
		self.assertEqual(journal_entry_account_no["insert_after"], "custom_datev_section")
		self.assertEqual(journal_entry_account_no["read_only"], 1)

		journal_entry_code = rows["Journal Entry Account-custom_datev_code"]
		self.assertEqual(journal_entry_code["fieldname"], "custom_datev_code")
		self.assertEqual(journal_entry_code["insert_after"], "custom_datev_account_no")

		sales_invoice_item_field = rows["Sales Invoice Item-custom_bu_schlussel"]
		self.assertEqual(sales_invoice_item_field["fieldname"], "custom_bu_schlussel")
		self.assertEqual(
			sales_invoice_item_field["fetch_from"], "item_tax_template.custom_bu_schlussel"
		)
		self.assertEqual(sales_invoice_item_field["insert_after"], "custom_datev_account_no")
		self.assertEqual(sales_invoice_item_field["read_only"], 1)

		sales_invoice_end_section = rows["Sales Invoice Item-datev_settings_end_section"]
		self.assertEqual(sales_invoice_end_section["insert_after"], "custom_bu_schlussel")

		purchase_invoice_item_field = rows["Purchase Invoice Item-custom_bu_schlussel"]
		self.assertEqual(purchase_invoice_item_field["fieldname"], "custom_bu_schlussel")
		self.assertEqual(
			purchase_invoice_item_field["fetch_from"], "item_tax_template.custom_bu_schlussel"
		)
		self.assertEqual(
			purchase_invoice_item_field["insert_after"], "custom_datev_account_no"
		)
		self.assertEqual(purchase_invoice_item_field["read_only"], 1)

		purchase_invoice_end_section = rows["Purchase Invoice Item-datev_settings_end_section"]
		self.assertEqual(purchase_invoice_end_section["insert_after"], "custom_bu_schlussel")
