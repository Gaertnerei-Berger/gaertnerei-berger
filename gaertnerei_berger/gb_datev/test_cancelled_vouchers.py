# Copyright (c) 2026, Gaertnerei Berger and contributors
# For license information, please see license.txt

"""Cancelled vouchers in the Buchungsstapel export (GitLab #106)."""

from datetime import datetime
from decimal import Decimal
from unittest import TestCase
from unittest.mock import MagicMock, patch

import frappe
from erpnext.accounts.doctype.sales_invoice.test_sales_invoice import create_sales_invoice
from frappe.utils import today

from gaertnerei_berger.gb_datev.report.datev.datev import (
	add_storno_rows,
	create_datev_export,
	filter_cancelled_voucher_rows,
	get_cancelled_query_parts,
	get_journal_entry_params,
	get_payment_entry_params,
	get_purchase_invoice_params,
	get_sales_invoice_params,
	prepare_buchungsstapel_transactions,
)
from gaertnerei_berger.gb_datev.report.datev.test_datev import (
	make_company,
	make_customer_with_account,
	make_datev_settings,
	make_item,
	setup_fiscal_year,
)

DATEV_MODULE = "gaertnerei_berger.gb_datev.report.datev.datev"
UMSATZ = "Umsatz (ohne Soll/Haben-Kz)"
SH = "Soll/Haben-Kennzeichen"
GU = "Generalumkehr (GU)"


def export_filters(company, include_cancelled, storno_mode="generalumkehr"):
	return {
		"company": company,
		"from_date": today(),
		"to_date": today(),
		"against_account": "9999",
		"opening_account": "9998",
		"buchungsstapel_export_mode": "consultant_booking",
		"invoice_amount_basis": "net",
		"payment_line_mode": "per_invoice",
		"payment_belegfeld_1": "payment_entry",
		"include_cancelled": include_cancelled,
		"storno_mode": storno_mode,
	}


def signed_total(rows):
	"""Net Umsatz: S positive, H negative; a Generalumkehr row counts reversed."""
	total = Decimal("0")
	for row in rows:
		amount = Decimal(str(row[UMSATZ]))
		sign = 1 if row[SH] == "S" else -1
		if row.get(GU) == "1":
			sign = -sign
		total += sign * amount
	return total


class TestCancelledSalesInvoiceExport(TestCase):
	"""Real Sales Invoice A, cancelled and amended to A-1."""

	def setUp(self):
		self.company = make_company("_Test GmbH", "_TG")
		customer = make_customer_with_account("_Test Kunde GmbH", self.company)
		make_datev_settings(self.company)
		item = make_item("_Test Item", self.company)
		setup_fiscal_year()

		income_account = frappe.db.get_value(
			"Account", {"account_number": "4200", "company": self.company.name}, "name"
		)
		warehouse = frappe.db.get_value(
			"Item Default", {"parent": item.name, "company": self.company.name}, "default_warehouse"
		)
		self.original = create_sales_invoice(
			company=self.company.name,
			customer=customer.name,
			currency=self.company.default_currency,
			debit_to=customer.accounts[0].account,
			income_account=income_account,
			expense_account="6990 - Herstellungskosten - _TG",
			cost_center=self.company.cost_center,
			warehouse=warehouse,
			item=item.name,
			rate=100,
			qty=1,
		)
		self.original.cancel()

		self.amended = frappe.copy_doc(self.original)
		self.amended.docstatus = 0
		self.amended.amended_from = self.original.name
		self.amended.items[0].rate = 80
		self.amended.insert()
		self.amended.submit()

	def export_rows(self, include_cancelled, storno_mode="generalumkehr"):
		rows = prepare_buchungsstapel_transactions(
			export_filters(self.company.name, include_cancelled, storno_mode)
		)
		vouchers = {self.original.name, self.amended.name}
		return [row for row in rows if row.get("Beleginfo - Inhalt 1") in vouchers]

	def rows_of(self, rows, voucher_no):
		return [row for row in rows if row.get("Beleginfo - Inhalt 1") == voucher_no]

	def test_setting_off_exports_only_the_amended_invoice(self):
		rows = self.export_rows(include_cancelled=0)

		self.assertEqual(self.rows_of(rows, self.original.name), [])
		self.assertTrue(self.rows_of(rows, self.amended.name))

	def test_generalumkehr_exports_original_storno_and_amended(self):
		rows = self.export_rows(include_cancelled=1)
		original_rows = self.rows_of(rows, self.original.name)

		self.assertEqual(len(original_rows), 2)
		booking, storno = original_rows
		self.assertNotEqual(booking.get(GU), "1")
		self.assertEqual(storno[GU], "1")
		self.assertEqual(storno[SH], booking[SH])
		self.assertEqual(storno[UMSATZ], booking[UMSATZ])
		self.assertEqual(storno["Konto"], booking["Konto"])
		self.assertEqual(storno["Gegenkonto (ohne BU-Schlüssel)"], booking["Gegenkonto (ohne BU-Schlüssel)"])
		self.assertEqual(storno["Belegdatum"], booking["Belegdatum"])
		self.assertEqual(storno["Belegfeld 1"], self.original.name)
		self.assertEqual(storno["Buchungstext"], "Storno {}".format(self.original.name))
		self.assertTrue(self.rows_of(rows, self.amended.name))

	def test_swap_soll_haben_swaps_and_leaves_gu_empty(self):
		rows = self.export_rows(include_cancelled=1, storno_mode="swap_soll_haben")
		booking, storno = self.rows_of(rows, self.original.name)

		self.assertNotEqual(storno[SH], booking[SH])
		self.assertFalse(storno.get(GU))
		self.assertEqual(storno[UMSATZ], booking[UMSATZ])

	def test_storno_follows_its_original(self):
		rows = self.export_rows(include_cancelled=1)
		names = [row.get("Beleginfo - Inhalt 1") for row in rows]
		first = names.index(self.original.name)

		self.assertEqual(names[first + 1], self.original.name)
		self.assertEqual(rows[first + 1][GU], "1")

	def test_original_and_storno_net_to_zero(self):
		for storno_mode in ("generalumkehr", "swap_soll_haben"):
			rows = self.export_rows(include_cancelled=1, storno_mode=storno_mode)
			self.assertEqual(signed_total(self.rows_of(rows, self.original.name)), 0)

	def test_erpnext_reversal_rows_are_never_exported(self):
		rows = self.export_rows(include_cancelled=1)

		for row in rows:
			self.assertFalse((row.get("Buchungstext") or "").startswith("On cancellation of"))


class TestCancelledJournalEntryExport(TestCase):
	"""Real party-less transfer Journal Entry (Bank an Kasse), cancelled."""

	def setUp(self):
		self.company = make_company("_Test GmbH", "_TG")
		make_datev_settings(self.company)
		setup_fiscal_year()

		accounts = frappe.get_all(
			"Account",
			filters={"company": self.company.name, "is_group": 0, "account_type": ["in", ["Bank", "Cash"]]},
			fields=["name", "account_number"],
			limit=2,
		)
		self.assertEqual(len(accounts), 2, "needs a bank and a cash account in _Test GmbH")

		journal_entry = frappe.get_doc(
			{
				"doctype": "Journal Entry",
				"company": self.company.name,
				"posting_date": today(),
				"accounts": [
					{"account": accounts[0].name, "debit_in_account_currency": 50},
					{"account": accounts[1].name, "credit_in_account_currency": 50},
				],
			}
		)
		journal_entry.insert()
		journal_entry.submit()
		journal_entry.cancel()
		self.journal_entry = journal_entry

	def test_cancelled_journal_entry_exports_with_storno(self):
		filters = export_filters(self.company.name, include_cancelled=1)
		rows = [
			row
			for row in prepare_buchungsstapel_transactions(filters)
			if row.get("Beleginfo - Inhalt 1") == self.journal_entry.name
		]

		self.assertEqual(len(rows), 2)
		self.assertEqual(rows[1][GU], "1")
		self.assertEqual(rows[1]["Buchungstext"], "Storno {}".format(self.journal_entry.name))
		self.assertEqual(signed_total(rows), 0)

	def test_setting_off_skips_cancelled_journal_entry(self):
		filters = export_filters(self.company.name, include_cancelled=0)
		rows = [
			row
			for row in prepare_buchungsstapel_transactions(filters)
			if row.get("Beleginfo - Inhalt 1") == self.journal_entry.name
		]

		self.assertEqual(rows, [])


def gl_row(voucher_type, voucher_no, creation, is_cancelled=0, reversal=0, konto="4200", sh="H"):
	return {
		UMSATZ: Decimal("100.00"),
		SH: sh,
		"Konto": konto,
		"Gegenkonto (ohne BU-Schlüssel)": "9999",
		"BU-Schlüssel": "",
		"Belegdatum": "2026-10-28",
		"Belegfeld 1": voucher_no,
		"Buchungstext": "On cancellation of {}".format(voucher_no) if reversal else "Test",
		"Beleginfo - Art 1": voucher_type,
		"Beleginfo - Inhalt 1": voucher_no,
		"_datev_gl_is_cancelled": is_cancelled,
		"_datev_gl_reversal": reversal,
		"_datev_gl_creation": datetime(2026, 10, 28, 10, creation),
	}


class TestFilterCancelledVoucherRows(TestCase):
	def run_filter(self, rows, docstatus):
		with patch(f"{DATEV_MODULE}.get_voucher_docstatus", return_value=docstatus):
			return filter_cancelled_voucher_rows(rows)

	def test_submitted_voucher_keeps_only_active_rows(self):
		# A Repost Accounting Ledger leaves flagged originals and their reversal
		rows = [
			gl_row("Sales Invoice", "A", 1, is_cancelled=1),
			gl_row("Sales Invoice", "A", 2, is_cancelled=1, reversal=1),
			gl_row("Sales Invoice", "A", 3),
		]
		result = self.run_filter(rows, {("Sales Invoice", "A"): 1})

		self.assertEqual(result, [rows[2]])
		self.assertNotIn("_datev_cancelled", rows[2])

	def test_cancelled_voucher_keeps_originals_and_drops_reversals(self):
		rows = [
			gl_row("Sales Invoice", "A", 1, is_cancelled=1),
			gl_row("Sales Invoice", "A", 1, is_cancelled=1, konto="10001", sh="S"),
			gl_row("Sales Invoice", "A", 5, is_cancelled=1, reversal=1),
			gl_row("Sales Invoice", "A", 5, is_cancelled=1, reversal=1, konto="10001", sh="H"),
		]
		result = self.run_filter(rows, {("Sales Invoice", "A"): 2})

		self.assertEqual(result, rows[:2])
		self.assertTrue(all(row["_datev_cancelled"] for row in result))

	def test_cancelled_voucher_keeps_only_last_generation_after_repost(self):
		rows = [
			gl_row("Journal Entry", "JV", 1, is_cancelled=1),
			gl_row("Journal Entry", "JV", 2, is_cancelled=1, reversal=1),
			gl_row("Journal Entry", "JV", 3, is_cancelled=1, konto="4400"),
			gl_row("Journal Entry", "JV", 9, is_cancelled=1, reversal=1, konto="4400"),
		]
		result = self.run_filter(rows, {("Journal Entry", "JV"): 2})

		self.assertEqual([row["Konto"] for row in result], ["4400"])

	def test_immutable_ledger_cancelled_voucher_without_flags(self):
		# Immutable Ledger leaves originals unflagged; the reversal may be out of range
		rows = [gl_row("Stock Entry", "STE-1", 1)]
		result = self.run_filter(rows, {("Stock Entry", "STE-1"): 2})

		self.assertEqual(result, rows)
		self.assertTrue(rows[0]["_datev_cancelled"])

	def test_generic_voucher_type_is_covered(self):
		rows = [
			gl_row("Stock Entry", "STE-2", 1, is_cancelled=1),
			gl_row("Stock Entry", "STE-2", 4, is_cancelled=1, reversal=1),
		]
		result = self.run_filter(rows, {("Stock Entry", "STE-2"): 2})

		self.assertEqual(result, rows[:1])

	def test_missing_voucher_behaves_as_without_setting(self):
		rows = [gl_row("Sales Invoice", "GONE", 1), gl_row("Sales Invoice", "GONE", 2, is_cancelled=1)]
		result = self.run_filter(rows, {})

		self.assertEqual(result, rows[:1])


class TestStornoRows(TestCase):
	def booking(self, **values):
		row = {
			UMSATZ: Decimal("100.00"),
			SH: "S",
			"Konto": "1800",
			"Gegenkonto (ohne BU-Schlüssel)": "10001",
			"BU-Schlüssel": "",
			"Belegdatum": "2026-10-28",
			"Belegfeld 1": "ACC-PAY-0001",
			"Buchungstext": "Payment",
			"Beleginfo - Art 1": "Payment Entry",
			"Beleginfo - Inhalt 1": "ACC-PAY-0001",
			"_datev_cancelled": True,
		}
		row.update(values)
		return row

	def test_setting_off_adds_nothing(self):
		rows = [self.booking()]
		self.assertEqual(add_storno_rows(rows, {"include_cancelled": 0}), rows)

	def test_submitted_rows_get_no_storno(self):
		rows = [self.booking(_datev_cancelled=False)]
		self.assertEqual(add_storno_rows(rows, {"include_cancelled": 1}), rows)

	def test_storno_text_uses_voucher_number_when_belegfeld_1_is_invoice(self):
		rows = [self.booking(**{"Belegfeld 1": "RG-260020"})]
		result = add_storno_rows(rows, {"include_cancelled": 1, "storno_mode": "generalumkehr"})

		self.assertEqual(result[1]["Belegfeld 1"], "RG-260020")
		self.assertEqual(result[1]["Buchungstext"], "Storno ACC-PAY-0001")

	def test_storno_text_is_cut_to_60_characters(self):
		rows = [self.booking(**{"Beleginfo - Inhalt 1": "X" * 70})]
		result = add_storno_rows(rows, {"include_cancelled": 1, "storno_mode": "generalumkehr"})

		self.assertEqual(len(result[1]["Buchungstext"]), 60)


class TestCancelledGroupedVouchers(TestCase):
	"""Grouping keeps the cancelled flag, so PI and PE get a Storno as well."""

	def test_purchase_invoice_items_get_storno(self):
		gl_rows = [
			{
				**gl_row("Purchase Invoice", "ER-1", 1, konto="", sh="H"),
				"Beleginfo - Art 3": "Supplier",
				"_datev_cancelled": True,
			}
		]
		voucher = frappe._dict(
			name="ER-1",
			company="_Test GmbH",
			supplier="_Test Lieferant",
			credit_to=None,
			items=[frappe._dict(custom_datev_account_no="5300", base_net_amount=100)],
		)
		rows = self.prepare(gl_rows, voucher)

		self.assertEqual([row["Konto"] for row in rows], ["5300", "5300"])
		self.assertEqual(rows[1][GU], "1")
		self.assertEqual(rows[1][SH], rows[0][SH])

	def test_payment_entry_gets_storno(self):
		party_row = {
			**gl_row("Payment Entry", "PE-1", 1, konto="10001", sh="H"),
			"Beleginfo - Art 3": "Customer",
			"_datev_cancelled": True,
		}
		bank_row = {**gl_row("Payment Entry", "PE-1", 1, konto="1800", sh="S"), "_datev_cancelled": True}
		voucher = frappe._dict(
			name="PE-1",
			payment_type="Receive",
			party_type="Customer",
			custom_datev_account_no="1800",
			custom_datev_against_account_no="10001",
		)
		rows = self.prepare([party_row, bank_row], voucher)

		self.assertEqual(len(rows), 2)
		self.assertEqual(rows[1]["Buchungstext"], "Storno PE-1")
		self.assertEqual(rows[1]["Konto"], "1800")
		self.assertEqual(rows[1][GU], "1")

	def prepare(self, gl_rows, voucher):
		filters = export_filters("_Test GmbH", include_cancelled=1)
		with (
			patch(f"{DATEV_MODULE}.get_transactions", return_value=gl_rows),
			patch(f"{DATEV_MODULE}.load_voucher_doc", return_value=voucher),
			patch(f"{DATEV_MODULE}.get_buchungsstapel_mappings", return_value={}),
			patch(f"{DATEV_MODULE}.get_account_maps", return_value=({}, {})),
			patch(f"{DATEV_MODULE}.get_party_account_number", return_value="70001"),
		):
			return prepare_buchungsstapel_transactions(filters)


class TestCancelledQueryParts(TestCase):
	def test_setting_off_keeps_submitted_only(self):
		fields, cancelled_filter = get_cancelled_query_parts({})

		self.assertEqual(fields, "")
		self.assertIn("is_cancelled, 0) = 0", cancelled_filter)
		for params in (
			get_sales_invoice_params,
			get_purchase_invoice_params,
			get_payment_entry_params,
			get_journal_entry_params,
		):
			self.assertIn("docstatus = 1", params({})[2])

	def test_setting_on_returns_cancelled_vouchers(self):
		filters = {"include_cancelled": 1}
		fields, cancelled_filter = get_cancelled_query_parts(filters)

		self.assertEqual(cancelled_filter, "")
		self.assertIn("_datev_gl_reversal", fields)
		self.assertIn("On cancellation of ", fields)
		for params in (
			get_sales_invoice_params,
			get_purchase_invoice_params,
			get_payment_entry_params,
			get_journal_entry_params,
		):
			self.assertIn("docstatus IN (1, 2)", params(filters)[2])


class TestDatevExportRecordsSetting(TestCase):
	def create(self, settings):
		export_doc = frappe._dict(name="DATEV-EXP-2026-00106", insert=MagicMock(), save=MagicMock())
		file_doc = frappe._dict(file_url="/private/files/x.zip", save=MagicMock())
		with (
			patch(f"{DATEV_MODULE}.frappe.only_for"),
			patch(f"{DATEV_MODULE}.get_existing_datev_export", return_value=None),
			patch(f"{DATEV_MODULE}.get_datev_export_filter_values", return_value=settings),
			patch(f"{DATEV_MODULE}.frappe.get_doc", side_effect=[export_doc, file_doc]) as get_doc,
			patch(f"{DATEV_MODULE}.build_datev_export_filters", return_value={}),
			patch(
				f"{DATEV_MODULE}.generate_datev_zip_payload",
				return_value={"zip_bytes": b"", "zip_filename": "x.zip", "row_count": 0},
			),
		):
			create_datev_export(company="My Company", from_date="2026-01-01", to_date="2026-01-31", force=1)

		return get_doc.call_args_list[0].args[0]

	def test_export_record_copies_both_settings(self):
		values = self.create({"include_cancelled": 1, "storno_mode": "swap_soll_haben"})

		self.assertEqual(values["include_cancelled"], 1)
		self.assertEqual(values["storno_mode"], "swap_soll_haben")

	def test_export_record_leaves_storno_mode_empty_when_off(self):
		values = self.create({"include_cancelled": 0, "storno_mode": "generalumkehr"})

		self.assertEqual(values["include_cancelled"], 0)
		self.assertEqual(values["storno_mode"], "")
