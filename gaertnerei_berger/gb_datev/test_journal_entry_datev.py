# Copyright (c) 2026, Gaertnerei Berger and contributors
# For license information, please see license.txt

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from gaertnerei_berger.gb_datev.journal_entry import (
	clear_datev_fields_on_tax_rows,
	get_item_tax_template_details,
	sync_datev_tax_lines,
	sync_journal_entry_header_datev_account_no,
)
from gaertnerei_berger.gb_datev.report.datev.datev import (
	get_business_row_bu_schluessel,
	get_grouped_journal_entry_rows,
	match_journal_entry_by_template,
)


class TestJournalEntryDatev(FrappeTestCase):
	def test_get_item_tax_template_details_returns_single_tax_row(self):
		with (
			patch(
				"gaertnerei_berger.gb_datev.journal_entry.frappe.db.get_value",
				return_value=frappe._dict(
					name="DE 19 USt",
					company="My Company",
					custom_bu_schlussel="9",
				),
			),
			patch(
				"gaertnerei_berger.gb_datev.journal_entry.frappe.get_all",
				return_value=[frappe._dict(tax_type="VAT 19 - _C", tax_rate=19)],
			),
		):
			details = get_item_tax_template_details("DE 19 USt", "My Company")

		self.assertEqual(details["bu_schluessel"], "9")
		self.assertEqual(details["tax_account"], "VAT 19 - _C")
		self.assertEqual(details["tax_rate"], 19)
		self.assertEqual(details["tax_detail_count"], 1)

	def test_sync_bundles_same_template_into_one_tax_line(self):
		doc = frappe.get_doc(
			{
				"doctype": "Journal Entry",
				"company": "My Company",
				"accounts": [
					{
						"account": "Debtors - _C",
						"party_type": "Customer",
						"party": "Customer A",
						"debit_in_account_currency": 119,
						"credit_in_account_currency": 0,
					},
					{
						"account": "Sales - _C",
						"debit_in_account_currency": 0,
						"credit_in_account_currency": 100,
						"custom_item_tax_template": "DE 19 USt",
						"custom_bu_schlussel": "9",
						"custom_datev_account_no": "8400",
					},
					{
						"account": "Sales Other - _C",
						"debit_in_account_currency": 0,
						"credit_in_account_currency": 200,
						"custom_item_tax_template": "DE 19 USt",
						"custom_bu_schlussel": "9",
						"custom_datev_account_no": "8400",
					},
				],
			}
		)

		with (
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.get_journal_entry_account_type",
				side_effect=lambda account: {
					"Debtors - _C": "Receivable",
					"Sales - _C": "Income",
					"Sales Other - _C": "Income",
					"VAT 19 - _C": "Tax",
				}.get(account, ""),
			),
			patch(
				"gaertnerei_berger.gb_datev.journal_entry.get_journal_entry_account_type",
				side_effect=lambda account: {
					"Debtors - _C": "Receivable",
					"Sales - _C": "Income",
					"Sales Other - _C": "Income",
					"VAT 19 - _C": "Tax",
				}.get(account, ""),
			),
			patch(
				"gaertnerei_berger.gb_datev.journal_entry.get_item_tax_template_details",
				return_value={
					"name": "DE 19 USt",
					"company": "My Company",
					"bu_schluessel": "9",
					"tax_detail_count": 1,
					"tax_account": "VAT 19 - _C",
					"tax_rate": 19,
				},
			),
		):
			sync_datev_tax_lines(doc)

		auto_tax_rows = [row for row in doc.accounts if row.custom_datev_auto_tax]
		self.assertEqual(len(auto_tax_rows), 1)
		self.assertEqual(auto_tax_rows[0].account, "VAT 19 - _C")
		self.assertEqual(float(auto_tax_rows[0].credit_in_account_currency), 57.0)
		self.assertEqual(auto_tax_rows[0].custom_bu_schlussel, "")

		party_row = doc.accounts[0]
		self.assertEqual(float(party_row.debit_in_account_currency), 357.0)

	def test_clear_bu_on_tax_account_rows(self):
		doc = frappe.get_doc(
			{
				"doctype": "Journal Entry",
				"company": "My Company",
				"accounts": [
					{
						"account": "VAT 19 - _C",
						"debit_in_account_currency": 0,
						"credit_in_account_currency": 19,
						"custom_bu_schlussel": "9",
						"custom_item_tax_template": "DE 19 USt",
						"custom_datev_auto_tax": 0,
					}
				],
			}
		)

		with patch(
			"gaertnerei_berger.gb_datev.journal_entry.get_journal_entry_account_type",
			return_value="Tax",
		):
			clear_datev_fields_on_tax_rows(doc)

		self.assertEqual(doc.accounts[0].custom_bu_schlussel, "")
		self.assertEqual(doc.accounts[0].custom_item_tax_template, "")

	def test_export_uses_business_row_bu_and_template_grouping(self):
		business_a = frappe._dict(
			{
				"account": "Sales - _C",
				"credit_in_account_currency": 100,
				"debit_in_account_currency": 0,
				"custom_item_tax_template": "DE 19 USt",
				"custom_bu_schlussel": "9",
				"custom_datev_account_no": "8400",
			}
		)
		business_b = frappe._dict(
			{
				"account": "Sales Other - _C",
				"credit_in_account_currency": 200,
				"debit_in_account_currency": 0,
				"custom_item_tax_template": "DE 19 USt",
				"custom_bu_schlussel": "9",
				"custom_datev_account_no": "8300",
			}
		)
		tax_row = frappe._dict(
			{
				"account": "VAT 19 - _C",
				"credit_in_account_currency": 57,
				"debit_in_account_currency": 0,
				"custom_datev_auto_tax": 1,
				"custom_item_tax_template": "DE 19 USt",
				"custom_bu_schlussel": "",
			}
		)

		paired = match_journal_entry_by_template([business_a, business_b], [tax_row])
		self.assertEqual(len(paired), 2)
		self.assertEqual(get_business_row_bu_schluessel(business_a, tax_row), "9")
		self.assertEqual(get_business_row_bu_schluessel(business_b, tax_row), "9")

		journal_entry = frappe._dict(
			{
				"name": "ACC-JV-2026-ITT",
				"company": "My Company",
				"accounts": [
					frappe._dict(
						{
							"account": "Debtors - _C",
							"party_type": "Customer",
							"party": "Customer A",
							"debit_in_account_currency": 357,
							"credit_in_account_currency": 0,
						}
					),
					business_a,
					business_b,
					tax_row,
				],
			}
		)
		voucher_rows = [
			{
				"Belegdatum": "2026-01-15",
				"Belegfeld 1": "ACC-JV-2026-ITT",
				"Beleginfo - Art 1": "Journal Entry",
			}
		]

		with (
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.load_voucher_doc",
				return_value=journal_entry,
			),
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.get_journal_entry_account_type",
				side_effect=lambda account: {
					"Debtors - _C": "Receivable",
					"Sales - _C": "Income",
					"Sales Other - _C": "Income",
					"VAT 19 - _C": "Tax",
				}.get(account, ""),
			),
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.get_party_account_number",
				return_value="10001",
			),
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.is_journal_entry_tax_row",
				side_effect=lambda row: row.account == "VAT 19 - _C",
			),
		):
			grouped = get_grouped_journal_entry_rows(
				"ACC-JV-2026-ITT",
				voucher_rows,
				{"company": "My Company", "against_account": "9999"},
			)

		self.assertEqual(len(grouped), 2)
		self.assertEqual({row["Konto"] for row in grouped}, {"8400", "8300"})
		self.assertEqual({row["Gegenkonto (ohne BU-Schlüssel)"] for row in grouped}, {"10001"})
		self.assertEqual({row["BU-Schlüssel"] for row in grouped}, {"9"})
		self.assertEqual(sum(float(row["Umsatz (ohne Soll/Haben-Kz)"]) for row in grouped), 300.0)

	def test_export_merges_same_konto_and_bu(self):
		"""Two business lines with same Konto + BU collapse to one DATEV row (summed Umsatz)."""
		business_a = frappe._dict(
			{
				"account": "Purchase - _C",
				"debit_in_account_currency": 301,
				"credit_in_account_currency": 0,
				"custom_item_tax_template": "DE 7 VSt",
				"custom_bu_schlussel": "5",
				"custom_datev_account_no": "5300",
			}
		)
		business_b = frappe._dict(
			{
				"account": "Purchase - _C",
				"debit_in_account_currency": 301,
				"credit_in_account_currency": 0,
				"custom_item_tax_template": "DE 7 VSt",
				"custom_bu_schlussel": "5",
				"custom_datev_account_no": "5300",
			}
		)
		tax_row = frappe._dict(
			{
				"account": "VAT Input 7 - _C",
				"debit_in_account_currency": 42.14,
				"credit_in_account_currency": 0,
				"custom_datev_auto_tax": 1,
				"custom_item_tax_template": "DE 7 VSt",
				"custom_bu_schlussel": "",
			}
		)

		journal_entry = frappe._dict(
			{
				"name": "ACC-JV-2026-MERGE",
				"company": "My Company",
				"accounts": [
					frappe._dict(
						{
							"account": "Creditors - _C",
							"party_type": "Supplier",
							"party": "Supplier A",
							"debit_in_account_currency": 0,
							"credit_in_account_currency": 644.14,
						}
					),
					business_a,
					business_b,
					tax_row,
				],
			}
		)
		voucher_rows = [
			{
				"Belegdatum": "2026-01-15",
				"Belegfeld 1": "ACC-JV-2026-MERGE",
				"Beleginfo - Art 1": "Journal Entry",
			}
		]

		with (
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.load_voucher_doc",
				return_value=journal_entry,
			),
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.get_journal_entry_account_type",
				side_effect=lambda account: {
					"Creditors - _C": "Payable",
					"Purchase - _C": "Expense",
					"VAT Input 7 - _C": "Tax",
				}.get(account, ""),
			),
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.get_party_account_number",
				return_value="70003",
			),
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.is_journal_entry_tax_row",
				side_effect=lambda row: row.account == "VAT Input 7 - _C",
			),
		):
			grouped = get_grouped_journal_entry_rows(
				"ACC-JV-2026-MERGE",
				voucher_rows,
				{"company": "My Company", "against_account": "9999"},
			)

		self.assertEqual(len(grouped), 1)
		self.assertEqual(grouped[0]["Konto"], "5300")
		self.assertEqual(grouped[0]["BU-Schlüssel"], "5")
		self.assertEqual(grouped[0]["Soll/Haben-Kennzeichen"], "S")
		self.assertEqual(float(grouped[0]["Umsatz (ohne Soll/Haben-Kz)"]), 602.0)
		self.assertEqual(grouped[0]["Gegenkonto (ohne BU-Schlüssel)"], "70003")

	def test_export_uses_gross_amount_basis_from_item_tax_template(self):
		business = frappe._dict(
			{
				"account": "Purchase - _C",
				"debit_in_account_currency": 283.56,
				"credit_in_account_currency": 0,
				"custom_item_tax_template": "DE 7 VSt",
				"custom_bu_schlussel": "5",
				"custom_datev_account_no": "5300",
			}
		)
		tax_row = frappe._dict(
			{
				"account": "VAT Input 7 - _C",
				"debit_in_account_currency": 19.85,
				"credit_in_account_currency": 0,
				"custom_datev_auto_tax": 1,
				"custom_item_tax_template": "DE 7 VSt",
			}
		)
		journal_entry = frappe._dict(
			{
				"name": "ACC-JV-2026-GROSS",
				"company": "My Company",
				"accounts": [
					frappe._dict(
						{
							"account": "Creditors - _C",
							"party_type": "Supplier",
							"party": "Supplier A",
							"debit_in_account_currency": 0,
							"credit_in_account_currency": 303.41,
						}
					),
					business,
					tax_row,
				],
			}
		)
		voucher_rows = [
			{
				"Belegdatum": "2026-01-15",
				"Belegfeld 1": "ACC-JV-2026-GROSS",
				"Beleginfo - Art 1": "Journal Entry",
			}
		]

		with (
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.load_voucher_doc",
				return_value=journal_entry,
			),
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.get_journal_entry_account_type",
				side_effect=lambda account: {
					"Creditors - _C": "Payable",
					"Purchase - _C": "Expense",
					"VAT Input 7 - _C": "Tax",
				}.get(account, ""),
			),
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.get_party_account_number",
				return_value="70217",
			),
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.is_journal_entry_tax_row",
				side_effect=lambda row: row.account == "VAT Input 7 - _C",
			),
			patch(
				"gaertnerei_berger.gb_datev.journal_entry.get_item_tax_template_details",
				return_value={"tax_rate": 7, "tax_account": "VAT Input 7 - _C", "bu_schluessel": "5"},
			),
		):
			gross_grouped = get_grouped_journal_entry_rows(
				"ACC-JV-2026-GROSS",
				voucher_rows,
				{
					"company": "My Company",
					"against_account": "9999",
					"invoice_amount_basis": "gross",
				},
			)
			net_grouped = get_grouped_journal_entry_rows(
				"ACC-JV-2026-GROSS",
				voucher_rows,
				{
					"company": "My Company",
					"against_account": "9999",
					"invoice_amount_basis": "net",
				},
			)

		self.assertEqual(len(gross_grouped), 1)
		self.assertEqual(float(gross_grouped[0]["Umsatz (ohne Soll/Haben-Kz)"]), 303.41)
		self.assertEqual(float(net_grouped[0]["Umsatz (ohne Soll/Haben-Kz)"]), 283.56)

	def test_sync_journal_entry_header_datev_account_no_from_party(self):
		doc = frappe.get_doc(
			{
				"doctype": "Journal Entry",
				"company": "My Company",
				"accounts": [
					{
						"account": "Debtors - _C",
						"party_type": "Customer",
						"party": "Customer A",
						"debit_in_account_currency": 119,
						"credit_in_account_currency": 0,
					},
					{
						"account": "Sales - _C",
						"debit_in_account_currency": 0,
						"credit_in_account_currency": 100,
						"custom_item_tax_template": "DE 19 USt",
					},
				],
			}
		)

		with (
			patch(
				"gaertnerei_berger.gb_datev.journal_entry.frappe.db.get_value",
				side_effect=lambda doctype, filters, fieldname, *args, **kwargs: {
					("Party Account", "debtor_creditor_number"): "10111",
				}.get((doctype, fieldname)),
			),
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.get_journal_entry_account_type",
				side_effect=lambda account: {
					"Debtors - _C": "Receivable",
					"Sales - _C": "Income",
				}.get(account, ""),
			),
			patch(
				"gaertnerei_berger.gb_datev.journal_entry.get_journal_entry_account_type",
				side_effect=lambda account: {
					"Debtors - _C": "Receivable",
					"Sales - _C": "Income",
				}.get(account, ""),
			),
		):
			sync_journal_entry_header_datev_account_no(doc)

		self.assertEqual(doc.custom_datev_account_no, "10111")
