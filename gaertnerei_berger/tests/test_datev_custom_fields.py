import importlib
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock


MODULE_NAME = "gaertnerei_berger.datev_custom_fields"
FIXTURE_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "custom_field.json"


class FakeDB:
	def __init__(self, exists_map=None, table_columns=None):
		self.exists_map = exists_map or {}
		self.table_columns = table_columns or {}
		self.set_value = Mock()
		self.sql = Mock()
		self.get_table_columns = Mock(side_effect=self._get_table_columns)

	def exists(self, doctype, name):
		return self.exists_map.get((doctype, name), False)

	def _get_table_columns(self, doctype):
		return list(self.table_columns.get(doctype, ()))


def load_module(fake_frappe):
	sys.modules["frappe"] = fake_frappe
	sys.modules.pop(MODULE_NAME, None)
	return importlib.import_module(MODULE_NAME)


class TestDatevCustomFieldFixtures(unittest.TestCase):
	def test_fixture_contains_bu_schlussel_flow(self):
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


class TestDatevCustomFieldsAfterMigrate(unittest.TestCase):
	def tearDown(self):
		sys.modules.pop("frappe", None)
		sys.modules.pop(MODULE_NAME, None)

	def test_after_migrate_updates_metadata_and_backfills_values(self):
		fake_frappe = types.SimpleNamespace()
		fake_frappe.db = FakeDB(
			exists_map={
				("Custom Field", "Item Tax Template-custom_datev_section"): True,
				("Custom Field", "Item Tax Template-custom_bu_schlussel"): True,
				("Custom Field", "Journal Entry Account-custom_datev_section"): True,
				("Custom Field", "Journal Entry Account-custom_datev_account_no"): True,
				("Custom Field", "Journal Entry Account-custom_datev_code"): True,
				("Custom Field", "Sales Invoice Item-datev_settings_section"): True,
				("Custom Field", "Sales Invoice Item-custom_bu_schlussel"): True,
				("Custom Field", "Sales Invoice Item-datev_settings_end_section"): True,
				("Custom Field", "Purchase Invoice Item-datev_settings_section"): True,
				("Custom Field", "Purchase Invoice Item-custom_bu_schlussel"): True,
				("Custom Field", "Purchase Invoice Item-datev_settings_end_section"): True,
			},
			table_columns={
				"Item Tax Template": {"custom_bu_schlussel"},
				"Sales Invoice Item": {"custom_bu_schlussel", "item_tax_template"},
				"Purchase Invoice Item": {"custom_bu_schlussel", "item_tax_template"},
			},
		)
		fake_frappe.clear_cache = Mock()
		module = load_module(fake_frappe)

		module.after_migrate()

		fake_frappe.db.set_value.assert_any_call(
			"Custom Field",
			"Journal Entry Account-custom_datev_account_no",
			{
				"fieldname": "custom_datev_account_no",
				"fetch_from": "account.account_number",
				"fetch_if_empty": 1,
				"insert_after": "custom_datev_section",
				"label": "DATEV Account No",
				"read_only": 1,
			},
			update_modified=False,
		)
		fake_frappe.db.set_value.assert_any_call(
			"Custom Field",
			"Journal Entry Account-custom_datev_code",
			{
				"fieldname": "custom_datev_code",
				"insert_after": "custom_datev_account_no",
				"label": "DATEV Code",
			},
			update_modified=False,
		)
		fake_frappe.db.set_value.assert_any_call(
			"Custom Field",
			"Sales Invoice Item-custom_bu_schlussel",
			{
				"fieldname": "custom_bu_schlussel",
				"fetch_from": "item_tax_template.custom_bu_schlussel",
				"fetch_if_empty": 1,
				"insert_after": "custom_datev_account_no",
				"label": "BU-Schlüssel",
				"read_only": 1,
			},
			update_modified=False,
		)
		fake_frappe.db.set_value.assert_any_call(
			"Custom Field",
			"Sales Invoice Item-datev_settings_end_section",
			{"insert_after": "custom_bu_schlussel"},
			update_modified=False,
		)
		fake_frappe.db.set_value.assert_any_call(
			"Custom Field",
			"Purchase Invoice Item-custom_bu_schlussel",
			{
				"fieldname": "custom_bu_schlussel",
				"fetch_from": "item_tax_template.custom_bu_schlussel",
				"fetch_if_empty": 1,
				"insert_after": "custom_datev_account_no",
				"label": "BU-Schlüssel",
				"read_only": 1,
			},
			update_modified=False,
		)
		fake_frappe.db.set_value.assert_any_call(
			"Custom Field",
			"Purchase Invoice Item-datev_settings_end_section",
			{"insert_after": "custom_bu_schlussel"},
			update_modified=False,
		)
		self.assertEqual(fake_frappe.db.sql.call_count, 2)
		fake_frappe.clear_cache.assert_called_once()

	def test_after_migrate_skips_backfill_without_columns(self):
		fake_frappe = types.SimpleNamespace()
		fake_frappe.db = FakeDB(
			table_columns={
				"Item Tax Template": {"custom_bu_schlussel"},
				"Sales Invoice Item": {"item_tax_template"},
				"Purchase Invoice Item": {"item_tax_template"},
			}
		)
		fake_frappe.clear_cache = Mock()
		module = load_module(fake_frappe)

		module.after_migrate()

		fake_frappe.db.sql.assert_not_called()
		fake_frappe.clear_cache.assert_called_once()

	def test_after_migrate_skips_purchase_backfill_without_item_tax_template_link(self):
		fake_frappe = types.SimpleNamespace()
		fake_frappe.db = FakeDB(
			table_columns={
				"Item Tax Template": {"custom_bu_schlussel"},
				"Sales Invoice Item": {"custom_bu_schlussel", "item_tax_template"},
				"Purchase Invoice Item": {"custom_bu_schlussel"},
			}
		)
		fake_frappe.clear_cache = Mock()
		module = load_module(fake_frappe)

		module.after_migrate()

		self.assertEqual(fake_frappe.db.sql.call_count, 1)
		fake_frappe.clear_cache.assert_called_once()

	def test_backfill_purchase_invoice_item_bu_schlussel_uses_item_tax_template_values(self):
		fake_frappe = types.SimpleNamespace()
		fake_frappe.db = FakeDB(
			table_columns={
				"Item Tax Template": {"custom_bu_schlussel"},
				"Purchase Invoice Item": {"custom_bu_schlussel", "item_tax_template"},
			}
		)
		module = load_module(fake_frappe)

		module.backfill_invoice_item_bu_schlussel(module.PURCHASE_INVOICE_ITEM_DOCTYPE)

		fake_frappe.db.sql.assert_called_once()
		query = fake_frappe.db.sql.call_args.args[0]
		self.assertIn("tabPurchase Invoice Item", query)
		self.assertIn("tabItem Tax Template", query)
		self.assertIn("invoice_item.item_tax_template", query)
		self.assertIn("invoice_item.`custom_bu_schlussel` = itt.`custom_bu_schlussel`", query)
