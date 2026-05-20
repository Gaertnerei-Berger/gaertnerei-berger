import zipfile
from io import BytesIO
from unittest import TestCase
from unittest.mock import patch

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
		map_mock.assert_called_once_with(grouped_transactions, get_transactions_mock.call_args.args[0])

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

	def test_preserves_grouped_sales_invoice_konto_from_parent_mapping_override(self):
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
		self.assertEqual([row["Konto"] for row in sales_rows], ["8400", "8300"])

		payment_rows = [row for row in mapped if row["Beleginfo - Art 1"] == "Payment Entry"]
		self.assertEqual([row["Konto"] for row in payment_rows], ["mapped-payment"])
