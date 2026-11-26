import frappe

from gaertnerei_berger.patches.post_model_sync.seed_datev_mapping_records import BUCHUNGSSTAPEL_REPORT

INVOICE_VOUCHER_TYPES = ("Sales Invoice", "Purchase Invoice")

# Grouping owns these on Sales/Purchase Invoice rows; the export ignores them
GROUPING_OWNED_COLUMNS = (
	"Konto",
	"Gegenkonto (ohne BU-Schlüssel)",
	"BU-Schlüssel",
	"Umsatz (ohne Soll/Haben-Kz)",
)


def execute():
	"""
	Drop account, BU and Umsatz rows from Sales/Purchase Invoice DATEV Mappings (GitLab #97).

	They put the Personenkonto on another column than the S/H flag expected,
	so DATEV read invoices as Gutschriften. Metadata rows (due_date, bill_no,
	bill_date) stay.
	"""
	parents = frappe.get_all(
		"DATEV Mapping",
		filters={"voucher_type": ["in", INVOICE_VOUCHER_TYPES]},
		pluck="name",
	)
	if not parents:
		return

	frappe.db.delete(
		"DATEV Mapping Field",
		{
			"parenttype": "DATEV Mapping",
			"parent": ["in", parents],
			"report_type": BUCHUNGSSTAPEL_REPORT,
			"map_to_column": ["in", GROUPING_OWNED_COLUMNS],
		},
	)
