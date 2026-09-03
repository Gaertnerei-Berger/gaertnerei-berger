# Copyright (c) 2026, Gaertnerei Berger and contributors
# For license information, please see license.txt

from unittest import TestCase
from unittest.mock import MagicMock, patch

import frappe

from gaertnerei_berger.gb_datev.report.datev.datev import (
	create_datev_export,
	get_datev_connection_counts,
	get_existing_datev_export,
	get_recent_datev_exports,
)


class TestDATEVExportAPI(TestCase):
	def test_get_existing_datev_export_returns_generated_record(self):
		with patch(
			"gaertnerei_berger.gb_datev.report.datev.datev.frappe.db.get_value",
			return_value={
				"name": "DATEV-EXP-2026-00001",
				"posting_date": "2026-02-05",
				"exported_by": "Administrator",
			},
		):
			existing = get_existing_datev_export("My Company", "2026-01-01", "2026-01-31")

		self.assertEqual(existing["name"], "DATEV-EXP-2026-00001")

	def test_create_datev_export_returns_duplicate_without_force(self):
		with (
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.frappe.only_for",
			),
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.get_existing_datev_export",
				return_value={"name": "DATEV-EXP-2026-00001"},
			),
		):
			result = create_datev_export(
				company="My Company",
				from_date="2026-01-01",
				to_date="2026-01-31",
				force=0,
			)

		self.assertTrue(result["duplicate"])
		self.assertEqual(result["existing"]["name"], "DATEV-EXP-2026-00001")

	def test_create_datev_export_attaches_zip_and_sets_row_count(self):
		export_doc = frappe._dict(name="DATEV-EXP-2026-00002")
		export_doc.insert = MagicMock()
		export_doc.save = MagicMock()
		file_doc = frappe._dict(file_url="/private/files/test-datev.zip", save=MagicMock())

		with (
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.frappe.only_for",
			),
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.get_existing_datev_export",
				return_value=None,
			),
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.get_datev_export_filter_values",
				return_value={
					"buchungsstapel_export_mode": "consultant_booking",
					"invoice_amount_basis": "net",
				},
			),
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.frappe.get_doc",
			) as get_doc,
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.build_datev_export_filters",
				return_value={"company": "My Company"},
			),
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.generate_datev_zip_payload",
				return_value={
					"zip_bytes": b"zip-content",
					"zip_filename": "2026-01-31 DATEV.zip",
					"row_count": 42,
				},
			),
		):
			get_doc.side_effect = [export_doc, file_doc]
			result = create_datev_export(
				company="My Company",
				from_date="2026-01-01",
				to_date="2026-01-31",
				force=1,
			)

		self.assertFalse(result["duplicate"])
		self.assertEqual(result["name"], "DATEV-EXP-2026-00002")
		self.assertEqual(result["row_count"], 42)
		self.assertEqual(export_doc.export_file, "/private/files/test-datev.zip")
		self.assertEqual(export_doc.status, "Generated")
		file_doc.save.assert_called_once()

	def test_get_recent_datev_exports_limits_results(self):
		with (
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.frappe.only_for",
			),
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.frappe.get_all",
				return_value=[{"name": "DATEV-EXP-2026-00003"}],
			) as get_all,
		):
			rows = get_recent_datev_exports("My Company", limit=10)

		self.assertEqual(len(rows), 1)
		self.assertEqual(get_all.call_args.kwargs["limit"], 10)

	def test_get_datev_connection_counts(self):
		def mock_count(doctype, filters=None):
			if doctype == "DATEV Mapping":
				return 9
			if doctype == "DATEV Export":
				return 3
			return 0

		with (
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.frappe.only_for",
			),
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.frappe.db.exists",
				return_value=True,
			),
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.frappe.db.count",
				side_effect=mock_count,
			),
		):
			counts = get_datev_connection_counts("My Company")

		self.assertEqual(counts["DATEV Settings"], 1)
		self.assertEqual(counts["DATEV Mapping"], 9)
		self.assertEqual(counts["DATEV Unternehmen Online Settings"], 1)
		self.assertEqual(counts["DATEV Export"], 3)
