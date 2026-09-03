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
	get_invoice_item_amount,
	get_journal_entry_bu_schluessel,
	get_payment_entry_params,
	get_purchase_invoice_params,
	get_sales_invoice_params,
	group_payment_entry_buchungsstapel,
	group_journal_entry_buchungsstapel,
	group_sales_invoice_buchungsstapel,
	get_suppliers,
	get_transactions,
	prepare_buchungsstapel_transactions,
	run_query,
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
			"against_account": "9999",
			"opening_account": "9998",
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
				"Umsatz (ohne Soll/Haben-Kz)": 100.5,
				"Soll/Haben-Kennzeichen": "H",
				"Kontonummer": "4200",
				"Gegenkonto (ohne BU-Schlüssel)": "10000",
				"Belegdatum": today(),
				"Buchungstext": "No remark",
				"Beleginfo - Art 1": "Sales Invoice",
				"Beleginfo - Inhalt 1": "SINV-0001",
			}
		]
		comma_csv = get_datev_csv(
			data=test_data,
			filters={**self.filters, "umsatz_decimal_separator": ","},
			csv_class=Transactions,
		)
		self.assertIn(b"100,5", comma_csv)

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
				"gaertnerei_berger.gb_datev.report.datev.datev.get_datev_export_filter_values",
				return_value={
					"against_account": "9999",
					"opening_account": "9998",
					"buchungsstapel_export_mode": "consultant_booking",
					"invoice_amount_basis": "net",
				},
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
				"buchungsstapel_export_mode": "consultant_booking",
				"invoice_amount_basis": "net",
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
				"gaertnerei_berger.gb_datev.report.datev.datev.get_datev_export_filter_values",
				return_value={
					"against_account": "9999",
					"opening_account": "9998",
					"buchungsstapel_export_mode": "consultant_booking",
					"invoice_amount_basis": "net",
				},
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
		self.assertEqual(grouped[0]["Konto"], "1200")
		self.assertEqual(grouped[0]["Gegenkonto (ohne BU-Schlüssel)"], "10001")
		self.assertEqual(grouped[0]["BU-Schlüssel"], "")
		self.assertEqual(grouped[0]["Soll/Haben-Kennzeichen"], "S")

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

	def test_groups_multi_rate_sales_journal_entry_into_multiple_lines(self):
		transactions = [
			{
				"Umsatz (ohne Soll/Haben-Kz)": 47104,
				"Soll/Haben-Kennzeichen": "S",
				"Konto": "10483",
				"Gegenkonto (ohne BU-Schlüssel)": "9999",
				"BU-Schlüssel": "",
				"Belegdatum": today(),
				"Belegfeld 1": "ACC-JV-2026-00007",
				"Buchungstext": "Sales Journal Entry",
				"Beleginfo - Art 1": "Journal Entry",
				"Beleginfo - Inhalt 1": "ACC-JV-2026-00007",
				"Beleginfo - Art 3": "Customer",
				"Beleginfo - Inhalt 3": "K-10483",
			},
			{
				"Umsatz (ohne Soll/Haben-Kz)": 7103,
				"Soll/Haben-Kennzeichen": "H",
				"Konto": "3806",
				"Gegenkonto (ohne BU-Schlüssel)": "9999",
				"BU-Schlüssel": "",
				"Belegdatum": today(),
				"Belegfeld 1": "ACC-JV-2026-00007",
				"Buchungstext": "Sales Journal Entry",
				"Beleginfo - Art 1": "Journal Entry",
				"Beleginfo - Inhalt 1": "ACC-JV-2026-00007",
			},
			{
				"Umsatz (ohne Soll/Haben-Kz)": 2617,
				"Soll/Haben-Kennzeichen": "H",
				"Konto": "3801",
				"Gegenkonto (ohne BU-Schlüssel)": "9999",
				"BU-Schlüssel": "",
				"Belegdatum": today(),
				"Belegfeld 1": "ACC-JV-2026-00007",
				"Buchungstext": "Sales Journal Entry",
				"Beleginfo - Art 1": "Journal Entry",
				"Beleginfo - Inhalt 1": "ACC-JV-2026-00007",
			},
			{
				"Umsatz (ohne Soll/Haben-Kz)": 18692,
				"Soll/Haben-Kennzeichen": "H",
				"Konto": "4300",
				"Gegenkonto (ohne BU-Schlüssel)": "9999",
				"BU-Schlüssel": "",
				"Belegdatum": today(),
				"Belegfeld 1": "ACC-JV-2026-00007",
				"Buchungstext": "Sales Journal Entry",
				"Beleginfo - Art 1": "Journal Entry",
				"Beleginfo - Inhalt 1": "ACC-JV-2026-00007",
			},
			{
				"Umsatz (ohne Soll/Haben-Kz)": 18692,
				"Soll/Haben-Kennzeichen": "H",
				"Konto": "4400",
				"Gegenkonto (ohne BU-Schlüssel)": "9999",
				"BU-Schlüssel": "",
				"Belegdatum": today(),
				"Belegfeld 1": "ACC-JV-2026-00007",
				"Buchungstext": "Sales Journal Entry",
				"Beleginfo - Art 1": "Journal Entry",
				"Beleginfo - Inhalt 1": "ACC-JV-2026-00007",
			},
		]
		journal_entry = frappe._dict(
			{
				"name": "ACC-JV-2026-00007",
				"company": "_Test GmbH",
				"accounts": [
					frappe._dict(
						{
							"account": "10483 - Reha Plus - GB",
							"party_type": "Customer",
							"party": "K-10483",
							"debit_in_account_currency": 47104,
							"credit_in_account_currency": 0,
							"custom_datev_account_no": "10483",
						}
					),
					frappe._dict(
						{
							"account": "3806 - Umsatzsteuer 19 % - GB",
							"debit_in_account_currency": 0,
							"credit_in_account_currency": 7103,
							"custom_datev_account_no": "3806",
						}
					),
					frappe._dict(
						{
							"account": "3801 - Umsatzsteuer 7 % - GB",
							"debit_in_account_currency": 0,
							"credit_in_account_currency": 2617,
							"custom_datev_account_no": "3801",
						}
					),
					frappe._dict(
						{
							"account": "4300 - Erlöse 7 % USt - GB",
							"debit_in_account_currency": 0,
							"credit_in_account_currency": 18692,
							"custom_datev_account_no": "4300",
						}
					),
					frappe._dict(
						{
							"account": "4400 - Erlöse 19 % USt - GB",
							"debit_in_account_currency": 0,
							"credit_in_account_currency": 18692,
							"custom_datev_account_no": "4400",
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
				side_effect=lambda account: {"10483 - Reha Plus - GB": "Receivable"}.get(account, ""),
			),
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.get_journal_entry_bu_schluessel",
				side_effect=lambda row: {
					"3806 - Umsatzsteuer 19 % - GB": "19",
					"3801 - Umsatzsteuer 7 % - GB": "7",
				}.get(row.account, ""),
			),
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.is_journal_entry_tax_row",
				side_effect=lambda row: "Umsatzsteuer" in row.account,
			),
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.get_party_account_number",
				return_value="10483",
			),
		):
			grouped = group_journal_entry_buchungsstapel(
				transactions, {"company": "_Test GmbH", "against_account": "9999"}
			)

		self.assertEqual(len(grouped), 2)
		self.assertEqual(
			{
				(
					row["Konto"],
					row["Gegenkonto (ohne BU-Schlüssel)"],
					row["BU-Schlüssel"],
					float(row["Umsatz (ohne Soll/Haben-Kz)"]),
					row["Soll/Haben-Kennzeichen"],
				)
				for row in grouped
			},
			{
				("4300", "10483", "7", 18692.0, "H"),
				("4400", "10483", "19", 18692.0, "H"),
			},
		)

	def test_preserves_multi_rate_journal_entry_when_tax_pairing_is_ambiguous(self):
		transactions = [
			{
				"Umsatz (ohne Soll/Haben-Kz)": 238,
				"Soll/Haben-Kennzeichen": "S",
				"Konto": "10001",
				"Gegenkonto (ohne BU-Schlüssel)": "9999",
				"BU-Schlüssel": "",
				"Belegdatum": today(),
				"Belegfeld 1": "ACC-JV-2026-00008",
				"Buchungstext": "Sales Journal Entry",
				"Beleginfo - Art 1": "Journal Entry",
				"Beleginfo - Inhalt 1": "ACC-JV-2026-00008",
				"Beleginfo - Art 3": "Customer",
				"Beleginfo - Inhalt 3": "Test Customer",
			},
			{
				"Umsatz (ohne Soll/Haben-Kz)": 19,
				"Soll/Haben-Kennzeichen": "H",
				"Konto": "3806",
				"Gegenkonto (ohne BU-Schlüssel)": "9999",
				"BU-Schlüssel": "",
				"Belegdatum": today(),
				"Belegfeld 1": "ACC-JV-2026-00008",
				"Buchungstext": "Sales Journal Entry",
				"Beleginfo - Art 1": "Journal Entry",
				"Beleginfo - Inhalt 1": "ACC-JV-2026-00008",
			},
			{
				"Umsatz (ohne Soll/Haben-Kz)": 19,
				"Soll/Haben-Kennzeichen": "H",
				"Konto": "3801",
				"Gegenkonto (ohne BU-Schlüssel)": "9999",
				"BU-Schlüssel": "",
				"Belegdatum": today(),
				"Belegfeld 1": "ACC-JV-2026-00008",
				"Buchungstext": "Sales Journal Entry",
				"Beleginfo - Art 1": "Journal Entry",
				"Beleginfo - Inhalt 1": "ACC-JV-2026-00008",
			},
			{
				"Umsatz (ohne Soll/Haben-Kz)": 100,
				"Soll/Haben-Kennzeichen": "H",
				"Konto": "8400",
				"Gegenkonto (ohne BU-Schlüssel)": "9999",
				"BU-Schlüssel": "",
				"Belegdatum": today(),
				"Belegfeld 1": "ACC-JV-2026-00008",
				"Buchungstext": "Sales Journal Entry",
				"Beleginfo - Art 1": "Journal Entry",
				"Beleginfo - Inhalt 1": "ACC-JV-2026-00008",
			},
			{
				"Umsatz (ohne Soll/Haben-Kz)": 100,
				"Soll/Haben-Kennzeichen": "H",
				"Konto": "8300",
				"Gegenkonto (ohne BU-Schlüssel)": "9999",
				"BU-Schlüssel": "",
				"Belegdatum": today(),
				"Belegfeld 1": "ACC-JV-2026-00008",
				"Buchungstext": "Sales Journal Entry",
				"Beleginfo - Art 1": "Journal Entry",
				"Beleginfo - Inhalt 1": "ACC-JV-2026-00008",
			},
		]
		journal_entry = frappe._dict(
			{
				"name": "ACC-JV-2026-00008",
				"company": "_Test GmbH",
				"accounts": [
					frappe._dict(
						{
							"account": "Debtors - _TG",
							"party_type": "Customer",
							"party": "Test Customer",
							"debit_in_account_currency": 238,
							"credit_in_account_currency": 0,
						}
					),
					frappe._dict(
						{
							"account": "VAT 19 - _TG",
							"debit_in_account_currency": 0,
							"credit_in_account_currency": 19,
						}
					),
					frappe._dict(
						{
							"account": "VAT 7 - _TG",
							"debit_in_account_currency": 0,
							"credit_in_account_currency": 19,
						}
					),
					frappe._dict(
						{
							"account": "Sales Domestic - _TG",
							"debit_in_account_currency": 0,
							"credit_in_account_currency": 100,
							"custom_datev_account_no": "8400",
						}
					),
					frappe._dict(
						{
							"account": "Sales Export - _TG",
							"debit_in_account_currency": 0,
							"credit_in_account_currency": 100,
							"custom_datev_account_no": "8300",
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
				"gaertnerei_berger.gb_datev.report.datev.datev.is_journal_entry_tax_row",
				side_effect=lambda row: row.account in {"VAT 19 - _TG", "VAT 7 - _TG"},
			),
		):
			grouped = group_journal_entry_buchungsstapel(
				transactions, {"company": "_Test GmbH", "against_account": "9999"}
			)

		self.assertEqual(grouped, transactions)

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

	def test_maps_multi_item_sales_invoice_gegenkonto_per_line(self):
		transactions = [
			{
				"Konto": "4300",
				"Gegenkonto (ohne BU-Schlüssel)": "10111",
				"BU-Schlüssel": "14",
				"Umsatz (ohne Soll/Haben-Kz)": 100,
				"Belegfeld 1": "ACC-SINV-2026-00003",
				"Beleginfo - Art 1": "Sales Invoice",
			},
			{
				"Konto": "4185",
				"Gegenkonto (ohne BU-Schlüssel)": "10111",
				"BU-Schlüssel": "31",
				"Umsatz (ohne Soll/Haben-Kz)": 100,
				"Belegfeld 1": "ACC-SINV-2026-00003",
				"Beleginfo - Art 1": "Sales Invoice",
			},
		]
		sales_invoice = frappe.get_doc(
			{
				"doctype": "Sales Invoice",
				"name": "ACC-SINV-2026-00003",
				"custom_datev_account_no": "10111",
				"items": [
					{
						"custom_datev_account_no": "4300",
						"custom_bu_schlussel": "14",
						"net_amount": 100,
						"amount": 100,
					},
					{
						"custom_datev_account_no": "4185",
						"custom_bu_schlussel": "31",
						"net_amount": 100,
						"amount": 100,
					},
				],
			}
		)

		with (
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.get_buchungsstapel_mappings",
				return_value={
					"Sales Invoice": [
						frappe._dict(
							{
								"map_to_field": "items.amount",
								"map_to_column": "Umsatz (ohne Soll/Haben-Kz)",
							}
						),
						frappe._dict(
							{
								"map_to_field": "custom_datev_account_no",
								"map_to_column": "Konto",
							}
						),
						frappe._dict(
							{
								"map_to_field": "items.custom_datev_account_no",
								"map_to_column": "Gegenkonto (ohne BU-Schlüssel)",
							}
						),
						frappe._dict(
							{
								"map_to_field": "items.custom_bu_schlussel",
								"map_to_column": "BU-Schlüssel",
							}
						),
					]
				},
			),
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.get_account_maps",
				return_value=({}, {}),
			),
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.load_voucher_doc",
				return_value=sales_invoice,
			),
		):
			mapped = apply_buchungsstapel_mapping(transactions, {"company": "My Company"})

		self.assertEqual(
			[
				(
					row["Konto"],
					row["Gegenkonto (ohne BU-Schlüssel)"],
					row["BU-Schlüssel"],
				)
				for row in mapped
			],
			[
				("10111", "4300", "14"),
				("10111", "4185", "31"),
			],
		)

	def test_preserves_grouped_sales_invoice_umsatz_from_mapping_override(self):
		transactions = [
			{
				"Konto": "4300",
				"Gegenkonto (ohne BU-Schlüssel)": "10111",
				"BU-Schlüssel": "14",
				"Umsatz (ohne Soll/Haben-Kz)": 300,
				"Belegfeld 1": "ACC-SINV-2026-00004",
				"Beleginfo - Art 1": "Sales Invoice",
			},
			{
				"Konto": "4185",
				"Gegenkonto (ohne BU-Schlüssel)": "10111",
				"BU-Schlüssel": "31",
				"Umsatz (ohne Soll/Haben-Kz)": 300,
				"Belegfeld 1": "ACC-SINV-2026-00004",
				"Beleginfo - Art 1": "Sales Invoice",
			},
		]
		sales_invoice = frappe.get_doc(
			{
				"doctype": "Sales Invoice",
				"name": "ACC-SINV-2026-00004",
				"custom_datev_account_no": "10111",
				"items": [
					{
						"custom_datev_account_no": "4300",
						"custom_bu_schlussel": "14",
						"net_amount": 100,
						"amount": 100,
					},
					{
						"custom_datev_account_no": "4185",
						"custom_bu_schlussel": "31",
						"net_amount": 100,
						"amount": 100,
					},
					{
						"custom_datev_account_no": "4185",
						"custom_bu_schlussel": "31",
						"net_amount": 200,
						"amount": 200,
					},
					{
						"custom_datev_account_no": "4300",
						"custom_bu_schlussel": "14",
						"net_amount": 200,
						"amount": 200,
					},
				],
			}
		)

		with (
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.get_buchungsstapel_mappings",
				return_value={
					"Sales Invoice": [
						frappe._dict(
							{
								"map_to_field": "items.amount",
								"map_to_column": "Umsatz (ohne Soll/Haben-Kz)",
							}
						),
						frappe._dict(
							{
								"map_to_field": "custom_datev_account_no",
								"map_to_column": "Konto",
							}
						),
						frappe._dict(
							{
								"map_to_field": "items.custom_datev_account_no",
								"map_to_column": "Gegenkonto (ohne BU-Schlüssel)",
							}
						),
						frappe._dict(
							{
								"map_to_field": "items.custom_bu_schlussel",
								"map_to_column": "BU-Schlüssel",
							}
						),
					]
				},
			),
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.get_account_maps",
				return_value=({}, {}),
			),
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.load_voucher_doc",
				return_value=sales_invoice,
			),
		):
			mapped = apply_buchungsstapel_mapping(transactions, {"company": "My Company"})

		self.assertEqual(
			[
				(
					row["Konto"],
					row["Gegenkonto (ohne BU-Schlüssel)"],
					row["BU-Schlüssel"],
					float(row["Umsatz (ohne Soll/Haben-Kz)"]),
				)
				for row in mapped
			],
			[
				("10111", "4300", "14", 300.0),
				("10111", "4185", "31", 300.0),
			],
		)


class TestDatevPaymentEntryGrouping(TestCase):
	def test_groups_receive_payment_entry_into_single_line_with_blank_bu_schluessel(self):
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
			}
		)

		with (
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.load_voucher_doc",
				return_value=payment_entry,
			),
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.frappe.db.get_value",
				side_effect=["1800", "1001"],
			),
		):
			grouped = group_payment_entry_buchungsstapel(
				transactions, {"company": "_Test GmbH", "against_account": "9999"}
			)

		self.assertEqual(len(grouped), 1)
		self.assertEqual(grouped[0]["Konto"], "1800")
		self.assertEqual(grouped[0]["Gegenkonto (ohne BU-Schlüssel)"], "1001")
		self.assertEqual(grouped[0]["BU-Schlüssel"], "")
		self.assertEqual(grouped[0]["Soll/Haben-Kennzeichen"], "S")

	def test_groups_pay_payment_entry_into_single_line_with_blank_bu_schluessel(self):
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
			}
		)

		with (
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.load_voucher_doc",
				return_value=payment_entry,
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
		self.assertEqual(grouped[0]["BU-Schlüssel"], "")
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


class TestDatevExportMode(TestCase):
	def test_consultant_mode_gross_amount_basis(self):
		item = {
			"base_net_amount": 100,
			"item_tax_rate": '{"3806 - Umsatzsteuer 19 % - MC": 19.0}',
		}
		net_filters = {"invoice_amount_basis": "net"}
		gross_filters = {"invoice_amount_basis": "gross"}

		self.assertEqual(float(get_invoice_item_amount(item, net_filters)), 100.0)
		self.assertEqual(float(get_invoice_item_amount(item, gross_filters)), 119.0)

	def test_consultant_mode_groups_si_gross_amounts(self):
		transactions = [
			{
				"Konto": "4300",
				"Gegenkonto (ohne BU-Schlüssel)": "10111",
				"BU-Schlüssel": "14",
				"Umsatz (ohne Soll/Haben-Kz)": 119,
				"Belegfeld 1": "ACC-SINV-2026-00004",
				"Beleginfo - Art 1": "Sales Invoice",
				"Beleginfo - Art 3": "Customer",
				"Beleginfo - Inhalt 3": "111 Customer",
			},
		]
		sales_invoice = frappe.get_doc(
			{
				"doctype": "Sales Invoice",
				"name": "ACC-SINV-2026-00004",
				"company": "_Test GmbH",
				"customer": "111 Customer",
				"debit_to": "10111 - Customer - MC",
				"custom_datev_account_no": "10111",
				"items": [
					{
						"custom_datev_account_no": "4300",
						"custom_bu_schlussel": "14",
						"item_tax_template": "7 % - MC",
						"item_tax_rate": '{"3801 - Umsatzsteuer 7 % - MC": 7.0}',
						"base_net_amount": 100,
						"net_amount": 100,
					},
					{
						"custom_datev_account_no": "4300",
						"custom_bu_schlussel": "14",
						"item_tax_template": "7 % - MC",
						"item_tax_rate": '{"3801 - Umsatzsteuer 7 % - MC": 7.0}',
						"base_net_amount": 200,
						"net_amount": 200,
					},
				],
			}
		)

		with (
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.load_voucher_doc",
				return_value=sales_invoice,
			),
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.get_invoice_gegenkonto",
				return_value="10111",
			),
		):
			grouped = group_sales_invoice_buchungsstapel(
				transactions,
				{
					"company": "_Test GmbH",
					"against_account": "9090",
					"invoice_amount_basis": "gross",
				},
			)

		self.assertEqual(len(grouped), 1)
		self.assertEqual(float(grouped[0]["Umsatz (ohne Soll/Haben-Kz)"]), 321.0)

	def test_run_query_excludes_cancelled_gl_entries(self):
		captured = {}

		def fake_sql(query, filters, as_dict=1):
			captured["query"] = query
			return []

		with patch(
			"gaertnerei_berger.gb_datev.report.datev.datev.frappe.db.sql",
			side_effect=fake_sql,
		):
			run_query(
				{
					"company": "_Test GmbH",
					"from_date": "2026-01-01",
					"to_date": "2026-01-31",
					"opening_account": "9000",
					"against_account": "9090",
				},
				"",
				"",
				"",
			)

		self.assertIn("IFNULL(gl.is_cancelled, 0) = 0", captured["query"])

	def test_voucher_params_require_submitted_docstatus(self):
		_, _, pe_filters = get_payment_entry_params({})
		_, _, si_filters = get_sales_invoice_params({})
		_, _, pi_filters = get_purchase_invoice_params({})

		self.assertIn("pe.docstatus = 1", pe_filters)
		self.assertIn("si.docstatus = 1", si_filters)
		self.assertIn("pi.docstatus = 1", pi_filters)

	def test_journal_entry_export_matches_sales_invoice_konto_orientation(self):
		journal_entry = frappe._dict(
			{
				"name": "ACC-JV-2026-PARITY",
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
							"custom_datev_account_no": "4300",
							"custom_bu_schlussel": "14",
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
		sales_invoice = frappe.get_doc(
			{
				"doctype": "Sales Invoice",
				"name": "ACC-SINV-2026-PARITY",
				"company": "_Test GmbH",
				"customer": "Test Customer",
				"custom_datev_account_no": "10111",
				"items": [
					{
						"custom_datev_account_no": "4300",
						"custom_bu_schlussel": "14",
						"net_amount": 100,
						"amount": 100,
					},
				],
			}
		)
		je_transactions = [
			{
				"Belegfeld 1": "ACC-JV-2026-PARITY",
				"Beleginfo - Art 1": "Journal Entry",
				"Beleginfo - Art 3": "Customer",
				"Beleginfo - Inhalt 3": "Test Customer",
				"Belegdatum": today(),
			}
		]
		si_transactions = [
			{
				"Konto": "4300",
				"Gegenkonto (ohne BU-Schlüssel)": "10111",
				"BU-Schlüssel": "14",
				"Umsatz (ohne Soll/Haben-Kz)": 100,
				"Belegfeld 1": "ACC-SINV-2026-PARITY",
				"Beleginfo - Art 1": "Sales Invoice",
				"Beleginfo - Art 3": "Customer",
				"Beleginfo - Inhalt 3": "Test Customer",
			}
		]

		with (
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.load_voucher_doc",
				side_effect=lambda voucher_type, voucher_no: journal_entry
				if voucher_type == "Journal Entry"
				else sales_invoice,
			),
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.get_journal_entry_account_type",
				side_effect=lambda account: {"Debtors - _TG": "Receivable"}.get(account, ""),
			),
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.is_journal_entry_tax_row",
				side_effect=lambda row: row.account == "VAT 19 - _TG",
			),
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.get_party_account_number",
				return_value="10111",
			),
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.get_invoice_gegenkonto",
				return_value="10111",
			),
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.get_buchungsstapel_mappings",
				return_value={
					"Sales Invoice": {
						"Both": [
							frappe._dict(
								{
									"map_to_field": "due_date",
									"map_to_column": "Fälligkeit",
								}
							),
						]
					}
				},
			),
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.get_account_maps",
				return_value=({}, {}),
			),
		):
			je_grouped = group_journal_entry_buchungsstapel(
				je_transactions, {"company": "_Test GmbH", "against_account": "9999"}
			)
			si_grouped = apply_buchungsstapel_mapping(
				group_sales_invoice_buchungsstapel(
					si_transactions,
					{"company": "_Test GmbH", "against_account": "9999", "invoice_amount_basis": "net"},
				),
				{"company": "_Test GmbH"},
			)

		expected = ("4300", "10111", "14", "H")
		self.assertEqual(
			(
				je_grouped[0]["Konto"],
				je_grouped[0]["Gegenkonto (ohne BU-Schlüssel)"],
				je_grouped[0]["BU-Schlüssel"],
				je_grouped[0]["Soll/Haben-Kennzeichen"],
			),
			expected,
		)
		self.assertEqual(
			(
				si_grouped[0]["Konto"],
				si_grouped[0]["Gegenkonto (ohne BU-Schlüssel)"],
				si_grouped[0]["BU-Schlüssel"],
				si_grouped[0]["Soll/Haben-Kennzeichen"],
			),
			expected,
		)

	def test_selects_receivable_mapping_over_both_for_payment_entry(self):
		from gaertnerei_berger.gb_datev.report.datev.datev import (
			get_voucher_party_account_type,
			select_buchungsstapel_field_mappings,
		)

		receivable_row = frappe._dict(
			{"map_to_field": "custom_datev_account_no", "map_to_column": "Konto"}
		)
		both_row = frappe._dict(
			{"map_to_field": "paid_amount", "map_to_column": "Umsatz (ohne Soll/Haben-Kz)"}
		)
		mappings = {
			"Payment Entry": {
				"Receivable": [receivable_row],
				"Both": [both_row],
			}
		}

		pe = frappe._dict({"payment_type": "Receive"})
		self.assertEqual(get_voucher_party_account_type("Payment Entry", pe), "Receivable")
		selected = select_buchungsstapel_field_mappings(mappings, "Payment Entry", "Receivable")
		self.assertEqual(selected, [receivable_row])

		pe_pay = frappe._dict({"payment_type": "Pay"})
		self.assertEqual(get_voucher_party_account_type("Payment Entry", pe_pay), "Payable")
		self.assertEqual(
			select_buchungsstapel_field_mappings(mappings, "Payment Entry", "Payable"),
			[both_row],
		)

	def test_journal_entry_direction_maps_to_party_account_type(self):
		from gaertnerei_berger.gb_datev.report.datev.datev import get_voucher_party_account_type

		with patch(
			"gaertnerei_berger.gb_datev.journal_entry.get_journal_entry_datev_direction",
			return_value="purchase",
		):
			self.assertEqual(
				get_voucher_party_account_type("Journal Entry", frappe._dict()),
				"Payable",
			)

		with patch(
			"gaertnerei_berger.gb_datev.journal_entry.get_journal_entry_datev_direction",
			return_value="sales",
		):
			self.assertEqual(
				get_voucher_party_account_type("Journal Entry", frappe._dict()),
				"Receivable",
			)


class TestDatevFrozenExportContract(TestCase):
	"""Six golden rows locking the v1 Consultant Booking orientation contract."""

	def _assert_orientation(self, row, konto, gegenkonto, bu, sh):
		self.assertEqual(row["Konto"], konto)
		self.assertEqual(row["Gegenkonto (ohne BU-Schlüssel)"], gegenkonto)
		self.assertEqual(row["BU-Schlüssel"], bu)
		self.assertEqual(row["Soll/Haben-Kennzeichen"], sh)

	def test_golden_sales_invoice_erloes_to_debitor(self):
		transactions = [
			{
				"Konto": "4300",
				"Gegenkonto (ohne BU-Schlüssel)": "9999",
				"BU-Schlüssel": "",
				"Umsatz (ohne Soll/Haben-Kz)": 100,
				"Soll/Haben-Kennzeichen": "H",
				"Belegdatum": today(),
				"Belegfeld 1": "ACC-SINV-GOLDEN",
				"Beleginfo - Art 1": "Sales Invoice",
				"Beleginfo - Art 3": "Customer",
				"Beleginfo - Inhalt 3": "Test Customer",
			}
		]
		sales_invoice = frappe._dict(
			{
				"name": "ACC-SINV-GOLDEN",
				"company": "_Test GmbH",
				"customer": "Test Customer",
				"items": [
					frappe._dict(
						{
							"custom_datev_account_no": "4300",
							"custom_bu_schlussel": "14",
							"net_amount": 100,
							"amount": 100,
						}
					)
				],
			}
		)

		with (
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.load_voucher_doc",
				return_value=sales_invoice,
			),
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.get_invoice_gegenkonto",
				return_value="10111",
			),
		):
			grouped = group_sales_invoice_buchungsstapel(
				transactions,
				{"company": "_Test GmbH", "against_account": "9999", "invoice_amount_basis": "net"},
			)

		self.assertEqual(len(grouped), 1)
		self._assert_orientation(grouped[0], "4300", "10111", "14", "H")

	def test_golden_purchase_invoice_aufwand_to_kreditor(self):
		transactions = [
			{
				"Konto": "5300",
				"Gegenkonto (ohne BU-Schlüssel)": "9999",
				"BU-Schlüssel": "",
				"Umsatz (ohne Soll/Haben-Kz)": 100,
				"Soll/Haben-Kennzeichen": "S",
				"Belegdatum": today(),
				"Belegfeld 1": "ACC-PINV-GOLDEN",
				"Beleginfo - Art 1": "Purchase Invoice",
				"Beleginfo - Art 3": "Supplier",
				"Beleginfo - Inhalt 3": "Test Supplier",
			}
		]
		purchase_invoice = frappe._dict(
			{
				"name": "ACC-PINV-GOLDEN",
				"company": "_Test GmbH",
				"supplier": "Test Supplier",
				"items": [
					frappe._dict(
						{
							"custom_datev_account_no": "5300",
							"custom_bu_schlussel": "8",
							"net_amount": 100,
							"amount": 100,
						}
					)
				],
			}
		)

		with (
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.load_voucher_doc",
				return_value=purchase_invoice,
			),
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.get_invoice_gegenkonto",
				return_value="70001",
			),
		):
			grouped = group_sales_invoice_buchungsstapel(
				transactions,
				{"company": "_Test GmbH", "against_account": "9999", "invoice_amount_basis": "net"},
			)

		self.assertEqual(len(grouped), 1)
		self._assert_orientation(grouped[0], "5300", "70001", "8", "S")

	def test_golden_payment_entry_receive_bank_to_personenkonto(self):
		transactions = [
			{
				"Umsatz (ohne Soll/Haben-Kz)": 119,
				"Konto": "9999",
				"Gegenkonto (ohne BU-Schlüssel)": "9999",
				"BU-Schlüssel": "",
				"Belegdatum": today(),
				"Belegfeld 1": "ACC-PAY-GOLDEN-R",
				"Beleginfo - Art 1": "Payment Entry",
				"Beleginfo - Art 3": "Customer",
				"Beleginfo - Inhalt 3": "Test Customer",
			},
			{
				"Umsatz (ohne Soll/Haben-Kz)": 119,
				"Konto": "9999",
				"Gegenkonto (ohne BU-Schlüssel)": "9999",
				"BU-Schlüssel": "",
				"Belegdatum": today(),
				"Belegfeld 1": "ACC-PAY-GOLDEN-R",
				"Beleginfo - Art 1": "Payment Entry",
			},
		]
		payment_entry = frappe._dict(
			{
				"name": "ACC-PAY-GOLDEN-R",
				"payment_type": "Receive",
				"party_type": "Customer",
				"party": "Test Customer",
				"company": "_Test GmbH",
				"custom_datev_account_no": "1820",
				"custom_datev_against_account_no": "10318",
				"custom_bu_schlussel": "80",
			}
		)

		with (
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.load_voucher_doc",
				return_value=payment_entry,
			),
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.get_buchungsstapel_mappings",
				return_value={
					"Payment Entry": {
						"Receivable": [
							frappe._dict(
								{"map_to_field": "custom_datev_account_no", "map_to_column": "Konto"}
							),
							frappe._dict(
								{
									"map_to_field": "custom_datev_against_account_no",
									"map_to_column": "Gegenkonto (ohne BU-Schlüssel)",
								}
							),
							frappe._dict(
								{"map_to_field": "custom_bu_schlussel", "map_to_column": "BU-Schlüssel"}
							),
						]
					}
				},
			),
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.get_account_maps",
				return_value=({}, {}),
			),
		):
			grouped = group_payment_entry_buchungsstapel(
				transactions, {"company": "_Test GmbH", "against_account": "9999"}
			)
			mapped = apply_buchungsstapel_mapping(grouped, {"company": "_Test GmbH"})

		self.assertEqual(len(mapped), 1)
		self._assert_orientation(mapped[0], "1820", "10318", "80", "S")

	def test_golden_payment_entry_pay_personenkonto_to_bank(self):
		transactions = [
			{
				"Umsatz (ohne Soll/Haben-Kz)": 119,
				"Konto": "9999",
				"Gegenkonto (ohne BU-Schlüssel)": "9999",
				"BU-Schlüssel": "",
				"Belegdatum": today(),
				"Belegfeld 1": "ACC-PAY-GOLDEN-P",
				"Beleginfo - Art 1": "Payment Entry",
				"Beleginfo - Art 3": "Supplier",
				"Beleginfo - Inhalt 3": "Test Supplier",
			},
			{
				"Umsatz (ohne Soll/Haben-Kz)": 119,
				"Konto": "9999",
				"Gegenkonto (ohne BU-Schlüssel)": "9999",
				"BU-Schlüssel": "",
				"Belegdatum": today(),
				"Belegfeld 1": "ACC-PAY-GOLDEN-P",
				"Beleginfo - Art 1": "Payment Entry",
			},
		]
		payment_entry = frappe._dict(
			{
				"name": "ACC-PAY-GOLDEN-P",
				"payment_type": "Pay",
				"party_type": "Supplier",
				"party": "Test Supplier",
				"company": "_Test GmbH",
				"custom_datev_account_no": "70217",
				"custom_datev_against_account_no": "1800",
				"custom_bu_schlussel": "90",
			}
		)

		with (
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.load_voucher_doc",
				return_value=payment_entry,
			),
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.get_buchungsstapel_mappings",
				return_value={
					"Payment Entry": {
						"Payable": [
							frappe._dict(
								{"map_to_field": "custom_datev_account_no", "map_to_column": "Konto"}
							),
							frappe._dict(
								{
									"map_to_field": "custom_datev_against_account_no",
									"map_to_column": "Gegenkonto (ohne BU-Schlüssel)",
								}
							),
							frappe._dict(
								{"map_to_field": "custom_bu_schlussel", "map_to_column": "BU-Schlüssel"}
							),
						]
					}
				},
			),
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.get_account_maps",
				return_value=({}, {}),
			),
		):
			grouped = group_payment_entry_buchungsstapel(
				transactions, {"company": "_Test GmbH", "against_account": "9999"}
			)
			mapped = apply_buchungsstapel_mapping(grouped, {"company": "_Test GmbH"})

		self.assertEqual(len(mapped), 1)
		self._assert_orientation(mapped[0], "70217", "1800", "90", "S")

	def test_golden_journal_entry_sales_erloes_to_debitor(self):
		transactions = [
			{
				"Umsatz (ohne Soll/Haben-Kz)": 119,
				"Konto": "10111",
				"Gegenkonto (ohne BU-Schlüssel)": "9999",
				"BU-Schlüssel": "",
				"Belegdatum": today(),
				"Belegfeld 1": "ACC-JV-GOLDEN-S",
				"Beleginfo - Art 1": "Journal Entry",
				"Beleginfo - Art 3": "Customer",
				"Beleginfo - Inhalt 3": "Test Customer",
			}
		]
		journal_entry = frappe._dict(
			{
				"name": "ACC-JV-GOLDEN-S",
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
							"custom_datev_account_no": "4300",
							"custom_bu_schlussel": "14",
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
				"gaertnerei_berger.gb_datev.report.datev.datev.is_journal_entry_tax_row",
				side_effect=lambda row: row.account == "VAT 19 - _TG",
			),
			patch(
				"gaertnerei_berger.gb_datev.report.datev.datev.get_party_account_number",
				return_value="10111",
			),
		):
			grouped = group_journal_entry_buchungsstapel(
				transactions, {"company": "_Test GmbH", "against_account": "9999"}
			)

		self.assertEqual(len(grouped), 1)
		self._assert_orientation(grouped[0], "4300", "10111", "14", "H")

	def test_golden_journal_entry_purchase_aufwand_to_kreditor(self):
		transactions = [
			{
				"Umsatz (ohne Soll/Haben-Kz)": 119,
				"Konto": "70001",
				"Gegenkonto (ohne BU-Schlüssel)": "9999",
				"BU-Schlüssel": "",
				"Belegdatum": today(),
				"Belegfeld 1": "ACC-JV-GOLDEN-P",
				"Beleginfo - Art 1": "Journal Entry",
				"Beleginfo - Art 3": "Supplier",
				"Beleginfo - Inhalt 3": "Test Supplier",
			}
		]
		journal_entry = frappe._dict(
			{
				"name": "ACC-JV-GOLDEN-P",
				"company": "_Test GmbH",
				"custom_datev_account_no": "70001",
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
							"custom_datev_account_no": "5300",
							"custom_bu_schlussel": "8",
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
		self._assert_orientation(grouped[0], "5300", "70001", "8", "S")

