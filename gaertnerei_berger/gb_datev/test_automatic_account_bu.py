# Copyright (c) 2026, Gaertnerei Berger and contributors
# For license information, please see license.txt

"""BU-Schlüssel stays empty on DATEV Automatikkonten (GitLab #109)."""

import json
from decimal import Decimal
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from gaertnerei_berger.gb_datev.account import (
	has_automatic_accounts,
	validate_automatic_account,
)
from gaertnerei_berger.gb_datev.report.datev.datev import (
	clear_automatic_account_bu_schluessel,
	get_automatic_account_numbers,
	prepare_buchungsstapel_transactions,
)
from gaertnerei_berger.gb_datev.report.datev.test_datev import make_company, make_datev_settings

DATEV_MODULE = "gaertnerei_berger.gb_datev.report.datev.datev"
ACCOUNT_MODULE = "gaertnerei_berger.gb_datev.account"


def booking(konto, gegenkonto, bu, umsatz="100.00"):
	return {
		"Umsatz (ohne Soll/Haben-Kz)": umsatz,
		"Soll/Haben-Kennzeichen": "S",
		"Konto": konto,
		"Gegenkonto (ohne BU-Schlüssel)": gegenkonto,
		"BU-Schlüssel": bu,
	}


class TestClearAutomaticAccountBuSchluessel(FrappeTestCase):
	FILTERS = {"company": "_Test GmbH"}

	def clear(self, rows, automatic_accounts):
		with patch(f"{DATEV_MODULE}.get_automatic_account_numbers", return_value=automatic_accounts):
			return clear_automatic_account_bu_schluessel(rows, self.FILTERS)

	def test_clears_bu_when_automatikkonto_is_gegenkonto(self):
		# Screenshot in #109: Kreditor 70021 against Wareneingang 3300 with BU 8
		rows = self.clear([booking("70021", "3300", "8")], {"3300", "3400"})
		self.assertEqual(rows[0]["BU-Schlüssel"], "")

	def test_clears_bu_when_automatikkonto_is_konto(self):
		rows = self.clear([booking("8400", "10035", "3")], {"8400"})
		self.assertEqual(rows[0]["BU-Schlüssel"], "")

	def test_keeps_bu_on_normal_accounts(self):
		# StB file: 4530 Kfz-Kosten keeps BU 90
		rows = self.clear([booking("4530", "1000", "90")], {"3300", "8400"})
		self.assertEqual(rows[0]["BU-Schlüssel"], "90")

	def test_mixed_invoice_clears_only_automatikkonto_row(self):
		rows = self.clear(
			[booking("8400", "10035", "3"), booking("8195", "10035", "3")],
			{"8400"},
		)
		self.assertEqual([row["BU-Schlüssel"] for row in rows], ["", "3"])

	def test_keeps_umsatz_and_accounts(self):
		row = self.clear([booking("8400", "10035", "3", umsatz="119.00")], {"8400"})[0]
		self.assertEqual(row["Konto"], "8400")
		self.assertEqual(row["Gegenkonto (ohne BU-Schlüssel)"], "10035")
		self.assertEqual(row["Umsatz (ohne Soll/Haben-Kz)"], "119.00")

	def test_numeric_account_numbers_match(self):
		rows = self.clear([booking(8400, 10035, "3")], {"8400"})
		self.assertEqual(rows[0]["BU-Schlüssel"], "")

	def test_no_automatic_accounts_keeps_rows(self):
		rows = self.clear([booking("8400", "10035", "3")], set())
		self.assertEqual(rows[0]["BU-Schlüssel"], "3")

	def test_runs_after_mapping_in_consultant_mode(self):
		# A DATEV Mapping may write the BU back; the clearing pass runs last
		def mapping_sets_bu(rows, _filters):
			for row in rows:
				row["BU-Schlüssel"] = "3"
			return rows

		filters = {
			"company": "_Test GmbH",
			"against_account": "9090",
			"buchungsstapel_export_mode": "consultant_booking",
			"invoice_amount_basis": "gross",
		}
		with (
			patch(f"{DATEV_MODULE}.get_transactions", return_value=[booking("8400", "10035", "")]),
			patch(f"{DATEV_MODULE}.group_sales_invoice_buchungsstapel", side_effect=lambda r, _f: r),
			patch(f"{DATEV_MODULE}.group_payment_entry_buchungsstapel", side_effect=lambda r, _f: r),
			patch(f"{DATEV_MODULE}.group_journal_entry_buchungsstapel", side_effect=lambda r, _f: r),
			patch(f"{DATEV_MODULE}.apply_buchungsstapel_mapping", side_effect=mapping_sets_bu),
			patch(f"{DATEV_MODULE}.get_automatic_account_numbers", return_value={"8400"}),
		):
			rows = prepare_buchungsstapel_transactions(filters)

		self.assertEqual(rows[0]["BU-Schlüssel"], "")

	def test_runs_after_mapping_in_gl_mirror_mode(self):
		filters = {
			"company": "_Test GmbH",
			"against_account": "9090",
			"buchungsstapel_export_mode": "gl_mirror",
		}
		with (
			patch(f"{DATEV_MODULE}.get_transactions", return_value=[booking("8400", "9090", "3")]),
			patch(f"{DATEV_MODULE}.apply_buchungsstapel_mapping", side_effect=lambda r, _f: r),
			patch(f"{DATEV_MODULE}.get_automatic_account_numbers", return_value={"8400"}),
		):
			rows = prepare_buchungsstapel_transactions(filters)

		self.assertEqual(rows[0]["BU-Schlüssel"], "")


def get_or_make_account(company, account_number, root_type):
	"""Leaf account by number; created under a group of root_type if the chart lacks it."""
	name = frappe.db.get_value(
		"Account", {"company": company.name, "account_number": account_number, "is_group": 0}, "name"
	)
	if name:
		return name

	parent_account = frappe.db.get_value(
		"Account", {"company": company.name, "root_type": root_type, "is_group": 1}, "name"
	)
	return (
		frappe.get_doc(
			{
				"doctype": "Account",
				"account_name": f"_Test DATEV {account_number}",
				"account_number": account_number,
				"parent_account": parent_account,
				"company": company.name,
			}
		)
		.insert()
		.name
	)


class AutomaticAccountTestCase(FrappeTestCase):
	"""_Test GmbH (SKR04) with 4400 Erlöse 19 % USt and 5300 Wareneingang 7 % VSt."""

	def setUp(self):
		self.company = make_company("_Test GmbH", "_TG")
		make_datev_settings(self.company)
		self.erloese_account = get_or_make_account(self.company, "4400", "Income")
		self.wareneingang_account = get_or_make_account(self.company, "5300", "Expense")
		# Accounts a developer flagged by hand on the test site must not leak in
		frappe.db.set_value(
			"Account",
			{"company": self.company.name, "custom_datev_automatic_account": 1},
			"custom_datev_automatic_account",
			0,
		)

	def tearDown(self):
		frappe.db.rollback()

	def flag(self, account, value=1):
		frappe.db.set_value("Account", account, "custom_datev_automatic_account", value)


class TestAutomaticAccountFlag(AutomaticAccountTestCase):
	def test_custom_field_is_installed_on_account(self):
		# Fails when the fixture is dropped from hooks.py or not migrated
		meta = frappe.get_meta("Account")
		self.assertTrue(meta.has_field("custom_datev_automatic_account"))
		# Own DATEV section: right after the section break, and no standard Account
		# field may end up below it (insert_after a field mid-form would pull them in)
		fieldnames = [field.fieldname for field in meta.fields]
		section_index = fieldnames.index("custom_datev_section")
		self.assertEqual(meta.fields[section_index].fieldtype, "Section Break")
		self.assertEqual(fieldnames[section_index + 1], "custom_datev_automatic_account")
		for field in meta.fields[section_index + 2 :]:
			if field.fieldtype == "Section Break":
				break
			self.fail(f"{field.fieldname} landed in the DATEV section")

	def test_flagged_account_number_is_returned(self):
		self.flag(self.erloese_account)
		self.assertEqual(get_automatic_account_numbers(self.company.name), {"4400"})
		self.assertTrue(has_automatic_accounts(self.company.name))

	def test_unflagged_account_number_is_not_returned(self):
		self.assertEqual(get_automatic_account_numbers(self.company.name), set())
		self.assertFalse(has_automatic_accounts(self.company.name))

	def test_no_company_returns_empty_set(self):
		self.assertEqual(get_automatic_account_numbers(None), set())

	def test_account_warns_when_amount_basis_is_net(self):
		frappe.db.set_value("DATEV Settings", self.company.name, "invoice_amount_basis", "net")
		doc = frappe._dict(company=self.company.name, is_group=0, custom_datev_automatic_account=1)
		with patch(f"{ACCOUNT_MODULE}.frappe.msgprint") as msgprint:
			validate_automatic_account(doc)
		msgprint.assert_called_once()

	def test_account_does_not_warn_when_amount_basis_is_gross(self):
		frappe.db.set_value("DATEV Settings", self.company.name, "invoice_amount_basis", "gross")
		doc = frappe._dict(company=self.company.name, is_group=0, custom_datev_automatic_account=1)
		with patch(f"{ACCOUNT_MODULE}.frappe.msgprint") as msgprint:
			validate_automatic_account(doc)
		msgprint.assert_not_called()

	def test_party_bank_and_tax_accounts_cannot_be_flagged(self):
		for account_type in ("Receivable", "Payable", "Bank", "Cash", "Tax"):
			doc = frappe._dict(
				company=self.company.name,
				is_group=0,
				account_type=account_type,
				custom_datev_automatic_account=1,
			)
			with self.subTest(account_type=account_type), self.assertRaises(frappe.ValidationError):
				validate_automatic_account(doc)

	def test_saving_a_bank_account_as_automatikkonto_is_refused(self):
		# Through the real doc_event, not only the function
		bank_account = frappe.db.get_value(
			"Account", {"company": self.company.name, "account_type": "Bank", "is_group": 0}, "name"
		)
		if not bank_account:
			self.fail("SKR04 chart of _Test GmbH has no Bank account")
		account = frappe.get_doc("Account", bank_account)
		account.custom_datev_automatic_account = 1
		self.assertRaises(frappe.ValidationError, account.save)

	def test_settings_warn_when_net_and_automatic_accounts_exist(self):
		self.flag(self.erloese_account)
		settings = frappe.get_doc("DATEV Settings", self.company.name)
		settings.invoice_amount_basis = "net"
		with patch(f"{ACCOUNT_MODULE}.frappe.msgprint") as msgprint:
			settings.validate()
		msgprint.assert_called_once()

	def test_settings_do_not_warn_without_automatic_accounts(self):
		settings = frappe.get_doc("DATEV Settings", self.company.name)
		settings.invoice_amount_basis = "net"
		with patch(f"{ACCOUNT_MODULE}.frappe.msgprint") as msgprint:
			settings.validate()
		msgprint.assert_not_called()

	def test_settings_do_not_warn_when_gross(self):
		self.flag(self.erloese_account)
		settings = frappe.get_doc("DATEV Settings", self.company.name)
		settings.invoice_amount_basis = "gross"
		with patch(f"{ACCOUNT_MODULE}.frappe.msgprint") as msgprint:
			settings.validate()
		msgprint.assert_not_called()


class TestAutomaticAccountExportPipeline(AutomaticAccountTestCase):
	"""
	Real grouping, real DATEV Mapping and the real Account flag; only the GL
	query and the voucher load are stubbed.
	"""

	SALES_INVOICE = "RG-AUTOMATIK-001"
	PURCHASE_INVOICE = "ER-AUTOMATIK-001"

	def invoice_gl_row(self, voucher_type, voucher_no, party_type):
		return {
			"Umsatz (ohne Soll/Haben-Kz)": Decimal("238.00"),
			"Soll/Haben-Kennzeichen": "S",
			"Konto": "",
			"Gegenkonto (ohne BU-Schlüssel)": "",
			"BU-Schlüssel": "",
			"Belegdatum": "2026-10-18",
			"Belegfeld 1": voucher_no,
			"Buchungstext": "Test",
			"Beleginfo - Art 1": voucher_type,
			"Beleginfo - Inhalt 1": voucher_no,
			"Beleginfo - Art 3": party_type,
			"Beleginfo - Inhalt 3": "_Test Partei",
		}

	def invoice_item(self, konto, bu, rate):
		return frappe._dict(
			custom_datev_account_no=konto,
			custom_bu_schlussel=bu,
			item_tax_template=f"_Test {rate} %",
			item_tax_rate=json.dumps({"_Test Steuer": rate}),
			base_net_amount=100,
		)

	def vouchers(self):
		sales_invoice = frappe._dict(
			name=self.SALES_INVOICE,
			company=self.company.name,
			customer="_Test Kunde Automatik",
			debit_to=None,
			# Mapping source: a BU on the header the Mapping would write onto every row
			custom_bu_schlussel="3",
			items=[self.invoice_item("4400", "3", 19), self.invoice_item("4200", "3", 19)],
		)
		purchase_invoice = frappe._dict(
			name=self.PURCHASE_INVOICE,
			company=self.company.name,
			supplier="_Test Lieferant Automatik",
			credit_to=None,
			items=[self.invoice_item("5300", "8", 7), self.invoice_item("6520", "8", 7)],
		)
		return {
			("Sales Invoice", self.SALES_INVOICE): sales_invoice,
			("Purchase Invoice", self.PURCHASE_INVOICE): purchase_invoice,
		}

	def export(self, mappings=None):
		vouchers = self.vouchers()
		gl_rows = [
			self.invoice_gl_row("Sales Invoice", self.SALES_INVOICE, "Customer"),
			self.invoice_gl_row("Purchase Invoice", self.PURCHASE_INVOICE, "Supplier"),
		]
		filters = {
			"company": self.company.name,
			"against_account": "9090",
			"buchungsstapel_export_mode": "consultant_booking",
			"invoice_amount_basis": "gross",
		}
		with (
			patch(f"{DATEV_MODULE}.get_transactions", return_value=gl_rows),
			patch(f"{DATEV_MODULE}.load_voucher_doc", side_effect=lambda vt, vn: vouchers.get((vt, vn))),
			patch(f"{DATEV_MODULE}.get_buchungsstapel_mappings", return_value=mappings or {}),
			patch(f"{DATEV_MODULE}.get_account_maps", return_value=({}, {})),
		):
			rows = prepare_buchungsstapel_transactions(filters)

		return {row["Konto"]: row for row in rows}

	def test_without_flags_every_row_keeps_its_bu(self):
		rows = self.export()
		self.assertEqual(
			{konto: row["BU-Schlüssel"] for konto, row in rows.items()},
			{"4400": "3", "4200": "3", "5300": "8", "6520": "8"},
		)

	def test_flagged_accounts_export_without_bu(self):
		self.flag(self.erloese_account)
		self.flag(self.wareneingang_account)
		rows = self.export()
		self.assertEqual(
			{konto: row["BU-Schlüssel"] for konto, row in rows.items()},
			{"4400": "", "4200": "3", "5300": "", "6520": "8"},
		)

	def test_flagged_accounts_keep_gross_umsatz_and_orientation(self):
		self.flag(self.erloese_account)
		self.flag(self.wareneingang_account)
		rows = self.export()
		self.assertEqual(rows["4400"]["Umsatz (ohne Soll/Haben-Kz)"], Decimal("119.00"))
		self.assertEqual(rows["4400"]["Soll/Haben-Kennzeichen"], "H")
		self.assertEqual(rows["5300"]["Umsatz (ohne Soll/Haben-Kz)"], Decimal("107.00"))
		self.assertEqual(rows["5300"]["Soll/Haben-Kennzeichen"], "S")

	def test_mapping_cannot_bring_the_bu_back(self):
		# Invoice BU Mapping only fills an empty BU, which is exactly what the
		# Automatikkonto row has after clearing; the clearing must run last
		self.flag(self.erloese_account)
		mappings = {
			"Sales Invoice": {
				"Both": [frappe._dict(map_to_field="custom_bu_schlussel", map_to_column="BU-Schlüssel")]
			}
		}
		rows = self.export(mappings)
		self.assertEqual(rows["4400"]["BU-Schlüssel"], "")
		self.assertEqual(rows["4200"]["BU-Schlüssel"], "3")
