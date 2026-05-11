import importlib
import sys
import types
import unittest
from unittest.mock import Mock


MODULE_NAME = "gaertnerei_berger.patches.post_model_sync.rename_datev_invoice_item_custom_fields"


class FakeDB:
	def __init__(self, exists_map=None, table_columns=None):
		self.exists_map = exists_map or {}
		self.table_columns = table_columns or {}
		self.rename_column = Mock()
		self.set_value = Mock()
		self.sql = Mock()
		self.get_table_columns = Mock(side_effect=self._get_table_columns)

	def exists(self, doctype, name):
		return self.exists_map.get((doctype, name), False)

	def _get_table_columns(self, doctype):
		return list(self.table_columns.get(doctype, ()))


def load_patch_module(fake_frappe):
	sys.modules["frappe"] = fake_frappe
	sys.modules.pop(MODULE_NAME, None)
	return importlib.import_module(MODULE_NAME)


class TestRenameDatevInvoiceItemCustomFields(unittest.TestCase):
	def setUp(self):
		self.fake_frappe = types.SimpleNamespace()
		self.fake_frappe.rename_doc = Mock()
		self.fake_frappe.delete_doc = Mock()
		self.fake_frappe.clear_cache = Mock()

	def tearDown(self):
		sys.modules.pop("frappe", None)
		sys.modules.pop(MODULE_NAME, None)

	def test_copies_values_when_new_column_already_exists(self):
		doctype = "Sales Invoice Item"
		self.fake_frappe.db = FakeDB(
			exists_map={
				("Custom Field", f"{doctype}-datev_account_no"): True,
				("Custom Field", f"{doctype}-custom_datev_account_no"): False,
			},
			table_columns={doctype: {"datev_account_no", "custom_datev_account_no"}},
		)
		patch = load_patch_module(self.fake_frappe)

		patch.rename_or_merge_field(doctype, "income_account.account_number")

		self.fake_frappe.db.rename_column.assert_not_called()
		self.fake_frappe.db.sql.assert_called_once()
		self.fake_frappe.rename_doc.assert_called_once_with(
			"Custom Field",
			f"{doctype}-datev_account_no",
			f"{doctype}-custom_datev_account_no",
			force=True,
			merge=False,
		)

	def test_renames_column_when_only_old_column_exists(self):
		doctype = "Purchase Invoice Item"
		self.fake_frappe.db = FakeDB(
			exists_map={
				("Custom Field", f"{doctype}-datev_account_no"): True,
				("Custom Field", f"{doctype}-custom_datev_account_no"): False,
			},
			table_columns={doctype: {"datev_account_no"}},
		)
		patch = load_patch_module(self.fake_frappe)

		patch.rename_or_merge_field(doctype, "expense_account.account_number")

		self.fake_frappe.db.rename_column.assert_called_once_with(
			doctype, "datev_account_no", "custom_datev_account_no"
		)
		self.fake_frappe.db.sql.assert_not_called()

	def test_copies_values_when_old_custom_field_is_missing_but_new_field_exists(self):
		doctype = "Sales Invoice Item"
		self.fake_frappe.db = FakeDB(
			exists_map={
				("Custom Field", f"{doctype}-datev_account_no"): False,
				("Custom Field", f"{doctype}-custom_datev_account_no"): True,
			},
			table_columns={doctype: {"datev_account_no", "custom_datev_account_no"}},
		)
		patch = load_patch_module(self.fake_frappe)

		patch.rename_or_merge_field(doctype, "income_account.account_number")

		self.fake_frappe.db.rename_column.assert_not_called()
		self.fake_frappe.db.sql.assert_called_once()
		self.fake_frappe.rename_doc.assert_not_called()
		self.fake_frappe.delete_doc.assert_not_called()

	def test_renames_legacy_column_when_new_custom_field_exists(self):
		doctype = "Purchase Invoice Item"
		self.fake_frappe.db = FakeDB(
			exists_map={
				("Custom Field", f"{doctype}-datev_account_no"): False,
				("Custom Field", f"{doctype}-custom_datev_account_no"): True,
			},
			table_columns={doctype: {"datev_account_no"}},
		)
		patch = load_patch_module(self.fake_frappe)

		patch.rename_or_merge_field(doctype, "expense_account.account_number")

		self.fake_frappe.db.rename_column.assert_called_once_with(
			doctype, "datev_account_no", "custom_datev_account_no"
		)
		self.fake_frappe.db.sql.assert_not_called()
		self.fake_frappe.rename_doc.assert_not_called()
		self.fake_frappe.delete_doc.assert_not_called()

	def test_renames_legacy_column_without_custom_fields(self):
		doctype = "Sales Invoice Item"
		self.fake_frappe.db = FakeDB(
			exists_map={
				("Custom Field", f"{doctype}-datev_account_no"): False,
				("Custom Field", f"{doctype}-custom_datev_account_no"): False,
			},
			table_columns={doctype: {"datev_account_no"}},
		)
		patch = load_patch_module(self.fake_frappe)

		patch.rename_or_merge_field(doctype, "income_account.account_number")

		self.fake_frappe.db.rename_column.assert_called_once_with(
			doctype, "datev_account_no", "custom_datev_account_no"
		)
		self.fake_frappe.db.sql.assert_not_called()
		self.fake_frappe.rename_doc.assert_not_called()
		self.fake_frappe.delete_doc.assert_not_called()
		self.fake_frappe.db.set_value.assert_not_called()

	def test_copies_values_without_custom_fields_when_both_columns_exist(self):
		doctype = "Purchase Invoice Item"
		self.fake_frappe.db = FakeDB(
			exists_map={
				("Custom Field", f"{doctype}-datev_account_no"): False,
				("Custom Field", f"{doctype}-custom_datev_account_no"): False,
			},
			table_columns={doctype: {"datev_account_no", "custom_datev_account_no"}},
		)
		patch = load_patch_module(self.fake_frappe)

		patch.rename_or_merge_field(doctype, "expense_account.account_number")

		self.fake_frappe.db.rename_column.assert_not_called()
		self.fake_frappe.db.sql.assert_called_once()
		self.fake_frappe.rename_doc.assert_not_called()
		self.fake_frappe.delete_doc.assert_not_called()
		self.fake_frappe.db.set_value.assert_not_called()
