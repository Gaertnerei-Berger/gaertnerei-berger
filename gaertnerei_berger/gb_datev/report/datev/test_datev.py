import zipfile
from io import BytesIO
from unittest import TestCase
from unittest.mock import Mock, patch

import frappe
from erpnext.accounts.doctype.sales_invoice.test_sales_invoice import (
	create_sales_invoice,
)
from frappe.utils import cstr, now_datetime, today

from gaertnerei_berger.gb_datev.report.datev.datev import (
	apply_buchungsstapel_mapping,
	download_datev_csv,
	execute,
	get_account_names,
	get_customers,
	group_payment_entry_buchungsstapel,
	group_journal_entry_buchungsstapel,
	group_sales_invoice_buchungsstapel,
	get_suppliers,
	get_transactions,
)
from gaertnerei_berger.utils.datev_constants import (
	AccountNames,
	DebtorsCreditors,
	Transactions,
)
from gaertnerei_berger.utils.datev_csv import get_datev_csv, get_header


def make_company(company_name, abbr):
	if not frappe.db.exists("Company", company_name):
		company = frappe.get_doc(
			{
				"doctype": "Company",
				"company_name": company_name,
				"abbr": abbr,
				"default_currency": "EUR",
				"country": "Germany",
				"create_chart_of_accounts_based_on": "Standard Template",
				"chart_of_accounts": "SKR04 mit Kontonummern",
			}
		)
		company.insert()
	else:
		company = frappe.get_doc("Company", company_name)

	# indempotent
	company.create_default_warehouses()

	if not frappe.db.get_value("Cost Center", {"is_group": 0, "company": company.name}):
		company.create_default_cost_center()

	company.save()
	return company


def setup_fiscal_year():
	fiscal_year = None
	year = cstr(now_datetime().year)
	if not frappe.db.get_value("Fiscal Year", {"year": year}, "name"):
		try:
			fiscal_year = frappe.get_doc(
				{
					"doctype": "Fiscal Year",
					"year": year,
					"year_start_date": f"{year}-01-01",
					"year_end_date": f"{year}-12-31",
				}
			)
			fiscal_year.insert()
		except frappe.NameError:
			pass

	if fiscal_year:
		fiscal_year.set_as_default()


def make_customer_with_account(customer_name, company):
	acc_name = frappe.db.get_value(
		"Account", {"account_name": customer_name, "company": company.name}, "name"
	)

	if not acc_name:
		acc = frappe.get_doc(
			{
				"doctype": "Account",
				"parent_account": "1 - Forderungen aus Lieferungen und Leistungen - _TG",
				"account_name": customer_name,
				"company": company.name,
				"account_type": "Receivable",
				"account_number": "10001",
			}
		)
		acc.insert()
		acc_name = acc.name

	if not frappe.db.exists("Customer", customer_name):
		customer = frappe.get_doc(
			{
				"doctype": "Customer",
				"customer_name": customer_name,
				"customer_type": "Company",
				"accounts": [{"company": company.name, "account": acc_name}],
			}
		)
		customer.insert()
	else:
		customer = frappe.get_doc("Customer", customer_name)

	return customer


def make_item(item_code, company):
	warehouse_name = frappe.db.get_value(
		"Warehouse", {"warehouse_name": "Stores", "company": company.name}, "name"
	)

	if not frappe.db.exists("Item", item_code):
		item = frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": item_code,
				"item_name": item_code,
				"description": item_code,
				"item_group": "All Item Groups",
				"is_stock_item": 0,
				"is_purchase_item": 0,
				"is_customer_provided_item": 0,
				"item_defaults": [{"default_warehouse": warehouse_name, "company": company.name}],
			}
		)
		item.insert()
	else:
		item = frappe.get_doc("Item", item_code)
	return item


def make_datev_settings(company):
	if not frappe.db.exists("DATEV Settings", company.name):
		frappe.get_doc(
			{
				"doctype": "DATEV Settings",
				"client": company.name,
				"client_number": "12345",
				"consultant_number": "67890",
				"temporary_against_account_number": "9999",
			}
		).insert()


class TestDatev(TestCase):
	def setUp(self):
		self.company = make_company("_Test GmbH", "_TG")
		self.customer = make_customer_with_account("_Test Kunde GmbH", self.company)
		self.filters = {
			"company": self.company.name,
			"from_date": today(),
			"to_date": today(),
			"temporary_against_account_number": "9999",
		}

		make_datev_settings(self.company)
		item = make_item("_Test Item", self.company)
		setup_fiscal_year()

		warehouse = frappe.db.get_value(
			"Item Default",
			{"parent": item.name, "company": self.company.name},
			"default_warehouse",
		)

		income_account = frappe.db.get_value(
			"Account", {"account_number": "4200", "company": self.company.name}, "name"
		)

		tax_account = frappe.db.get_value(
			"Account", {"account_number": "3806", "company": self.company.name}, "name"
		)

		si = create_sales_invoice(
			company=self.company.name,
			customer=self.customer.name,
			currency=self.company.default_currency,
			debit_to=self.customer.accounts[0].account,
			income_account=income_account,
			expense_account="6990 - Herstellungskosten - _TG",
			cost_center=self.company.cost_center,
			warehouse=warehouse,
			item=item.name,
			do_not_save=1,
		)

		si.append(
			"taxes",
			{
				"charge_type": "On Net Total",
				"account_head": tax_account,
				"description": "Umsatzsteuer 19 %",
				"rate": 19,
				"cost_center": self.company.cost_center,
			},
		)

		si.cost_center = self.company.cost_center

		si.save()
		si.submit()

	def test_columns(self):
		def is_subset(get_data, allowed_keys):
			"""
			Validate that the dict contains only allowed keys.

			Params:
			get_data -- Function that returns a list of dicts.
			allowed_keys -- List of allowed keys
			"""
			data = get_data(self.filters)
			if data == []:
				# No data and, therefore, no columns is okay
				return True
			actual_set = set(data[0].keys())
			# allowed set must be interpreted as unicode to match the actual set
			allowed_set = set({frappe.as_unicode(key) for key in allowed_keys})
			return actual_set.issubset(allowed_set)

		self.assertTrue(is_subset(get_transactions, Transactions.COLUMNS))
		self.assertTrue(is_subset(get_customers, DebtorsCreditors.COLUMNS))
		self.assertTrue(is_subset(get_suppliers, DebtorsCreditors.COLUMNS))
		self.assertTrue(is_subset(get_account_names, AccountNames.COLUMNS))

	def test_header(self):
		self.assertTrue(Transactions.DATA_CATEGORY in get_header(self.filters, Transactions))
		self.assertTrue(AccountNames.DATA_CATEGORY in get_header(self.filters, AccountNames))
		self.assertTrue(DebtorsCreditors.DATA_CATEGORY in get_header(self.filters, DebtorsCreditors))

	def test_csv(self):
		test_data = [
			{
				"Umsatz (ohne Soll/Haben-Kz)": 100,
				"Soll/Haben-Kennzeichen": "H",
				"Kontonummer": "4200",
				"Gegenkonto (ohne BU-Schlüssel)": "10000",
				"Belegdatum": today(),
				"Buchungstext": "No remark",
				"Beleginfo - Art 1": "Sales Invoice",
				"Beleginfo - Inhalt 1": "SINV-0001",
			}
		]
		get_datev_csv(data=test_data, filters=self.filters, csv_class=Transactions)

	def test_download(self):
		"""Assert that the returned file is a ZIP file."""
		download_datev_csv(self.filters)

		# zipfile.is_zipfile() expects a file-like object
		zip_buffer = BytesIO()
		zip_buffer.write(frappe.response["filecontent"])

		self.assertTrue(zipfile.is_zipfile(zip_buffer))


class TestDatevSalesInvoiceGrouping(TestCase):
	def test_execute_applies_grouping_and_mapping_before_returning_rows(self):
		raw_transactions = [
			{
				"Konto": "4300",
				"Gegenkonto (ohne BU-Schlüssel)": "10483",
				"BU-Schlüssel": "7",
				"Belegdatum": today(),
				"Belegfeld 1": "ACC-SINV-2026-00010",
				"Beleginfo - Art 1": "Sales Invoice",
			}
		]
		grouped_transactions = [
			{
				"Konto": "4300",
				"Gegenkonto (ohne BU-Schlüssel)": "10483",
				"BU-Schlüssel": "7",
				"Belegdatum": today(),
				"Belegfeld 1": "ACC-SINV-2026-00010",
				"Beleginfo - Art 1": "Sales Invoice",
			},
			{
				"Konto": "6990",
				"Gegenkonto (ohne BU-Schlüssel)": "10483",
				"BU-Schlüssel": "7",
				"Belegdatum": today(),
				"Belegfeld 1": "ACC-SINV-2026-00010",
				"Beleginfo - Art 1": "Sales Invoice",
			},
		]
		payment_grouped_transactions = list(grouped_transactions)
		journal_grouped_transactions = list(payment_grouped_transactions)
		mapped_transactions = [
			{
				"Konto": "4300",
				"Gegenkonto (ohne BU-Schlüssel)": "4300",
				"BU-Schlüssel": "7",
				"Belegdatum": today(),
				"Belegfeld 1": "ACC-SINV-2026-00010",
				"Beleginfo - Art 1": "Sales Invoice",
			},
			{
				"Konto": "6990",
				"Gegenkonto (ohne BU-Schlüssel)": "6990",
				"BU-Schlüssel": "7",
				"Belegdatum": today(),
				"Belegfeld 1": "ACC-SINV-2026-00010",
				"Beleginfo - Art 1": "Sales Invoice",
			},
		]
		filters = {
			"company": "_Test GmbH",
			"from_date": today(),
			"to_date": today(),
			"voucher_type": "Sales Invoice",
		}

		with (
			patch("gaertnerei_berger.gb_datev.report.datev.datev.validate", return_value=True),
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.frappe.get_value",
				return_value=("9999", "9998"),
			),
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.get_transactions",
				return_value=raw_transactions,
			) as get_transactions_mock,
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.group_sales_invoice_buchungsstapel",
				return_value=grouped_transactions,
			) as group_mock,
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.group_payment_entry_buchungsstapel",
				return_value=payment_grouped_transactions,
			) as payment_group_mock,
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.group_journal_entry_buchungsstapel",
				return_value=journal_grouped_transactions,
			) as journal_group_mock,
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.apply_buchungsstapel_mapping",
				return_value=mapped_transactions,
			) as map_mock,
		):
			columns, data = execute(filters)

		self.assertEqual(
			[column["fieldname"] for column in columns[:5]],
			[
				"Umsatz (ohne Soll/Haben-Kz)",
				"Soll/Haben-Kennzeichen",
				"Konto",
				"Gegenkonto (ohne BU-Schlüssel)",
				"BU-Schlüssel",
			],
		)
		self.assertEqual(
			[data_row[2:5] for data_row in data],
			[["4300", "4300", "7"], ["6990", "6990", "7"]],
		)
		self.assertEqual(get_transactions_mock.call_args.args[0]["against_account"], "9999")
		self.assertEqual(get_transactions_mock.call_args.args[0]["opening_account"], "9998")
		group_mock.assert_called_once_with(raw_transactions, get_transactions_mock.call_args.args[0])
		payment_group_mock.assert_called_once_with(
			grouped_transactions, get_transactions_mock.call_args.args[0]
		)
		journal_group_mock.assert_called_once_with(
			payment_grouped_transactions, get_transactions_mock.call_args.args[0]
		)
		map_mock.assert_called_once_with(
			journal_grouped_transactions, get_transactions_mock.call_args.args[0]
		)

	def test_download_applies_journal_entry_grouping_before_csv_export(self):
		raw_transactions = [
			{
				"Konto": "4400",
				"Gegenkonto (ohne BU-Schlüssel)": "10483",
				"BU-Schlüssel": "",
				"Belegdatum": today(),
				"Belegfeld 1": "ACC-JV-2026-00003",
				"Beleginfo - Art 1": "Journal Entry",
			}
		]
		sales_grouped_transactions = list(raw_transactions)
		payment_grouped_transactions = list(sales_grouped_transactions)
		journal_grouped_transactions = [
			{
				"Konto": "4400",
				"Gegenkonto (ohne BU-Schlüssel)": "10483",
				"BU-Schlüssel": "19",
				"Belegdatum": today(),
				"Belegfeld 1": "ACC-JV-2026-00003",
				"Beleginfo - Art 1": "Journal Entry",
			}
		]
		mapped_transactions = list(journal_grouped_transactions)
		filters = {
			"company": "_Test GmbH",
			"from_date": today(),
			"to_date": today(),
			"voucher_type": "Journal Entry",
		}
		datev_settings = frappe._dict(
			{
				"account_number_length": 4,
				"temporary_against_account_number": "9999",
				"opening_against_account_number": "9998",
			}
		)

		with (
			patch("gaertnerei_berger.gb_datev.report.datev.datev.frappe.only_for"),
			patch("gaertnerei_berger.gb_datev.report.datev.datev.validate"),
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.get_fiscal_year",
				return_value=("2026", today()),
			),
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.frappe.get_value",
				return_value="SKR04 mit Kontonummern",
			),
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.frappe.get_doc",
				return_value=datev_settings,
			),
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.get_transactions",
				return_value=raw_transactions,
			) as get_transactions_mock,
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.group_sales_invoice_buchungsstapel",
				return_value=sales_grouped_transactions,
			) as sales_group_mock,
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.group_payment_entry_buchungsstapel",
				return_value=payment_grouped_transactions,
			) as payment_group_mock,
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.group_journal_entry_buchungsstapel",
				return_value=journal_grouped_transactions,
			) as journal_group_mock,
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.apply_buchungsstapel_mapping",
				return_value=mapped_transactions,
			) as map_mock,
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.get_account_names",
				return_value=[],
			),
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.get_customers",
				return_value=[],
			),
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.get_suppliers",
				return_value=[],
			),
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.get_datev_csv",
				return_value="csv-data",
			),
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.zip_and_download",
			) as zip_mock,
		):
			download_datev_csv(filters)

		self.assertEqual(get_transactions_mock.call_args.args[0]["against_account"], "9999")
		self.assertEqual(get_transactions_mock.call_args.args[0]["opening_account"], "9998")
		sales_group_mock.assert_called_once_with(raw_transactions, get_transactions_mock.call_args.args[0])
		payment_group_mock.assert_called_once_with(
			sales_grouped_transactions, get_transactions_mock.call_args.args[0]
		)
		journal_group_mock.assert_called_once_with(
			payment_grouped_transactions, get_transactions_mock.call_args.args[0]
		)
		map_mock.assert_called_once_with(
			journal_grouped_transactions, get_transactions_mock.call_args.args[0]
		)
		self.assertTrue(zip_mock.called)

	def test_groups_sales_invoice_rows_only_when_account_and_tax_match(self):
		transactions = [
			{
				"Umsatz (ohne Soll/Haben-Kz)": 42,
				"Soll/Haben-Kennzeichen": "H",
				"Konto": "1200",
				"Gegenkonto (ohne BU-Schlüssel)": "9999",
				"BU-Schlüssel": "",
				"Belegdatum": today(),
				"Belegfeld 1": "RG-260007",
				"Buchungstext": "Accounting Entry for Sales Invoice",
				"Beleginfo - Art 1": "Sales Invoice",
				"Beleginfo - Inhalt 1": "RG-260007",
				"Beleginfo - Art 3": "Customer",
				"Beleginfo - Inhalt 3": "Test Customer",
			},
			{
				"Umsatz (ohne Soll/Haben-Kz)": 10,
				"Soll/Haben-Kennzeichen": "H",
				"Konto": "8400",
				"Gegenkonto (ohne BU-Schlüssel)": "9999",
				"BU-Schlüssel": "",
				"Belegdatum": today(),
				"Belegfeld 1": "RG-260007",
				"Buchungstext": "Accounting Entry for Sales Invoice",
				"Beleginfo - Art 1": "Sales Invoice",
				"Beleginfo - Inhalt 1": "RG-260007",
			},
			{
				"Umsatz (ohne Soll/Haben-Kz)": 7.5,
				"Soll/Haben-Kennzeichen": "H",
				"Konto": "3806",
				"Gegenkonto (ohne BU-Schlüssel)": "9999",
				"BU-Schlüssel": "",
				"Belegdatum": today(),
				"Belegfeld 1": "RG-260007",
				"Buchungstext": "Accounting Entry for Sales Invoice",
				"Beleginfo - Art 1": "Sales Invoice",
				"Beleginfo - Inhalt 1": "RG-260007",
			},
			{
				"Umsatz (ohne Soll/Haben-Kz)": 5,
				"Soll/Haben-Kennzeichen": "H",
				"Konto": "1776",
				"Gegenkonto (ohne BU-Schlüssel)": "9999",
				"BU-Schlüssel": "",
				"Belegdatum": today(),
				"Belegfeld 1": "ACC-PAY-0001",
				"Buchungstext": "Payment Entry",
				"Beleginfo - Art 1": "Payment Entry",
				"Beleginfo - Inhalt 1": "ACC-PAY-0001",
			},
		]
		sales_invoice = frappe._dict(
			{
				"name": "RG-260007",
				"company": "_Test GmbH",
				"customer": "Test Customer",
				"debit_to": "Debtors - _TG",
				"items": [
					frappe._dict(
						{
							"custom_datev_account_no": "8400",
							"custom_bu_schlussel": "",
							"item_tax_template": "DE Standard 19",
							"base_net_amount": 10,
						}
					),
					frappe._dict(
						{
							"custom_datev_account_no": "8400",
							"custom_bu_schlussel": "",
							"item_tax_template": "DE Standard 19",
							"base_net_amount": 15,
						}
					),
					frappe._dict(
						{
							"custom_datev_account_no": "8400",
							"custom_bu_schlussel": "",
							"item_tax_template": "DE Reduced 7",
							"base_net_amount": 7,
						}
					),
					frappe._dict(
						{
							"custom_datev_account_no": "8300",
							"custom_bu_schlussel": "",
							"item_tax_template": "DE Standard 19",
							"base_net_amount": 9,
						}
					),
					frappe._dict(
						{
							"custom_datev_account_no": "4400",
							"custom_bu_schlussel": "",
							"item_tax_template": "EU Reverse Charge",
							"base_net_amount": 11,
						}
					),
				],
			}
		)

		with (
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.load_voucher_doc",
				return_value=sales_invoice,
			),
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.frappe.db.get_value",
				side_effect=["10001"],
			),
		):
			grouped = group_sales_invoice_buchungsstapel(
				transactions, {"company": "_Test GmbH", "against_account": "9999"}
			)

		sales_rows = [row for row in grouped if row["Beleginfo - Art 1"] == "Sales Invoice"]
		self.assertEqual(len(sales_rows), 4)
		self.assertEqual(
			{(row["Konto"], float(row["Umsatz (ohne Soll/Haben-Kz)"])) for row in sales_rows},
			{("8400", 25.0), ("8400", 7.0), ("8300", 9.0), ("4400", 11.0)},
		)
		self.assertEqual(
			{row["Gegenkonto (ohne BU-Schlüssel)"] for row in sales_rows},
			{"10001"},
		)

		other_rows = [row for row in grouped if row["Beleginfo - Art 1"] != "Sales Invoice"]
		self.assertEqual(len(other_rows), 1)
		self.assertEqual(other_rows[0]["Belegfeld 1"], "ACC-PAY-0001")

	def test_groups_purchase_invoice_rows_by_expense_account_and_tax_match(self):
		transactions = [
			{
				"Umsatz (ohne Soll/Haben-Kz)": 42,
				"Soll/Haben-Kennzeichen": "S",
				"Konto": "70000",
				"Gegenkonto (ohne BU-Schlüssel)": "9999",
				"BU-Schlüssel": "",
				"Belegdatum": today(),
				"Belegfeld 1": "PINV-260007",
				"Buchungstext": "Accounting Entry for Purchase Invoice",
				"Beleginfo - Art 1": "Purchase Invoice",
				"Beleginfo - Inhalt 1": "PINV-260007",
				"Beleginfo - Art 3": "Supplier",
				"Beleginfo - Inhalt 3": "Test Supplier",
			},
			{
				"Umsatz (ohne Soll/Haben-Kz)": 10,
				"Soll/Haben-Kennzeichen": "S",
				"Konto": "3400",
				"Gegenkonto (ohne BU-Schlüssel)": "9999",
				"BU-Schlüssel": "",
				"Belegdatum": today(),
				"Belegfeld 1": "PINV-260007",
				"Buchungstext": "Accounting Entry for Purchase Invoice",
				"Beleginfo - Art 1": "Purchase Invoice",
				"Beleginfo - Inhalt 1": "PINV-260007",
			},
			{
				"Umsatz (ohne Soll/Haben-Kz)": 7.5,
				"Soll/Haben-Kennzeichen": "S",
				"Konto": "1406",
				"Gegenkonto (ohne BU-Schlüssel)": "9999",
				"BU-Schlüssel": "",
				"Belegdatum": today(),
				"Belegfeld 1": "PINV-260007",
				"Buchungstext": "Accounting Entry for Purchase Invoice",
				"Beleginfo - Art 1": "Purchase Invoice",
				"Beleginfo - Inhalt 1": "PINV-260007",
			},
			{
				"Umsatz (ohne Soll/Haben-Kz)": 5,
				"Soll/Haben-Kennzeichen": "H",
				"Konto": "1776",
				"Gegenkonto (ohne BU-Schlüssel)": "9999",
				"BU-Schlüssel": "",
				"Belegdatum": today(),
				"Belegfeld 1": "ACC-PAY-0001",
				"Buchungstext": "Payment Entry",
				"Beleginfo - Art 1": "Payment Entry",
				"Beleginfo - Inhalt 1": "ACC-PAY-0001",
			},
		]
		purchase_invoice = frappe._dict(
			{
				"name": "PINV-260007",
				"company": "_Test GmbH",
				"supplier": "Test Supplier",
				"credit_to": "Creditors - _TG",
				"items": [
					frappe._dict(
						{
							"expense_account": "Expense A",
							"custom_bu_schlussel": "",
							"item_tax_template": "DE Standard 19",
							"base_net_amount": 10,
						}
					),
					frappe._dict(
						{
							"expense_account": "Expense A",
							"custom_bu_schlussel": "",
							"item_tax_template": "DE Standard 19",
							"base_net_amount": 15,
						}
					),
					frappe._dict(
						{
							"expense_account": "Expense A",
							"custom_bu_schlussel": "",
							"item_tax_template": "DE Reduced 7",
							"base_net_amount": 7,
						}
					),
					frappe._dict(
						{
							"expense_account": "Expense B",
							"custom_bu_schlussel": "",
							"item_tax_template": "DE Standard 19",
							"base_net_amount": 9,
						}
					),
				],
			}
		)

		with (
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.load_voucher_doc",
				return_value=purchase_invoice,
			),
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.frappe.db.get_value",
				side_effect=["70001", "3400", "3400", "3400", "3300"],
			),
		):
			grouped = group_sales_invoice_buchungsstapel(
				transactions, {"company": "_Test GmbH", "against_account": "9999"}
			)

		purchase_rows = [row for row in grouped if row["Beleginfo - Art 1"] == "Purchase Invoice"]
		self.assertEqual(len(purchase_rows), 3)
		self.assertEqual(
			{(row["Konto"], float(row["Umsatz (ohne Soll/Haben-Kz)"])) for row in purchase_rows},
			{("3400", 25.0), ("3400", 7.0), ("3300", 9.0)},
		)
		self.assertEqual(
			{row["Gegenkonto (ohne BU-Schlüssel)"] for row in purchase_rows},
			{"70001"},
		)
		self.assertEqual(
			{(row["Konto"], row["Soll/Haben-Kennzeichen"]) for row in purchase_rows},
			{("3400", "S"), ("3300", "S")},
		)

		other_rows = [row for row in grouped if row["Beleginfo - Art 1"] != "Purchase Invoice"]
		self.assertEqual(len(other_rows), 1)
		self.assertEqual(other_rows[0]["Belegfeld 1"], "ACC-PAY-0001")

	def test_groups_receive_payment_entry_rows_with_blank_bu_schluessel(self):
		transactions = [
			{
				"Umsatz (ohne Soll/Haben-Kz)": 119,
				"Soll/Haben-Kennzeichen": "H",
				"Konto": "1400",
				"Gegenkonto (ohne BU-Schlüssel)": "9999",
				"BU-Schlüssel": "",
				"Belegdatum": today(),
				"Belegfeld 1": "ACC-PAY-2026-00001",
				"Buchungstext": "Payment Entry",
				"Beleginfo - Art 1": "Payment Entry",
				"Beleginfo - Inhalt 1": "ACC-PAY-2026-00001",
				"Beleginfo - Art 3": "Customer",
				"Beleginfo - Inhalt 3": "Test Customer",
			},
			{
				"Umsatz (ohne Soll/Haben-Kz)": 119,
				"Soll/Haben-Kennzeichen": "S",
				"Konto": "1200",
				"Gegenkonto (ohne BU-Schlüssel)": "9999",
				"BU-Schlüssel": "",
				"Belegdatum": today(),
				"Belegfeld 1": "ACC-PAY-2026-00001",
				"Buchungstext": "Payment Entry",
				"Beleginfo - Art 1": "Payment Entry",
				"Beleginfo - Inhalt 1": "ACC-PAY-2026-00001",
			},
		]
		payment_entry = frappe._dict(
			{
				"name": "ACC-PAY-2026-00001",
				"payment_type": "Receive",
				"party_type": "Customer",
				"party": "Test Customer",
				"company": "_Test GmbH",
				"paid_from": "Debtors - _TG",
				"paid_to": "Bank - _TG",
			}
		)

		with (
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.load_voucher_doc",
				return_value=payment_entry,
			),
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.get_party_account_number",
				return_value="10001",
			),
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.get_payment_entry_account_number",
				return_value="1200",
			),
		):
			grouped = group_payment_entry_buchungsstapel(
				transactions, {"company": "_Test GmbH", "against_account": "9999"}
			)

		self.assertEqual(len(grouped), 1)
		self.assertEqual(grouped[0]["Konto"], "10001")
		self.assertEqual(grouped[0]["Gegenkonto (ohne BU-Schlüssel)"], "1200")
		self.assertEqual(grouped[0]["BU-Schlüssel"], "")
		self.assertEqual(grouped[0]["Soll/Haben-Kennzeichen"], "H")

	def test_groups_pay_payment_entry_rows_with_blank_bu_schluessel(self):
		transactions = [
			{
				"Umsatz (ohne Soll/Haben-Kz)": 119,
				"Soll/Haben-Kennzeichen": "S",
				"Konto": "1600",
				"Gegenkonto (ohne BU-Schlüssel)": "9999",
				"BU-Schlüssel": "19",
				"Belegdatum": today(),
				"Belegfeld 1": "ACC-PAY-2026-00009",
				"Buchungstext": "Payment Entry",
				"Beleginfo - Art 1": "Payment Entry",
				"Beleginfo - Inhalt 1": "ACC-PAY-2026-00009",
				"Beleginfo - Art 3": "Supplier",
				"Beleginfo - Inhalt 3": "Test Supplier",
			},
			{
				"Umsatz (ohne Soll/Haben-Kz)": 119,
				"Soll/Haben-Kennzeichen": "H",
				"Konto": "1200",
				"Gegenkonto (ohne BU-Schlüssel)": "9999",
				"BU-Schlüssel": "",
				"Belegdatum": today(),
				"Belegfeld 1": "ACC-PAY-2026-00009",
				"Buchungstext": "Payment Entry",
				"Beleginfo - Art 1": "Payment Entry",
				"Beleginfo - Inhalt 1": "ACC-PAY-2026-00009",
			},
		]
		payment_entry = frappe._dict(
			{
				"name": "ACC-PAY-2026-00009",
				"payment_type": "Pay",
				"party_type": "Supplier",
				"party": "Test Supplier",
				"company": "_Test GmbH",
				"paid_from": "Bank - _TG",
				"paid_to": "Creditors - _TG",
			}
		)

		with (
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.load_voucher_doc",
				return_value=payment_entry,
			),
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.get_party_account_number",
				return_value="70001",
			),
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.get_payment_entry_account_number",
				return_value="1200",
			),
		):
			grouped = group_payment_entry_buchungsstapel(
				transactions, {"company": "_Test GmbH", "against_account": "9999"}
			)

		self.assertEqual(len(grouped), 1)
		self.assertEqual(grouped[0]["Konto"], "70001")
		self.assertEqual(grouped[0]["Gegenkonto (ohne BU-Schlüssel)"], "1200")
		self.assertEqual(grouped[0]["BU-Schlüssel"], "")
		self.assertEqual(grouped[0]["Soll/Haben-Kennzeichen"], "S")

	def test_leaves_complex_payment_entry_rows_untouched(self):
		transactions = [
			{
				"Umsatz (ohne Soll/Haben-Kz)": 100,
				"Soll/Haben-Kennzeichen": "H",
				"Konto": "1400",
				"Gegenkonto (ohne BU-Schlüssel)": "9999",
				"BU-Schlüssel": "",
				"Belegdatum": today(),
				"Belegfeld 1": "ACC-PAY-2026-00002",
				"Beleginfo - Art 1": "Payment Entry",
			},
			{
				"Umsatz (ohne Soll/Haben-Kz)": 95,
				"Soll/Haben-Kennzeichen": "S",
				"Konto": "1200",
				"Gegenkonto (ohne BU-Schlüssel)": "9999",
				"BU-Schlüssel": "",
				"Belegdatum": today(),
				"Belegfeld 1": "ACC-PAY-2026-00002",
				"Beleginfo - Art 1": "Payment Entry",
			},
			{
				"Umsatz (ohne Soll/Haben-Kz)": 5,
				"Soll/Haben-Kennzeichen": "S",
				"Konto": "4970",
				"Gegenkonto (ohne BU-Schlüssel)": "9999",
				"BU-Schlüssel": "",
				"Belegdatum": today(),
				"Belegfeld 1": "ACC-PAY-2026-00002",
				"Beleginfo - Art 1": "Payment Entry",
			},
		]

		grouped = group_payment_entry_buchungsstapel(
			transactions, {"company": "_Test GmbH", "against_account": "9999"}
		)

		self.assertEqual(grouped, transactions)

	def test_groups_sales_journal_entry_into_single_line(self):
		transactions = [
			{
				"Umsatz (ohne Soll/Haben-Kz)": 119,
				"Soll/Haben-Kennzeichen": "S",
				"Konto": "10001",
				"Gegenkonto (ohne BU-Schlüssel)": "9999",
				"BU-Schlüssel": "",
				"Belegdatum": today(),
				"Belegfeld 1": "ACC-JV-2026-00003",
				"Buchungstext": "Sales Journal Entry",
				"Beleginfo - Art 1": "Journal Entry",
				"Beleginfo - Inhalt 1": "ACC-JV-2026-00003",
				"Beleginfo - Art 3": "Customer",
				"Beleginfo - Inhalt 3": "Test Customer",
			},
			{
				"Umsatz (ohne Soll/Haben-Kz)": 100,
				"Soll/Haben-Kennzeichen": "H",
				"Konto": "8400",
				"Gegenkonto (ohne BU-Schlüssel)": "9999",
				"BU-Schlüssel": "",
				"Belegdatum": today(),
				"Belegfeld 1": "ACC-JV-2026-00003",
				"Buchungstext": "Sales Journal Entry",
				"Beleginfo - Art 1": "Journal Entry",
				"Beleginfo - Inhalt 1": "ACC-JV-2026-00003",
			},
			{
				"Umsatz (ohne Soll/Haben-Kz)": 19,
				"Soll/Haben-Kennzeichen": "H",
				"Konto": "3806",
				"Gegenkonto (ohne BU-Schlüssel)": "9999",
				"BU-Schlüssel": "",
				"Belegdatum": today(),
				"Belegfeld 1": "ACC-JV-2026-00003",
				"Buchungstext": "Sales Journal Entry",
				"Beleginfo - Art 1": "Journal Entry",
				"Beleginfo - Inhalt 1": "ACC-JV-2026-00003",
			},
		]
		journal_entry = frappe._dict(
			{
				"name": "ACC-JV-2026-00003",
				"company": "_Test GmbH",
				"accounts": [
					frappe._dict(
						{
							"account": "Debtors - _TG",
							"party_type": "Customer",
							"party": "Test Customer",
							"debit_in_account_currency": 119,
							"credit_in_account_currency": 0,
						}
					),
					frappe._dict(
						{
							"account": "Sales - _TG",
							"debit_in_account_currency": 0,
							"credit_in_account_currency": 100,
							"custom_datev_account_no": "8400",
						}
					),
					frappe._dict(
						{
							"account": "VAT 19 - _TG",
							"debit_in_account_currency": 0,
							"credit_in_account_currency": 19,
						}
					),
				],
			}
		)

		with (
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.load_voucher_doc",
				return_value=journal_entry,
			),
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.get_journal_entry_account_type",
				side_effect=lambda account: {"Debtors - _TG": "Receivable"}.get(account, ""),
			),
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.get_journal_entry_bu_schluessel",
				side_effect=lambda row: "19" if row.account == "VAT 19 - _TG" else "",
			),
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.is_journal_entry_tax_row",
				side_effect=lambda row: row.account == "VAT 19 - _TG",
			),
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.get_party_account_number",
				return_value="10001",
			),
		):
			grouped = group_journal_entry_buchungsstapel(
				transactions, {"company": "_Test GmbH", "against_account": "9999"}
			)

		self.assertEqual(len(grouped), 1)
		self.assertEqual(grouped[0]["Konto"], "8400")
		self.assertEqual(grouped[0]["Gegenkonto (ohne BU-Schlüssel)"], "10001")
		self.assertEqual(grouped[0]["BU-Schlüssel"], "19")
		self.assertEqual(float(grouped[0]["Umsatz (ohne Soll/Haben-Kz)"]), 100.0)
		self.assertEqual(grouped[0]["Soll/Haben-Kennzeichen"], "H")

	def test_groups_purchase_journal_entry_into_single_line(self):
		transactions = [
			{
				"Umsatz (ohne Soll/Haben-Kz)": 119,
				"Soll/Haben-Kennzeichen": "H",
				"Konto": "70001",
				"Gegenkonto (ohne BU-Schlüssel)": "9999",
				"BU-Schlüssel": "",
				"Belegdatum": today(),
				"Belegfeld 1": "ACC-JV-2026-00004",
				"Buchungstext": "Purchase Journal Entry",
				"Beleginfo - Art 1": "Journal Entry",
				"Beleginfo - Inhalt 1": "ACC-JV-2026-00004",
				"Beleginfo - Art 3": "Supplier",
				"Beleginfo - Inhalt 3": "Test Supplier",
			},
			{
				"Umsatz (ohne Soll/Haben-Kz)": 100,
				"Soll/Haben-Kennzeichen": "S",
				"Konto": "3400",
				"Gegenkonto (ohne BU-Schlüssel)": "9999",
				"BU-Schlüssel": "",
				"Belegdatum": today(),
				"Belegfeld 1": "ACC-JV-2026-00004",
				"Buchungstext": "Purchase Journal Entry",
				"Beleginfo - Art 1": "Journal Entry",
				"Beleginfo - Inhalt 1": "ACC-JV-2026-00004",
			},
			{
				"Umsatz (ohne Soll/Haben-Kz)": 19,
				"Soll/Haben-Kennzeichen": "S",
				"Konto": "1406",
				"Gegenkonto (ohne BU-Schlüssel)": "9999",
				"BU-Schlüssel": "",
				"Belegdatum": today(),
				"Belegfeld 1": "ACC-JV-2026-00004",
				"Buchungstext": "Purchase Journal Entry",
				"Beleginfo - Art 1": "Journal Entry",
				"Beleginfo - Inhalt 1": "ACC-JV-2026-00004",
			},
		]
		journal_entry = frappe._dict(
			{
				"name": "ACC-JV-2026-00004",
				"company": "_Test GmbH",
				"accounts": [
					frappe._dict(
						{
							"account": "Creditors - _TG",
							"party_type": "Supplier",
							"party": "Test Supplier",
							"debit_in_account_currency": 0,
							"credit_in_account_currency": 119,
						}
					),
					frappe._dict(
						{
							"account": "Expense - _TG",
							"debit_in_account_currency": 100,
							"credit_in_account_currency": 0,
							"custom_datev_account_no": "3400",
						}
					),
					frappe._dict(
						{
							"account": "Input VAT 19 - _TG",
							"debit_in_account_currency": 19,
							"credit_in_account_currency": 0,
						}
					),
				],
			}
		)

		with (
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.load_voucher_doc",
				return_value=journal_entry,
			),
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.get_journal_entry_account_type",
				side_effect=lambda account: {"Creditors - _TG": "Payable"}.get(account, ""),
			),
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.get_journal_entry_bu_schluessel",
				side_effect=lambda row: "19" if row.account == "Input VAT 19 - _TG" else "",
			),
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.is_journal_entry_tax_row",
				side_effect=lambda row: row.account == "Input VAT 19 - _TG",
			),
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.get_party_account_number",
				return_value="70001",
			),
		):
			grouped = group_journal_entry_buchungsstapel(
				transactions, {"company": "_Test GmbH", "against_account": "9999"}
			)

		self.assertEqual(len(grouped), 1)
		self.assertEqual(grouped[0]["Konto"], "3400")
		self.assertEqual(grouped[0]["Gegenkonto (ohne BU-Schlüssel)"], "70001")
		self.assertEqual(grouped[0]["BU-Schlüssel"], "19")
		self.assertEqual(float(grouped[0]["Umsatz (ohne Soll/Haben-Kz)"]), 100.0)
		self.assertEqual(grouped[0]["Soll/Haben-Kennzeichen"], "S")

	def test_groups_journal_entry_when_tax_account_has_no_unique_bu_schluessel(self):
		transactions = [
			{
				"Umsatz (ohne Soll/Haben-Kz)": 119,
				"Soll/Haben-Kennzeichen": "S",
				"Konto": "10001",
				"Gegenkonto (ohne BU-Schlüssel)": "9999",
				"BU-Schlüssel": "",
				"Belegdatum": today(),
				"Belegfeld 1": "ACC-JV-2026-00005",
				"Buchungstext": "Sales Journal Entry",
				"Beleginfo - Art 1": "Journal Entry",
				"Beleginfo - Inhalt 1": "ACC-JV-2026-00005",
				"Beleginfo - Art 3": "Customer",
				"Beleginfo - Inhalt 3": "Test Customer",
			},
			{
				"Umsatz (ohne Soll/Haben-Kz)": 100,
				"Soll/Haben-Kennzeichen": "H",
				"Konto": "8400",
				"Gegenkonto (ohne BU-Schlüssel)": "9999",
				"BU-Schlüssel": "",
				"Belegdatum": today(),
				"Belegfeld 1": "ACC-JV-2026-00005",
				"Buchungstext": "Sales Journal Entry",
				"Beleginfo - Art 1": "Journal Entry",
				"Beleginfo - Inhalt 1": "ACC-JV-2026-00005",
			},
			{
				"Umsatz (ohne Soll/Haben-Kz)": 19,
				"Soll/Haben-Kennzeichen": "H",
				"Konto": "3806",
				"Gegenkonto (ohne BU-Schlüssel)": "9999",
				"BU-Schlüssel": "",
				"Belegdatum": today(),
				"Belegfeld 1": "ACC-JV-2026-00005",
				"Buchungstext": "Sales Journal Entry",
				"Beleginfo - Art 1": "Journal Entry",
				"Beleginfo - Inhalt 1": "ACC-JV-2026-00005",
			},
		]
		journal_entry = frappe._dict(
			{
				"name": "ACC-JV-2026-00005",
				"company": "_Test GmbH",
				"accounts": [
					frappe._dict(
						{
							"account": "Debtors - _TG",
							"party_type": "Customer",
							"party": "Test Customer",
							"debit_in_account_currency": 119,
							"credit_in_account_currency": 0,
						}
					),
					frappe._dict(
						{
							"account": "Sales - _TG",
							"debit_in_account_currency": 0,
							"credit_in_account_currency": 100,
							"custom_datev_account_no": "8400",
						}
					),
					frappe._dict(
						{
							"account": "VAT 19 - _TG",
							"debit_in_account_currency": 0,
							"credit_in_account_currency": 19,
						}
					),
				],
			}
		)

		with (
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.load_voucher_doc",
				return_value=journal_entry,
			),
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.get_journal_entry_account_type",
				side_effect=lambda account: {"Debtors - _TG": "Receivable"}.get(account, ""),
			),
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.get_journal_entry_bu_schluessel",
				return_value="",
			),
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.is_journal_entry_tax_row",
				side_effect=lambda row: row.account == "VAT 19 - _TG",
			),
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.get_party_account_number",
				return_value="10001",
			),
		):
			grouped = group_journal_entry_buchungsstapel(
				transactions, {"company": "_Test GmbH", "against_account": "9999"}
			)

		self.assertEqual(len(grouped), 1)
		self.assertEqual(grouped[0]["Konto"], "8400")
		self.assertEqual(grouped[0]["Gegenkonto (ohne BU-Schlüssel)"], "10001")
		self.assertEqual(grouped[0]["BU-Schlüssel"], "")
		self.assertEqual(float(grouped[0]["Umsatz (ohne Soll/Haben-Kz)"]), 100.0)
		self.assertEqual(grouped[0]["Soll/Haben-Kennzeichen"], "H")

	def test_preserves_grouped_sales_invoice_bu_schluessel_from_mapping_override(self):
		transactions = [
			{
				"Konto": "8400",
				"Gegenkonto (ohne BU-Schlüssel)": "10001",
				"BU-Schlüssel": "19",
				"Belegfeld 1": "ACC-SINV-2026-00011",
				"Beleginfo - Art 1": "Sales Invoice",
			},
			{
				"Konto": "8400",
				"Gegenkonto (ohne BU-Schlüssel)": "10001",
				"BU-Schlüssel": "7",
				"Belegfeld 1": "ACC-SINV-2026-00011",
				"Beleginfo - Art 1": "Sales Invoice",
			},
			{
				"Konto": "1776",
				"Gegenkonto (ohne BU-Schlüssel)": "10001",
				"BU-Schlüssel": "",
				"Belegfeld 1": "ACC-PAY-0001",
				"Beleginfo - Art 1": "Payment Entry",
			},
		]

		with (
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.get_buchungsstapel_mappings",
				return_value={
					"Sales Invoice": [
						frappe._dict(
							{
								"map_to_field": "custom_bu_schlussel",
								"map_to_column": "BU-Schlüssel",
							}
						)
					],
					"Payment Entry": [
						frappe._dict(
							{
								"map_to_field": "reference_no",
								"map_to_column": "BU-Schlüssel",
							}
						)
					],
				},
			),
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.get_account_maps",
				return_value=({}, {}),
			),
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.load_voucher_doc",
				side_effect=[
					frappe._dict({"name": "sales-invoice"}),
					frappe._dict({"name": "payment-entry"}),
				],
			),
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.resolve_map_to_value",
				return_value="mapped-payment",
			) as resolve_map,
		):
			mapped = apply_buchungsstapel_mapping(transactions, {"company": "_Test GmbH"})

		sales_rows = [row for row in mapped if row["Beleginfo - Art 1"] == "Sales Invoice"]
		self.assertEqual([row["BU-Schlüssel"] for row in sales_rows], ["19", "7"])

		payment_rows = [row for row in mapped if row["Beleginfo - Art 1"] == "Payment Entry"]
		self.assertEqual([row["BU-Schlüssel"] for row in payment_rows], ["mapped-payment"])
		self.assertEqual(resolve_map.call_count, 1)

	def test_preserves_purchase_invoice_bu_schluessel_from_mapping_override(self):
		transactions = [
			{
				"Konto": "3400",
				"Gegenkonto (ohne BU-Schlüssel)": "70000",
				"BU-Schlüssel": "9",
				"Belegfeld 1": "ACC-PINV-2026-00011",
				"Beleginfo - Art 1": "Purchase Invoice",
			},
			{
				"Konto": "1576",
				"Gegenkonto (ohne BU-Schlüssel)": "70000",
				"BU-Schlüssel": "",
				"Belegfeld 1": "ACC-PAY-0001",
				"Beleginfo - Art 1": "Payment Entry",
			},
		]

		with (
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.get_buchungsstapel_mappings",
				return_value={
					"Purchase Invoice": [
						frappe._dict(
							{
								"map_to_field": "custom_bu_schlussel",
								"map_to_column": "BU-Schlüssel",
							}
						)
					],
					"Payment Entry": [
						frappe._dict(
							{
								"map_to_field": "reference_no",
								"map_to_column": "BU-Schlüssel",
							}
						)
					],
				},
			),
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.get_account_maps",
				return_value=({}, {}),
			),
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.load_voucher_doc",
				side_effect=[
					frappe._dict({"name": "purchase-invoice"}),
					frappe._dict({"name": "payment-entry"}),
				],
			),
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.resolve_map_to_value",
				return_value="mapped-payment",
			) as resolve_map,
		):
			mapped = apply_buchungsstapel_mapping(transactions, {"company": "_Test GmbH"})

		purchase_rows = [row for row in mapped if row["Beleginfo - Art 1"] == "Purchase Invoice"]
		self.assertEqual([row["BU-Schlüssel"] for row in purchase_rows], ["9"])

		payment_rows = [row for row in mapped if row["Beleginfo - Art 1"] == "Payment Entry"]
		self.assertEqual([row["BU-Schlüssel"] for row in payment_rows], ["mapped-payment"])
		self.assertEqual(resolve_map.call_count, 1)

	def test_applies_grouped_sales_invoice_konto_from_parent_mapping_override(self):
		transactions = [
			{
				"Konto": "8400",
				"Gegenkonto (ohne BU-Schlüssel)": "10001",
				"BU-Schlüssel": "19",
				"Belegfeld 1": "ACC-SINV-2026-00011",
				"Beleginfo - Art 1": "Sales Invoice",
			},
			{
				"Konto": "8300",
				"Gegenkonto (ohne BU-Schlüssel)": "10001",
				"BU-Schlüssel": "19",
				"Belegfeld 1": "ACC-SINV-2026-00011",
				"Beleginfo - Art 1": "Sales Invoice",
			},
			{
				"Konto": "1776",
				"Gegenkonto (ohne BU-Schlüssel)": "10001",
				"BU-Schlüssel": "",
				"Belegfeld 1": "ACC-PAY-0001",
				"Beleginfo - Art 1": "Payment Entry",
			},
		]

		with (
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.get_buchungsstapel_mappings",
				return_value={
					"Sales Invoice": [
						frappe._dict(
							{
								"map_to_field": "custom_datev_account_no",
								"map_to_column": "Konto",
							}
						)
					],
					"Payment Entry": [
						frappe._dict(
							{
								"map_to_field": "reference_no",
								"map_to_column": "Konto",
							}
						)
					],
				},
			),
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.get_account_maps",
				return_value=({}, {}),
			),
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.load_voucher_doc",
				side_effect=[
					frappe._dict({"name": "sales-invoice", "custom_datev_account_no": "9999"}),
					frappe._dict({"name": "payment-entry", "reference_no": "mapped-payment"}),
				],
			),
		):
			mapped = apply_buchungsstapel_mapping(transactions, {"company": "_Test GmbH"})

		sales_rows = [row for row in mapped if row["Beleginfo - Art 1"] == "Sales Invoice"]
		self.assertEqual([row["Konto"] for row in sales_rows], ["9999", "9999"])

		payment_rows = [row for row in mapped if row["Beleginfo - Art 1"] == "Payment Entry"]
		self.assertEqual([row["Konto"] for row in payment_rows], ["mapped-payment"])

	def test_applies_grouped_sales_invoice_konto_override_for_non_account_parent_mapping(self):
		transactions = [
			{
				"Konto": "8400",
				"Gegenkonto (ohne BU-Schlüssel)": "10001",
				"BU-Schlüssel": "19",
				"Belegfeld 1": "ACC-SINV-2026-00012",
				"Beleginfo - Art 1": "Sales Invoice",
			},
			{
				"Konto": "8300",
				"Gegenkonto (ohne BU-Schlüssel)": "10001",
				"BU-Schlüssel": "19",
				"Belegfeld 1": "ACC-SINV-2026-00012",
				"Beleginfo - Art 1": "Sales Invoice",
			},
			{
				"Konto": "1776",
				"Gegenkonto (ohne BU-Schlüssel)": "10001",
				"BU-Schlüssel": "",
				"Belegfeld 1": "ACC-PAY-0001",
				"Beleginfo - Art 1": "Payment Entry",
			},
		]

		with (
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.get_buchungsstapel_mappings",
				return_value={
					"Sales Invoice": [
						frappe._dict(
							{
								"map_to_field": "customer",
								"map_to_column": "Konto",
							}
						)
					],
					"Payment Entry": [
						frappe._dict(
							{
								"map_to_field": "reference_no",
								"map_to_column": "Konto",
							}
						)
					],
				},
			),
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.get_account_maps",
				return_value=({}, {}),
			),
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.load_voucher_doc",
				side_effect=[
					frappe._dict({"name": "sales-invoice", "customer": "Test Customer"}),
					frappe._dict({"name": "payment-entry", "reference_no": "mapped-payment"}),
				],
			),
		):
			mapped = apply_buchungsstapel_mapping(transactions, {"company": "_Test GmbH"})

		sales_rows = [row for row in mapped if row["Beleginfo - Art 1"] == "Sales Invoice"]
		self.assertEqual([row["Konto"] for row in sales_rows], ["Test Customer", "Test Customer"])

		payment_rows = [row for row in mapped if row["Beleginfo - Art 1"] == "Payment Entry"]
		self.assertEqual([row["Konto"] for row in payment_rows], ["mapped-payment"])


class TestDatevPaymentEntryGrouping(TestCase):
	def test_groups_receive_payment_entry_into_single_line_with_invoice_bu_schluessel(self):
		transactions = [
			{
				"Umsatz (ohne Soll/Haben-Kz)": 119.0,
				"Soll/Haben-Kennzeichen": "H",
				"Konto": "1001",
				"Gegenkonto (ohne BU-Schlüssel)": "9999",
				"BU-Schlüssel": "",
				"Belegdatum": today(),
				"Belegfeld 1": "ACC-PAY-2026-00001",
				"Beleginfo - Art 1": "Payment Entry",
				"Beleginfo - Art 2": "Sales Invoice",
				"Beleginfo - Inhalt 2": "ACC-SINV-2026-00001",
				"Beleginfo - Art 3": "Customer",
				"Beleginfo - Inhalt 3": "DATEV Dummy Customer",
			},
			{
				"Umsatz (ohne Soll/Haben-Kz)": 119.0,
				"Soll/Haben-Kennzeichen": "S",
				"Konto": "1800",
				"Gegenkonto (ohne BU-Schlüssel)": "9999",
				"BU-Schlüssel": "",
				"Belegdatum": today(),
				"Belegfeld 1": "ACC-PAY-2026-00001",
				"Beleginfo - Art 1": "Payment Entry",
			},
		]
		payment_entry = frappe._dict(
			{
				"name": "ACC-PAY-2026-00001",
				"payment_type": "Receive",
				"party_type": "Customer",
				"paid_from": "1001 - DATEV Dummy Customer - GB",
				"paid_to": "1800 - Bank - GB",
				"references": [
					frappe._dict(
						{
							"reference_doctype": "Sales Invoice",
							"reference_name": "ACC-SINV-2026-00001",
						}
					)
				],
			}
		)
		reference_invoice = frappe._dict(
			{
				"name": "ACC-SINV-2026-00001",
				"items": [frappe._dict({"custom_bu_schlussel": "19"})],
			}
		)

		with (
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.load_voucher_doc",
				side_effect=[payment_entry, reference_invoice],
			),
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.frappe.db.get_value",
				side_effect=["1001", "1800"],
			),
		):
			grouped = group_payment_entry_buchungsstapel(
				transactions, {"company": "_Test GmbH", "against_account": "9999"}
			)

		self.assertEqual(len(grouped), 1)
		self.assertEqual(grouped[0]["Konto"], "1001")
		self.assertEqual(grouped[0]["Gegenkonto (ohne BU-Schlüssel)"], "1800")
		self.assertEqual(grouped[0]["BU-Schlüssel"], "19")
		self.assertEqual(grouped[0]["Soll/Haben-Kennzeichen"], "H")

	def test_groups_pay_payment_entry_into_single_line_with_invoice_bu_schluessel(self):
		transactions = [
			{
				"Umsatz (ohne Soll/Haben-Kz)": 59.5,
				"Soll/Haben-Kennzeichen": "S",
				"Konto": "3001",
				"Gegenkonto (ohne BU-Schlüssel)": "9999",
				"BU-Schlüssel": "",
				"Belegdatum": today(),
				"Belegfeld 1": "ACC-PAY-2026-00002",
				"Beleginfo - Art 1": "Payment Entry",
				"Beleginfo - Art 3": "Supplier",
				"Beleginfo - Inhalt 3": "DATEV Dummy Supplier",
			},
			{
				"Umsatz (ohne Soll/Haben-Kz)": 59.5,
				"Soll/Haben-Kennzeichen": "H",
				"Konto": "1800",
				"Gegenkonto (ohne BU-Schlüssel)": "9999",
				"BU-Schlüssel": "",
				"Belegdatum": today(),
				"Belegfeld 1": "ACC-PAY-2026-00002",
				"Beleginfo - Art 1": "Payment Entry",
			},
		]
		payment_entry = frappe._dict(
			{
				"name": "ACC-PAY-2026-00002",
				"payment_type": "Pay",
				"party_type": "Supplier",
				"paid_from": "1800 - Bank - GB",
				"paid_to": "3001 - DATEV Dummy Supplier - GB",
				"references": [
					frappe._dict(
						{
							"reference_doctype": "Purchase Invoice",
							"reference_name": "ACC-PINV-2026-00001",
						}
					)
				],
			}
		)
		reference_invoice = frappe._dict(
			{
				"name": "ACC-PINV-2026-00001",
				"items": [frappe._dict({"custom_bu_schlussel": "9"})],
			}
		)

		with (
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.load_voucher_doc",
				side_effect=[payment_entry, reference_invoice],
			),
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.frappe.db.get_value",
				side_effect=["3001", "1800"],
			),
		):
			grouped = group_payment_entry_buchungsstapel(
				transactions, {"company": "_Test GmbH", "against_account": "9999"}
			)

		self.assertEqual(len(grouped), 1)
		self.assertEqual(grouped[0]["Konto"], "3001")
		self.assertEqual(grouped[0]["Gegenkonto (ohne BU-Schlüssel)"], "1800")
		self.assertEqual(grouped[0]["BU-Schlüssel"], "9")
		self.assertEqual(grouped[0]["Soll/Haben-Kennzeichen"], "S")

	def test_mapping_paid_to_account_outputs_short_account_number(self):
		transactions = [
			{
				"Konto": "1001",
				"Gegenkonto (ohne BU-Schlüssel)": "1800",
				"BU-Schlüssel": "",
				"Belegfeld 1": "ACC-PAY-2026-00001",
				"Beleginfo - Art 1": "Payment Entry",
			}
		]
		voucher_doc = frappe._dict(
			{
				"name": "payment-entry",
				"paid_to": "1800 - Bank - GB",
			}
		)
		voucher_doc.meta = Mock()
		voucher_doc.meta.get_field.return_value = frappe._dict(
			{"fieldtype": "Link", "options": "Account"}
		)

		with (
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.get_buchungsstapel_mappings",
				return_value={
					"Payment Entry": [
						frappe._dict(
							{
								"map_to_field": "paid_to",
								"map_to_column": "Gegenkonto (ohne BU-Schlüssel)",
							}
						)
					]
				},
			),
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.get_account_maps",
				return_value=({}, {"1800 - Bank - GB": "1800"}),
			),
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.load_voucher_doc",
				return_value=voucher_doc,
			),
		):
			mapped = apply_buchungsstapel_mapping(transactions, {"company": "_Test GmbH"})

		self.assertEqual(mapped[0]["Gegenkonto (ohne BU-Schlüssel)"], "1800")
