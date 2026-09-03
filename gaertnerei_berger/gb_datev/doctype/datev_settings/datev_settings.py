# Copyright (c) 2023, Gaertnerei Berger and contributors
# For license information, please see license.txt

from frappe import _, throw
from frappe.model.document import Document


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

		if self.buchungsstapel_export_mode not in {"consultant_booking", "gl_mirror"}:
			# gl_mirror remains valid in code/tests but is hidden from Settings UI (#9=C)
			throw(_("Export Mode must be Consultant Booking."))

		if self.buchungsstapel_export_mode == "consultant_booking" and self.invoice_amount_basis not in {
			"net",
			"gross",
			None,
			"",
		}:
			throw(_("Amount Basis must be Net or Gross."))
