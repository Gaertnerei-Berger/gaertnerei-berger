import frappe

TAX_CATEGORIES = (
	"Inland Ust",
	"Inland Vst",
)


def execute():
	for title in TAX_CATEGORIES:
		if frappe.db.exists("Tax Category", title):
			continue

		frappe.get_doc({"doctype": "Tax Category", "title": title}).insert(ignore_permissions=True)
