# Copyright (c) 2026, Gaertnerei Berger and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import getdate, nowdate


class DATEVExport(Document):
	def before_insert(self):
		if not self.exported_by:
			self.exported_by = frappe.session.user
		if not self.posting_date:
			self.posting_date = nowdate()

	def validate(self):
		if getdate(self.from_date) > getdate(self.to_date):
			frappe.throw(frappe._("From Date cannot be after To Date"))
