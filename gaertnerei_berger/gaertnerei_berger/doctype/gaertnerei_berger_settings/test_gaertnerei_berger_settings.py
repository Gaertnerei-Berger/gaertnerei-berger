# Copyright (c) 2026, Gaertnerei Berger and contributors
# For license information, please see license.txt

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from gaertnerei_berger.gaertnerei_berger.doctype.gaertnerei_berger_settings.gaertnerei_berger_settings import (
	SETTINGS_DOCTYPE,
	run_sales_invoice_datev_backfill,
)

BACKFILL_MODULE = (
	"gaertnerei_berger.gaertnerei_berger.doctype.gaertnerei_berger_settings.gaertnerei_berger_settings"
)
OLD_MODIFIED = "2020-01-01 10:00:00.000000"


class TestGaertnereiBergerSettings(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		# The backfill commits on purpose; keep it from committing test data to the site.
		commit_patcher = patch.object(frappe.db, "commit")
		self.commit = commit_patcher.start()
		self.addCleanup(commit_patcher.stop)
		frappe.db.set_single_value(SETTINGS_DOCTYPE, "si_datev_backfill_done", 0)

		_insert("Account", name="_Test GB Debtors", account_number="10000")
		_insert("Account", name="_Test GB Revenue", account_number="8400")
		_insert("Item Tax Template", name="_Test GB 19", custom_bu_schlussel="9")

		# Blank DATEV fields: must be filled.
		_insert("Sales Invoice", name="_Test GB SI Blank", debit_to="_Test GB Debtors", docstatus=1)
		_insert_item("_Test GB SI Blank", "_Test GB SII Blank")
		# Already filled: must be kept.
		_insert(
			"Sales Invoice",
			name="_Test GB SI Filled",
			debit_to="_Test GB Debtors",
			custom_datev_account_no="12345",
			docstatus=1,
		)
		_insert_item(
			"_Test GB SI Filled",
			"_Test GB SII Filled",
			custom_datev_account_no="4000",
			custom_bu_schlussel="3",
		)

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def test_fills_empty_fields_from_sources(self):
		run_sales_invoice_datev_backfill()

		self.assertEqual(
			frappe.db.get_value("Sales Invoice", "_Test GB SI Blank", "custom_datev_account_no"), "10000"
		)
		self.assertEqual(
			frappe.db.get_value(
				"Sales Invoice Item", "_Test GB SII Blank", ["custom_datev_account_no", "custom_bu_schlussel"]
			),
			("8400", "9"),
		)

	def test_keeps_existing_values(self):
		run_sales_invoice_datev_backfill()

		self.assertEqual(
			frappe.db.get_value("Sales Invoice", "_Test GB SI Filled", "custom_datev_account_no"), "12345"
		)
		self.assertEqual(
			frappe.db.get_value(
				"Sales Invoice Item",
				"_Test GB SII Filled",
				["custom_datev_account_no", "custom_bu_schlussel"],
			),
			("4000", "3"),
		)

	def test_does_not_touch_modified(self):
		run_sales_invoice_datev_backfill()

		for doctype, name in (
			("Sales Invoice", "_Test GB SI Blank"),
			("Sales Invoice Item", "_Test GB SII Blank"),
		):
			self.assertEqual(str(frappe.db.get_value(doctype, name, "modified")), "2020-01-01 10:00:00")

	def test_records_execution_and_runs_only_once(self):
		run_sales_invoice_datev_backfill()

		self.assertTrue(frappe.db.get_single_value(SETTINGS_DOCTYPE, "si_datev_backfill_done", cache=False))
		self.assertEqual(
			frappe.db.get_single_value(SETTINGS_DOCTYPE, "si_datev_backfill_by", cache=False), "Administrator"
		)
		self.assertRaises(frappe.ValidationError, run_sales_invoice_datev_backfill)

	def test_commits_before_releasing_the_lock(self):
		lock_held = []
		self.commit.side_effect = lambda: lock_held.append(self.lock_is_held)
		self.lock_is_held = False

		class FakeLock:
			def __enter__(lock):
				self.lock_is_held = True

			def __exit__(lock, *exc):
				self.lock_is_held = False

		with patch(f"{BACKFILL_MODULE}.filelock", return_value=FakeLock()):
			run_sales_invoice_datev_backfill()

		self.assertEqual(lock_held, [True])

	def test_missing_column_refuses_to_run_and_records_nothing(self):
		original_has_column = frappe.db.has_column

		def has_column(doctype, fieldname):
			if (doctype, fieldname) == ("Item Tax Template", "custom_bu_schlussel"):
				return False
			return original_has_column(doctype, fieldname)

		with patch.object(frappe.db, "has_column", side_effect=has_column):
			self.assertRaises(frappe.ValidationError, run_sales_invoice_datev_backfill)

		self.assertFalse(frappe.db.get_single_value(SETTINGS_DOCTYPE, "si_datev_backfill_done", cache=False))
		self.assertFalse(frappe.db.get_value("Sales Invoice", "_Test GB SI Blank", "custom_datev_account_no"))

	def test_requires_system_manager(self):
		frappe.set_user("Guest")
		self.assertRaises(frappe.PermissionError, run_sales_invoice_datev_backfill)


def _insert(doctype, **values):
	"""Insert a bare row without validation, so the test does not depend on a full ERPNext setup."""
	frappe.get_doc(
		{"doctype": doctype, "creation": OLD_MODIFIED, "modified": OLD_MODIFIED, **values}
	).db_insert()


def _insert_item(parent, name, **values):
	_insert(
		"Sales Invoice Item",
		name=name,
		parent=parent,
		parenttype="Sales Invoice",
		parentfield="items",
		income_account="_Test GB Revenue",
		item_tax_template="_Test GB 19",
		**values,
	)
