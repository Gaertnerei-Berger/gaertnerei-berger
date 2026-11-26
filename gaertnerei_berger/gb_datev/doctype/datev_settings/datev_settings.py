# Copyright (c) 2023, Gaertnerei Berger and contributors
# For license information, please see license.txt

from frappe import _, throw
from frappe.model.document import Document

from gaertnerei_berger.gb_datev.account import has_automatic_accounts, msgprint_net_amount_basis_warning
from gaertnerei_berger.gb_datev.master_data import is_party_tax_id_field


class DATEVSettings(Document):
	def validate(self):
		if (
			self.temporary_against_account_number
			and len(self.temporary_against_account_number) != self.account_number_length
		):
			throw(
				_("Temporary Against Account Number must be {0} digits long").format(
					self.account_number_length
				)
			)

		if (
			self.opening_against_account_number
			and len(self.opening_against_account_number) != self.account_number_length
		):
			throw(
				_("Opening Against Account Number must be {0} digits long").format(self.account_number_length)
			)

		if self.invoice_amount_basis not in {
			"net",
			"gross",
			None,
			"",
		}:
			throw(_("Amount Basis must be Net or Gross."))

		if self.payment_line_mode not in {"per_invoice", "per_payment", None, ""}:
			throw(_("Lines per Payment must be per_invoice or per_payment."))

		if self.payment_belegfeld_1 not in {"payment_entry", "invoice", None, ""}:
			throw(_("Belegfeld 1 on Payment Lines must be payment_entry or invoice."))

		for fieldname in ("steuernummer_field", "ust_idnr_field"):
			value = self.get(fieldname)
			if value and not is_party_tax_id_field(value):
				throw(
					_("{0}: {1} must be a Data field on both Customer and Supplier.").format(
						_(self.meta.get_label(fieldname)), value
					)
				)

		if self.invoice_amount_basis != "gross" and has_automatic_accounts(self.client):
			msgprint_net_amount_basis_warning()
