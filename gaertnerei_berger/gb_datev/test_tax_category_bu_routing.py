# Copyright (c) 2026, Gaertnerei Berger and contributors
# For license information, please see license.txt

from unittest.mock import patch

import frappe
from erpnext.buying.doctype.supplier.test_supplier import create_supplier
from erpnext.stock.get_item_details import get_item_tax_template
from frappe.tests.utils import FrappeTestCase
from frappe.utils import today

from gaertnerei_berger.gb_datev.report.datev.datev import (
	build_item_tax_template_bu_schluessel_by_account,
	get_grouped_invoice_rows,
	get_journal_entry_bu_schluessel,
)
from gaertnerei_berger.gb_datev.report.datev.test_datev import (
	make_company,
	make_customer_with_account,
	make_datev_settings,
	make_item,
	setup_fiscal_year,
)


def ensure_tax_category(title):
	if not frappe.db.exists("Tax Category", title):
		frappe.get_doc({"doctype": "Tax Category", "title": title}).insert()
	return title


def make_test_tax_account(company, account_name, account_number, account_type="Tax"):
	parent_account = frappe.db.get_value(
		"Account",
		{"company": company.name, "account_type": account_type, "is_group": 1},
		"name",
	)
	if not parent_account:
		parent_account = frappe.db.get_value(
			"Account",
			{"company": company.name, "is_group": 1, "root_type": "Liability"},
			"name",
		)

	existing = frappe.db.get_value(
		"Account",
		{"company": company.name, "account_number": account_number},
		"name",
	)
	if existing:
		return existing

	acc = frappe.get_doc(
		{
			"doctype": "Account",
			"parent_account": parent_account,
			"account_name": account_name,
			"company": company.name,
			"account_type": account_type,
			"account_number": account_number,
		}
	)
	acc.insert()
	return acc.name


def make_item_tax_template(title, company, tax_account, tax_rate, bu_schluessel):
	existing_name = frappe.db.get_value(
		"Item Tax Template",
		{"title": title, "company": company.name},
		"name",
	)
	if existing_name:
		doc = frappe.get_doc("Item Tax Template", existing_name)
	else:
		doc = frappe.new_doc("Item Tax Template")
		doc.title = title
		doc.company = company.name

	doc.custom_bu_schlussel = bu_schluessel
	doc.set("taxes", [])
	doc.append("taxes", {"tax_type": tax_account, "tax_rate": tax_rate})
	doc.save()
	return doc


def make_supplier_with_account(supplier_name, company):
	return create_supplier(supplier_name=supplier_name)


def make_buy_sell_item(item_code, company, ust_template, vst_template):
	item = make_item(item_code, company)
	item.is_purchase_item = 1
	item.is_sales_item = 1
	item.set("taxes", [])
	item.append(
		"taxes",
		{
			"item_tax_template": ust_template.name,
			"tax_category": ensure_tax_category("Inland Ust"),
		},
	)
	item.append(
		"taxes",
		{
			"item_tax_template": vst_template.name,
			"tax_category": ensure_tax_category("Inland Vst"),
		},
	)
	item.save()
	return item


class TestTaxCategoryBuRouting(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.company = make_company("_Test GmbH", "_TG")
		setup_fiscal_year()
		make_datev_settings(cls.company)

		ensure_tax_category("Inland Ust")
		ensure_tax_category("Inland Vst")

		cls.ust_account = make_test_tax_account(cls.company, "_Test DATEV USt", "993806")
		cls.vst_account = make_test_tax_account(cls.company, "_Test DATEV VSt", "991406")

		cls.ust_template = make_item_tax_template(
			"DE 19 USt",
			cls.company,
			cls.ust_account,
			19,
			"9",
		)
		cls.vst_template = make_item_tax_template(
			"DE 19 VSt",
			cls.company,
			cls.vst_account,
			19,
			"8",
		)

		cls.item = make_buy_sell_item(
			"_Test Buy Sell Item",
			cls.company,
			cls.ust_template,
			cls.vst_template,
		)

		cls.customer = make_customer_with_account("_Test Kunde GmbH", cls.company)
		cls.customer.tax_category = "Inland Ust"
		cls.customer.save()

		cls.supplier = make_supplier_with_account("_Test Lieferant GmbH", cls.company)
		cls.supplier.tax_category = "Inland Vst"
		cls.supplier.save()

	def test_item_tax_template_routes_by_tax_category_for_sales(self):
		template = get_item_tax_template(
			{
				"item_code": self.item.name,
				"company": self.company.name,
				"tax_category": "Inland Ust",
				"transaction_date": today(),
			}
		)
		self.assertEqual(template, self.ust_template.name)

	def test_item_tax_template_routes_by_tax_category_for_purchase(self):
		template = get_item_tax_template(
			{
				"item_code": self.item.name,
				"company": self.company.name,
				"tax_category": "Inland Vst",
				"transaction_date": today(),
			}
		)
		self.assertEqual(template, self.vst_template.name)

	def test_each_direction_template_carries_its_own_bu(self):
		self.assertEqual(
			frappe.db.get_value("Item Tax Template", self.ust_template.name, "custom_bu_schlussel"),
			"9",
		)
		self.assertEqual(
			frappe.db.get_value("Item Tax Template", self.vst_template.name, "custom_bu_schlussel"),
			"8",
		)

	def test_datev_export_uses_line_bu_from_selected_template(self):
		sales_invoice = frappe._dict(
			{
				"name": "RG-TAX-CAT-001",
				"company": self.company.name,
				"customer": self.customer.name,
				"debit_to": self.customer.accounts[0].account,
				"items": [
					frappe._dict(
						{
							"custom_datev_account_no": "8400",
							"custom_bu_schlussel": "9",
							"item_tax_template": self.ust_template.name,
							"base_net_amount": 100,
						}
					)
				],
			}
		)
		purchase_invoice = frappe._dict(
			{
				"name": "ER-TAX-CAT-001",
				"company": self.company.name,
				"supplier": self.supplier.name,
				"credit_to": (self.supplier.accounts[0].account if self.supplier.accounts else ""),
				"items": [
					frappe._dict(
						{
							"custom_datev_account_no": "3400",
							"custom_bu_schlussel": "8",
							"item_tax_template": self.vst_template.name,
							"base_net_amount": 100,
						}
					)
				],
			}
		)

		base_row = {
			"Belegdatum": today(),
			"Belegfeld 1": "RG-TAX-CAT-001",
			"Buchungstext": "Test",
			"Beleginfo - Art 1": "Sales Invoice",
			"Beleginfo - Inhalt 1": "RG-TAX-CAT-001",
			"Beleginfo - Art 3": "Customer",
			"Beleginfo - Inhalt 3": self.customer.name,
			"Gegenkonto (ohne BU-Schlüssel)": "10001",
		}

		with patch(
			"gaertnerei_berger.gb_datev.report.datev.datev.load_voucher_doc",
			return_value=sales_invoice,
		):
			sales_rows = get_grouped_invoice_rows(
				"Sales Invoice",
				sales_invoice.name,
				[base_row],
				{"company": self.company.name, "against_account": "9999"},
			)

		self.assertEqual(len(sales_rows), 1)
		self.assertEqual(sales_rows[0]["BU-Schlüssel"], "9")
		self.assertEqual(sales_rows[0]["Konto"], "8400")

		purchase_base_row = dict(base_row)
		purchase_base_row.update(
			{
				"Belegfeld 1": "ER-TAX-CAT-001",
				"Beleginfo - Art 1": "Purchase Invoice",
				"Beleginfo - Inhalt 1": "ER-TAX-CAT-001",
				"Beleginfo - Art 3": "Supplier",
				"Beleginfo - Inhalt 3": self.supplier.name,
			}
		)

		with patch(
			"gaertnerei_berger.gb_datev.report.datev.datev.load_voucher_doc",
			return_value=purchase_invoice,
		):
			purchase_rows = get_grouped_invoice_rows(
				"Purchase Invoice",
				purchase_invoice.name,
				[purchase_base_row],
				{"company": self.company.name, "against_account": "9999"},
			)

		self.assertEqual(len(purchase_rows), 1)
		self.assertEqual(purchase_rows[0]["BU-Schlüssel"], "8")
		self.assertEqual(purchase_rows[0]["Konto"], "3400")

	def test_journal_entry_bu_resolves_from_unique_tax_account_mapping(self):
		mapping = build_item_tax_template_bu_schluessel_by_account()
		self.assertEqual(mapping.get(self.ust_account), {"9"})
		self.assertEqual(mapping.get(self.vst_account), {"8"})

		bu = get_journal_entry_bu_schluessel(frappe._dict({"account": self.ust_account}))
		self.assertEqual(bu, "9")

		bu = get_journal_entry_bu_schluessel(frappe._dict({"account": self.vst_account}))
		self.assertEqual(bu, "8")

	def test_journal_entry_bu_is_blank_when_account_maps_to_multiple_bus(self):
		conflict_account = make_test_tax_account(
			self.company, "_Test DATEV USt Conflict", "993807"
		)
		make_item_tax_template(
			"DE 19 USt Conflict A",
			self.company,
			conflict_account,
			19,
			"9",
		)
		make_item_tax_template(
			"DE 19 USt Conflict B",
			self.company,
			conflict_account,
			19,
			"99",
		)

		mapping = build_item_tax_template_bu_schluessel_by_account()
		self.assertEqual(mapping[conflict_account], {"9", "99"})

		bu = get_journal_entry_bu_schluessel(frappe._dict({"account": conflict_account}))
		self.assertEqual(bu, "")
