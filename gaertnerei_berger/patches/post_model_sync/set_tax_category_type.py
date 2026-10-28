import frappe
from frappe.utils.fixtures import sync_fixtures

TAX_CATEGORY_TYPES = {
	"Inland Ust": "Sales",
	"Inland Vst": "Purchase",
}


def execute():
	"""Set Sales / Purchase on the seeded Tax Categories (GitLab #110). Values already set stay."""
	# Fixtures sync after post_model_sync patches, so the field may not exist yet.
	# Only sync when it is missing: the sync adds a column, which commits.
	if not frappe.db.has_column("Tax Category", "custom_tax_category_type"):
		sync_fixtures("gaertnerei_berger")

	for title, tax_category_type in TAX_CATEGORY_TYPES.items():
		if frappe.db.exists("Tax Category", title) and not frappe.db.get_value(
			"Tax Category", title, "custom_tax_category_type"
		):
			frappe.db.set_value("Tax Category", title, "custom_tax_category_type", tax_category_type)
