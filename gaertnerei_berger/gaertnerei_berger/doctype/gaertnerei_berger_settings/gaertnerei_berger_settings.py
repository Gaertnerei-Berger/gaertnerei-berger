# Copyright (c) 2026, Gaertnerei Berger and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, format_datetime, now_datetime
from frappe.utils.synchronization import filelock

SETTINGS_DOCTYPE = "Gaertnerei Berger Settings"

# (label, target table, target field, source table, link field on target, source field)
SALES_INVOICE_DATEV_BACKFILLS = (
	(
		"Sales Invoice: Account No",
		"Sales Invoice",
		"custom_datev_account_no",
		"Account",
		"debit_to",
		"account_number",
	),
	(
		"Sales Invoice Item: Account No",
		"Sales Invoice Item",
		"custom_datev_account_no",
		"Account",
		"income_account",
		"account_number",
	),
	(
		"Sales Invoice Item: BU-Schlüssel",
		"Sales Invoice Item",
		"custom_bu_schlussel",
		"Item Tax Template",
		"item_tax_template",
		"custom_bu_schlussel",
	),
)


class GaertnereiBergerSettings(Document):
	pass


@frappe.whitelist()
def run_sales_invoice_datev_backfill():
	"""Fill empty DATEV fields on all Sales Invoices, once per site (GitLab #96).

	Only System Managers (write permission on the settings) may run it. Returns
	`{label: rows_filled}` for each backfill in `SALES_INVOICE_DATEV_BACKFILLS`.

	A second call is refused. To allow a rerun on purpose, a System Manager can set
	`si_datev_backfill_done` back to 0 (e.g. with `frappe.client.set_value`).
	"""
	frappe.has_permission(SETTINGS_DOCTYPE, "write", throw=True)
	_check_columns_exist()

	with filelock("gaertnerei_berger_si_datev_backfill"):
		state = _get_backfill_state_for_update()
		if cint(state.get("si_datev_backfill_done")):
			frappe.throw(
				_("This one-time operation has already been executed on {0} by {1}.").format(
					format_datetime(state.get("si_datev_backfill_on")), state.get("si_datev_backfill_by")
				)
			)

		results = {
			label: _fill_empty_from_source(table, target_field, source_table, link_field, source_field)
			for label, table, target_field, source_table, link_field, source_field in SALES_INVOICE_DATEV_BACKFILLS
		}

		frappe.db.set_single_value(
			SETTINGS_DOCTYPE,
			{
				"si_datev_backfill_done": 1,
				"si_datev_backfill_on": now_datetime(),
				"si_datev_backfill_by": frappe.session.user,
				"si_datev_backfill_result": "\n".join(
					f"{_(label)}: {count}" for label, count in results.items()
				),
			},
		)
		# Commit while the lock is still held. Frappe would only commit after the request
		# returns, and a second request waiting on the lock could then still read "not done".
		frappe.db.commit()

	return results


def _check_columns_exist():
	"""Refuse to run, before writing anything, if a target or source column is missing.

	Otherwise that backfill would be skipped and still be recorded as done.
	"""
	missing = [
		f"{doctype}.{fieldname}"
		for _label, table, target_field, source_table, link_field, source_field in SALES_INVOICE_DATEV_BACKFILLS
		for doctype, fieldname in (
			(table, target_field),
			(table, link_field),
			(source_table, source_field),
		)
		if not frappe.db.has_column(doctype, fieldname)
	]
	if missing:
		frappe.throw(
			_("Cannot run the DATEV backfill. Missing columns: {0}. Run bench migrate first.").format(
				", ".join(missing)
			)
		)


def _get_backfill_state_for_update():
	"""Read the backfill state with a locking read, so it reflects the latest committed values.

	A plain read could return an older snapshot (InnoDB REPEATABLE READ) and miss a run that
	another request has just committed.
	"""
	rows = frappe.db.sql(
		"""
		SELECT field, value FROM `tabSingles`
		WHERE doctype = %s AND field IN ('si_datev_backfill_done', 'si_datev_backfill_on', 'si_datev_backfill_by')
		FOR UPDATE
		""",
		SETTINGS_DOCTYPE,
	)
	return dict(rows)


def _fill_empty_from_source(table, target_field, source_table, link_field, source_field):
	"""Copy source_field into empty target_field via raw SQL, so no controller runs and `modified` stays.

	All identifiers come from the `SALES_INVOICE_DATEV_BACKFILLS` constant, never from the caller,
	so formatting them into the SQL is safe. The count is taken just before the UPDATE; an invoice
	saved in between could make it differ by a row, which only affects the reported number.
	"""
	join = f"`tab{table}` tgt JOIN `tab{source_table}` src ON src.name = tgt.`{link_field}`"
	where = f"IFNULL(tgt.`{target_field}`, '') = '' AND IFNULL(src.`{source_field}`, '') != ''"

	count = frappe.db.sql(f"SELECT COUNT(*) FROM {join} WHERE {where}")[0][0]
	if count:
		frappe.db.sql(f"UPDATE {join} SET tgt.`{target_field}` = src.`{source_field}` WHERE {where}")
	return count
