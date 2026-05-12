import importlib
import sys
import types
import unittest
from unittest.mock import Mock


MODULE_NAME = "gaertnerei_berger.patches.post_model_sync.backfill_datev_invoice_item_bu_schlussel"


class FakeDB:
	def __init__(self, table_columns=None):
		self.table_columns = table_columns or {}
		self.sql = Mock()
		self.get_table_columns = Mock(side_effect=self._get_table_columns)

	def _get_table_columns(self, doctype):
		return list(self.table_columns.get(doctype, ()))


def load_module(fake_frappe):
	sys.modules["frappe"] = fake_frappe
	sys.modules.pop(MODULE_NAME, None)
	return importlib.import_module(MODULE_NAME)


class TestBackfillDatevInvoiceItemBuSchlussel(unittest.TestCase):
	def tearDown(self):
		sys.modules.pop("frappe", None)
		sys.modules.pop(MODULE_NAME, None)

	def test_execute_backfills_both_invoice_item_doctypes(self):
		fake_frappe = types.SimpleNamespace()
		fake_frappe.db = FakeDB(
			table_columns={
				"Item Tax Template": {"custom_bu_schlussel"},
				"Sales Invoice Item": {"custom_bu_schlussel", "item_tax_template"},
				"Purchase Invoice Item": {"custom_bu_schlussel", "item_tax_template"},
			}
		)
		fake_frappe.clear_cache = Mock()
		module = load_module(fake_frappe)

		module.execute()

		self.assertEqual(fake_frappe.db.sql.call_count, 2)
		fake_frappe.clear_cache.assert_called_once()

	def test_execute_skips_backfill_without_required_columns(self):
		fake_frappe = types.SimpleNamespace()
		fake_frappe.db = FakeDB(
			table_columns={
				"Item Tax Template": {"custom_bu_schlussel"},
				"Sales Invoice Item": {"item_tax_template"},
				"Purchase Invoice Item": {"custom_bu_schlussel"},
			}
		)
		fake_frappe.clear_cache = Mock()
		module = load_module(fake_frappe)

		module.execute()

		fake_frappe.db.sql.assert_not_called()
		fake_frappe.clear_cache.assert_called_once()

	def test_backfill_purchase_invoice_item_uses_item_tax_template_values(self):
		fake_frappe = types.SimpleNamespace()
		fake_frappe.db = FakeDB(
			table_columns={
				"Item Tax Template": {"custom_bu_schlussel"},
				"Purchase Invoice Item": {"custom_bu_schlussel", "item_tax_template"},
			}
		)
		module = load_module(fake_frappe)

		module.backfill_invoice_item_bu_schlussel("Purchase Invoice Item")

		fake_frappe.db.sql.assert_called_once()
		query = fake_frappe.db.sql.call_args.args[0]
		self.assertIn("tabPurchase Invoice Item", query)
		self.assertIn("tabItem Tax Template", query)
		self.assertIn("invoice_item.item_tax_template", query)
		self.assertIn("invoice_item.`custom_bu_schlussel` = itt.`custom_bu_schlussel`", query)
