# Copyright (c) 2026, Gaertnerei Berger and contributors
# For license information, please see license.txt

"""
Invoice orientation in the Buchungsstapel export (GitLab #97).

DATEV's S/H refers to Konto. Invoices put the Personenkonto on Konto, so a
normal invoice is Debitor Soll / Kreditor Haben; DATEV rejected the old
mixed rows with REW02890 because they read as Gutschriften.
"""

from decimal import Decimal
from unittest import TestCase
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from gaertnerei_berger.gb_datev.report.datev.datev import (
	add_storno_rows,
	get_purchase_invoice_params,
	get_sales_invoice_params,
	keep_soll_haben_with_personenkonto,
	prepare_buchungsstapel_transactions,
)
from gaertnerei_berger.patches.post_model_sync import drop_invoice_account_mappings
from gaertnerei_berger.patches.post_model_sync.seed_datev_mapping_records import BUCHUNGSSTAPEL_REPORT

DATEV_MODULE = "gaertnerei_berger.gb_datev.report.datev.datev"
UMSATZ = "Umsatz (ohne Soll/Haben-Kz)"
SH = "Soll/Haben-Kennzeichen"
GEGENKONTO = "Gegenkonto (ohne BU-Schlüssel)"

DEBITOR = "10035"
KREDITOR = "70063"


def gl_row(voucher_type, voucher_no, party_type):
	return {
		UMSATZ: Decimal("100.00"),
		SH: "S",
		"Konto": "",
		GEGENKONTO: "",
		"BU-Schlüssel": "",
		"Belegdatum": "2026-12-01",
		"Belegfeld 1": voucher_no,
		"Buchungstext": "Test",
		"Beleginfo - Art 1": voucher_type,
		"Beleginfo - Inhalt 1": voucher_no,
		"Beleginfo - Art 3": party_type,
		"Beleginfo - Inhalt 3": "_Test Partei",
		# The GL query; the Mapping fills it from due_date
		"Fälligkeit": None,
	}


def invoice(voucher_no, item_konto, bu, sign=1, is_return=0, **fields):
	return frappe._dict(
		name=voucher_no,
		company="_Test GmbH",
		is_return=is_return,
		due_date="2026-12-31",
		custom_datev_account_no=fields.pop("header_konto", ""),
		items=[
			frappe._dict(
				custom_datev_account_no=item_konto, custom_bu_schlussel=bu, base_net_amount=100 * sign
			)
		],
		**fields,
	)


def mapping(*pairs):
	return [frappe._dict(map_to_field=field, map_to_column=column) for field, column in pairs]


# Mappings as found on the customer site: header (Personenkonto) on Konto,
# item account on Gegenkonto, plus the due date
LIVE_INVOICE_MAPPING = mapping(
	("custom_datev_account_no", "Konto"),
	("items.custom_datev_account_no", GEGENKONTO),
	("due_date", "Fälligkeit"),
)


class InvoiceExportCase(TestCase):
	def export(self, vouchers, mappings=None, **filters):
		gl_rows = [
			gl_row(voucher_type, voucher.name, "Customer" if voucher_type == "Sales Invoice" else "Supplier")
			for (voucher_type, _), voucher in vouchers.items()
		]
		export_filters = {
			"company": "_Test GmbH",
			"against_account": "9090",
			"buchungsstapel_export_mode": "consultant_booking",
			"invoice_amount_basis": "net",
			**filters,
		}

		def party_number(party_type, **kwargs):
			return DEBITOR if party_type == "Customer" else KREDITOR

		with (
			patch(f"{DATEV_MODULE}.get_transactions", return_value=gl_rows),
			patch(f"{DATEV_MODULE}.load_voucher_doc", side_effect=lambda vt, vn: vouchers.get((vt, vn))),
			patch(f"{DATEV_MODULE}.get_buchungsstapel_mappings", return_value=mappings or {}),
			patch(f"{DATEV_MODULE}.get_account_maps", return_value=({}, {})),
			patch(f"{DATEV_MODULE}.get_party_account_number", side_effect=party_number),
			patch(f"{DATEV_MODULE}.get_automatic_account_numbers", return_value=set()),
		):
			return prepare_buchungsstapel_transactions(export_filters)

	def summary(self, rows):
		return [(row["Konto"], row[GEGENKONTO], row[SH], row["BU-Schlüssel"]) for row in rows]


class TestInvoiceOrientation(InvoiceExportCase):
	def test_sales_invoice_debitor_soll(self):
		rows = self.export({("Sales Invoice", "RG-1"): invoice("RG-1", "8300", "")})
		self.assertEqual(self.summary(rows), [(DEBITOR, "8300", "S", "")])

	def test_purchase_invoice_kreditor_haben(self):
		rows = self.export({("Purchase Invoice", "ER-1"): invoice("ER-1", "3300", "8")})
		self.assertEqual(self.summary(rows), [(KREDITOR, "3300", "H", "8")])

	def test_returns_flip(self):
		rows = self.export(
			{
				("Sales Invoice", "RG-2"): invoice("RG-2", "8300", "", sign=-1, is_return=1),
				("Purchase Invoice", "ER-2"): invoice("ER-2", "3300", "8", sign=-1, is_return=1),
			}
		)
		self.assertEqual(
			sorted(self.summary(rows)),
			[(DEBITOR, "8300", "H", ""), (KREDITOR, "3300", "S", "8")],
		)

	def test_live_mapping_keeps_orientation(self):
		# Header account on Konto, items on Gegenkonto: the customer's live config.
		# Before #97 this produced Debitor Haben and DATEV rejected the due date.
		rows = self.export(
			{
				("Sales Invoice", "RG-3"): invoice("RG-3", "8300", "", header_konto="1400"),
				("Purchase Invoice", "ER-3"): invoice("ER-3", "3300", "8", header_konto="1600"),
			},
			mappings={
				"Sales Invoice": {"Both": LIVE_INVOICE_MAPPING},
				"Purchase Invoice": {"Both": LIVE_INVOICE_MAPPING},
			},
		)
		self.assertEqual(
			sorted(self.summary(rows)),
			[(DEBITOR, "8300", "S", ""), (KREDITOR, "3300", "H", "8")],
		)

	def test_swapping_mapping_cannot_move_invoice_accounts(self):
		rows = self.export(
			{("Sales Invoice", "RG-4"): invoice("RG-4", "8300", "", header_konto=DEBITOR)},
			mappings={
				"Sales Invoice": {
					"Both": mapping(
						("items.custom_datev_account_no", "Konto"),
						("custom_datev_account_no", GEGENKONTO),
					)
				}
			},
		)
		self.assertEqual(self.summary(rows), [(DEBITOR, "8300", "S", "")])


class TestFaelligkeit(InvoiceExportCase):
	def test_invoice_keeps_due_date_from_mapping(self):
		rows = self.export(
			{("Sales Invoice", "RG-5"): invoice("RG-5", "8300", "")},
			mappings={"Sales Invoice": {"Both": LIVE_INVOICE_MAPPING}},
		)
		self.assertEqual(str(rows[0]["Fälligkeit"]), "2026-12-31")

	def test_return_gets_no_due_date_from_mapping(self):
		rows = self.export(
			{
				("Sales Invoice", "RG-6"): invoice("RG-6", "8300", "", sign=-1, is_return=1),
				("Purchase Invoice", "ER-6"): invoice("ER-6", "3300", "8", sign=-1, is_return=1),
			},
			mappings={
				"Sales Invoice": {"Both": LIVE_INVOICE_MAPPING},
				"Purchase Invoice": {"Both": LIVE_INVOICE_MAPPING},
			},
		)
		self.assertEqual([row["Fälligkeit"] for row in rows], [None, None])

	def test_return_due_date_is_empty_in_query(self):
		for params in (get_sales_invoice_params, get_purchase_invoice_params):
			fields = params({})[0]
			self.assertIn("is_return = 1 THEN NULL", fields)

	def test_storno_has_no_due_date(self):
		row = {
			SH: "S",
			"Konto": DEBITOR,
			GEGENKONTO: "8300",
			"Fälligkeit": "2026-12-31",
			"_datev_cancelled": True,
		}
		result = add_storno_rows([row], {"include_cancelled": 1, "storno_mode": "swap_soll_haben"})
		self.assertEqual(result[0]["Fälligkeit"], "2026-12-31")
		self.assertIsNone(result[1]["Fälligkeit"])
		self.assertEqual(result[1][SH], "H")


class TestKeepSollHabenWithPersonenkonto(TestCase):
	def journal_row(self, konto, gegenkonto, sh="H"):
		return {
			"Konto": konto,
			GEGENKONTO: gegenkonto,
			SH: sh,
			"_datev_party_no": DEBITOR,
			"_datev_party_column": GEGENKONTO,
		}

	def test_flips_when_mapping_moved_party_to_konto(self):
		row = self.journal_row(DEBITOR, "4300")
		keep_soll_haben_with_personenkonto([row])
		self.assertEqual(row[SH], "S")
		self.assertEqual(row["_datev_party_column"], "Konto")

	def test_keeps_when_party_stays(self):
		row = self.journal_row("4300", DEBITOR)
		keep_soll_haben_with_personenkonto([row])
		self.assertEqual(row[SH], "H")

	def test_keeps_when_party_is_gone(self):
		row = self.journal_row("4300", "9090")
		keep_soll_haben_with_personenkonto([row])
		self.assertEqual(row[SH], "H")

	def test_ignores_rows_without_party(self):
		row = {"Konto": "1800", GEGENKONTO: "1600", SH: "S"}
		keep_soll_haben_with_personenkonto([row])
		self.assertEqual(row[SH], "S")


class TestDropInvoiceAccountMappingsPatch(FrappeTestCase):
	def make_mapping(self, voucher_type, rows):
		name = f"{voucher_type} - Both"
		if frappe.db.exists("DATEV Mapping", name):
			frappe.delete_doc("DATEV Mapping", name, force=True)
		doc = frappe.new_doc("DATEV Mapping")
		doc.voucher_type = voucher_type
		doc.party_account_type = "Both"
		for field, column in rows:
			doc.append(
				"mapping_fields",
				{"report_type": BUCHUNGSSTAPEL_REPORT, "map_to_field": field, "map_to_column": column},
			)
		doc.insert(ignore_permissions=True)
		return doc.name

	def columns(self, name):
		return sorted(frappe.get_all("DATEV Mapping Field", filters={"parent": name}, pluck="map_to_column"))

	def test_keeps_only_metadata_rows(self):
		sales = self.make_mapping(
			"Sales Invoice",
			[
				("items.amount", UMSATZ),
				("custom_datev_account_no", "Konto"),
				("items.custom_datev_account_no", GEGENKONTO),
				("items.custom_bu_schlussel", "BU-Schlüssel"),
				("due_date", "Fälligkeit"),
			],
		)
		purchase = self.make_mapping(
			"Purchase Invoice",
			[
				("custom_datev_account_no", GEGENKONTO),
				("items.custom_datev_account_no", "Konto"),
				("bill_no", "Beleginfo - Inhalt 5"),
				("due_date", "Fälligkeit"),
			],
		)
		payment = self.make_mapping("Payment Entry", [("custom_datev_account_no", "Konto")])

		drop_invoice_account_mappings.execute()

		self.assertEqual(self.columns(sales), ["Fälligkeit"])
		self.assertEqual(self.columns(purchase), ["Beleginfo - Inhalt 5", "Fälligkeit"])
		self.assertEqual(self.columns(payment), ["Konto"])
