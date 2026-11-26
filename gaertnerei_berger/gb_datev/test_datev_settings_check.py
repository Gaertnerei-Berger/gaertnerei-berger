# Copyright (c) 2026, Gaertnerei Berger and contributors
# For license information, please see license.txt

"""No DATEV export while the Steuernummer/USt-IdNr fields are not set (GitLab #114)."""

import json
from unittest import TestCase
from unittest.mock import patch

import frappe

from gaertnerei_berger.gb_datev.report.datev.datev import (
	check_datev_settings,
	create_datev_export,
	download_datev_csv,
	get_missing_datev_settings,
)

DATEV = "gaertnerei_berger.gb_datev.report.datev.datev"
STEUERNUMMER_LABEL = "Steuernummer from Field"
UST_IDNR_LABEL = "USt-IdNr from Field"


def settings_values(**values):
	"""Patch the DATEV Settings lookup; exists=False: the company has no DATEV Settings."""
	exists = values.pop("exists", True)
	return patch(
		f"{DATEV}.get_required_export_setting_values", return_value=frappe._dict(values) if exists else None
	)


class TestMissingSettings(TestCase):
	def missing(self, **values):
		with settings_values(**values):
			return get_missing_datev_settings("My Company")

	def test_both_set(self):
		self.assertEqual(self.missing(steuernummer_field="tax_id", ust_idnr_field="tax_id"), [])

	def test_ust_idnr_missing(self):
		self.assertEqual(self.missing(steuernummer_field="tax_id", ust_idnr_field=None), [UST_IDNR_LABEL])

	def test_both_missing(self):
		self.assertEqual(self.missing(), [STEUERNUMMER_LABEL, UST_IDNR_LABEL])

	def test_no_settings_record(self):
		self.assertEqual(self.missing(exists=False), [STEUERNUMMER_LABEL, UST_IDNR_LABEL])


class TestExportIsStopped(TestCase):
	def test_check_returns_dialog_message(self):
		with settings_values(steuernummer_field="tax_id"), patch(f"{DATEV}.frappe.only_for"):
			result = check_datev_settings("My Company")
		self.assertEqual(result["missing"], [UST_IDNR_LABEL])
		self.assertIn(UST_IDNR_LABEL, result["message"])
		self.assertTrue(result["settings_exist"])

	def test_check_escapes_company(self):
		with settings_values(), patch(f"{DATEV}.frappe.only_for"):
			result = check_datev_settings("<b>x</b>")
		self.assertNotIn("<b>x</b>", result["message"])

	def test_create_export_stops_before_anything_is_written(self):
		with (
			settings_values(steuernummer_field="tax_id"),
			patch(f"{DATEV}.frappe.only_for"),
			patch(f"{DATEV}.get_existing_datev_export") as existing,
			patch(f"{DATEV}.frappe.get_doc") as get_doc,
		):
			with self.assertRaises(frappe.ValidationError):
				create_datev_export(company="My Company", from_date="2026-01-01", to_date="2026-01-31")
		existing.assert_not_called()
		get_doc.assert_not_called()

	def test_download_is_stopped(self):
		filters = json.dumps({"company": "My Company", "from_date": "2026-01-01", "to_date": "2026-01-31"})
		with (
			patch(f"{DATEV}.frappe.only_for"),
			patch(f"{DATEV}.validate"),
			patch(f"{DATEV}.get_missing_datev_settings", return_value=[UST_IDNR_LABEL]),
			patch(f"{DATEV}.get_datev_csv_files") as files,
		):
			with self.assertRaises(frappe.ValidationError):
				download_datev_csv(filters)
		files.assert_not_called()

	def test_create_export_runs_when_set(self):
		with (
			patch(f"{DATEV}.frappe.only_for"),
			patch(f"{DATEV}.get_missing_datev_settings", return_value=[]),
			patch(f"{DATEV}.get_existing_datev_export", return_value={"name": "DATEV-EXP-1"}),
		):
			result = create_datev_export(company="My Company", from_date="2026-01-01", to_date="2026-01-31")
		self.assertTrue(result["duplicate"])
