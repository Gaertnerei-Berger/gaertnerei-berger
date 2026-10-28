# Copyright (c) 2026, Gaertnerei Berger and contributors
# For license information, please see license.txt

"""Tax Category Type (Sales / Purchase) and the picker filter (GitLab #110)."""

import frappe
from frappe.tests.utils import FrappeTestCase

from gaertnerei_berger.patches.post_model_sync import set_tax_category_type

SALES = "_Test TC Type Sales"
PURCHASE = "_Test TC Type Purchase"
BOTH = "_Test TC Type Both"


def make_tax_category(title, tax_category_type):
	if frappe.db.exists("Tax Category", title):
		frappe.delete_doc("Tax Category", title)
	frappe.get_doc(
		{"doctype": "Tax Category", "title": title, "custom_tax_category_type": tax_category_type}
	).insert()


def picker_titles(side):
	"""Same filter as public/js/tax_category_filter.js."""
	other_side = "Purchase" if side == "Sales" else "Sales"
	return set(
		frappe.get_all(
			"Tax Category",
			filters={"custom_tax_category_type": ["!=", other_side]},
			pluck="name",
		)
	)


class TestTaxCategoryType(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		set_tax_category_type.execute()

	def setUp(self):
		make_tax_category(SALES, "Sales")
		make_tax_category(PURCHASE, "Purchase")
		make_tax_category(BOTH, "")
		# A category created before the field existed has NULL, not "".
		frappe.db.sql("update `tabTax Category` set custom_tax_category_type = null where name = %s", BOTH)

	def test_field_options(self):
		field = frappe.get_meta("Tax Category").get_field("custom_tax_category_type")
		self.assertEqual(field.fieldtype, "Select")
		self.assertEqual(field.options.split("\n"), ["", "Sales", "Purchase"])
		self.assertFalse(field.reqd)

	def test_sales_picker_hides_purchase(self):
		titles = picker_titles("Sales")
		self.assertIn(SALES, titles)
		self.assertIn(BOTH, titles)
		self.assertNotIn(PURCHASE, titles)

	def test_purchase_picker_hides_sales(self):
		titles = picker_titles("Purchase")
		self.assertIn(PURCHASE, titles)
		self.assertIn(BOTH, titles)
		self.assertNotIn(SALES, titles)

	def test_patch_sets_seeded_categories(self):
		for title in set_tax_category_type.TAX_CATEGORY_TYPES:
			if not frappe.db.exists("Tax Category", title):
				frappe.get_doc({"doctype": "Tax Category", "title": title}).insert()
			frappe.db.set_value("Tax Category", title, "custom_tax_category_type", None)

		set_tax_category_type.execute()

		self.assertEqual(
			frappe.db.get_value("Tax Category", "Inland Ust", "custom_tax_category_type"), "Sales"
		)
		self.assertEqual(
			frappe.db.get_value("Tax Category", "Inland Vst", "custom_tax_category_type"), "Purchase"
		)

	def test_patch_keeps_value_already_set(self):
		if not frappe.db.exists("Tax Category", "Inland Ust"):
			frappe.get_doc({"doctype": "Tax Category", "title": "Inland Ust"}).insert()
		frappe.db.set_value("Tax Category", "Inland Ust", "custom_tax_category_type", "Purchase")

		set_tax_category_type.execute()

		self.assertEqual(
			frappe.db.get_value("Tax Category", "Inland Ust", "custom_tax_category_type"), "Purchase"
		)
