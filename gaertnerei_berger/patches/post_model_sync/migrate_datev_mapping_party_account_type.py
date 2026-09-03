import frappe

from gaertnerei_berger.gb_datev.doctype.datev_mapping.datev_mapping import (
	PARTY_ACCOUNT_TYPE_BOTH,
	PARTY_ACCOUNT_TYPE_PAYABLE,
	PARTY_ACCOUNT_TYPE_RECEIVABLE,
)
from gaertnerei_berger.patches.post_model_sync.seed_datev_mapping_records import (
	get_default_mappings,
	mapping_name,
	upsert_mapping,
)


def execute():
	"""Add party_account_type, rename legacy mappings, seed directional PE/JE maps."""
	frappe.reload_doc("gb_datev", "doctype", "datev_mapping")

	if not frappe.db.has_column("DATEV Mapping", "party_account_type"):
		# migrate should have synced the DocType; guard for safety
		frappe.reload_doc("gb_datev", "doctype", "datev_mapping")

	_backfill_party_account_type()
	_rename_legacy_mapping_names()
	_seed_directional_defaults()
	_remove_obsolete_single_pe_je_both_if_split_exists()


def _backfill_party_account_type():
	frappe.db.sql(
		"""
		UPDATE `tabDATEV Mapping`
		SET party_account_type = %s
		WHERE IFNULL(party_account_type, '') = ''
		""",
		PARTY_ACCOUNT_TYPE_BOTH,
	)


def _rename_legacy_mapping_names():
	"""Rename docs still named exactly as voucher_type to '{voucher_type} - {party_account_type}'."""
	rows = frappe.get_all(
		"DATEV Mapping",
		fields=["name", "voucher_type", "party_account_type"],
		limit_page_length=0,
	)
	for row in rows:
		party_account_type = row.party_account_type or PARTY_ACCOUNT_TYPE_BOTH
		target = mapping_name(row.voucher_type, party_account_type)
		if row.name == target:
			continue
		if row.name != row.voucher_type:
			# Already renamed or custom name — only force-rename exact legacy names
			continue
		if frappe.db.exists("DATEV Mapping", target):
			# Target already exists; drop legacy duplicate after copying missing fields
			_merge_mapping_fields(row.name, target)
			frappe.delete_doc("DATEV Mapping", row.name, force=True, ignore_permissions=True)
			continue
		frappe.rename_doc("DATEV Mapping", row.name, target, force=True, merge=False)


def _merge_mapping_fields(source_name, target_name):
	source = frappe.get_doc("DATEV Mapping", source_name)
	target = frappe.get_doc("DATEV Mapping", target_name)
	existing = {(r.report_type, r.map_to_field, r.map_to_column) for r in target.mapping_fields}
	changed = False
	for row in source.mapping_fields:
		key = (row.report_type, row.map_to_field, row.map_to_column)
		if key in existing:
			continue
		target.append(
			"mapping_fields",
			{
				"report_type": row.report_type,
				"map_to_field": row.map_to_field,
				"map_to_column": row.map_to_column,
			},
		)
		changed = True
	if changed:
		target.save(ignore_permissions=True)


def _seed_directional_defaults():
	for (voucher_type, party_account_type), mappings in get_default_mappings().items():
		upsert_mapping(voucher_type, mappings, party_account_type=party_account_type)


def _remove_obsolete_single_pe_je_both_if_split_exists():
	"""
	If PE/JE Receivable+Payable exist, remove a leftover 'Both' PE/JE mapping that only
	existed as the pre-split catch-all (optional cleanup).
	"""
	for voucher_type in ("Payment Entry", "Journal Entry"):
		receivable = mapping_name(voucher_type, PARTY_ACCOUNT_TYPE_RECEIVABLE)
		payable = mapping_name(voucher_type, PARTY_ACCOUNT_TYPE_PAYABLE)
		both = mapping_name(voucher_type, PARTY_ACCOUNT_TYPE_BOTH)
		if (
			frappe.db.exists("DATEV Mapping", receivable)
			and frappe.db.exists("DATEV Mapping", payable)
			and frappe.db.exists("DATEV Mapping", both)
		):
			frappe.delete_doc("DATEV Mapping", both, force=True, ignore_permissions=True)
