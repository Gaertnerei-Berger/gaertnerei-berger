// Offer only Tax Categories of the form's side (GitLab #110).
// Categories with an empty Tax Category Type show on both sides.

// Frappe loads this file once per hooked doctype; register the handlers only once.
if (!window.gaertnerei_berger?.tax_category_filter) {
	frappe.provide("gaertnerei_berger");

	gaertnerei_berger.tax_category_filter = {
		SIDE_BY_DOCTYPE: {
			Quotation: "Sales",
			"Sales Order": "Sales",
			"Delivery Note": "Sales",
			"Sales Invoice": "Sales",
			"POS Invoice": "Sales",
			"POS Profile": "Sales",
			Customer: "Sales",
			"Sales Taxes and Charges Template": "Sales",
			"Supplier Quotation": "Purchase",
			"Purchase Order": "Purchase",
			"Purchase Receipt": "Purchase",
			"Purchase Invoice": "Purchase",
			Supplier: "Purchase",
			"Purchase Taxes and Charges Template": "Purchase",
		},

		get_side(frm) {
			if (frm.doctype === "Tax Rule") {
				return frm.doc.tax_type;
			}
			return this.SIDE_BY_DOCTYPE[frm.doctype];
		},

		setup(frm) {
			frm.set_query("tax_category", () => {
				const side = this.get_side(frm);
				if (!side) {
					return {};
				}
				const other_side = side === "Sales" ? "Purchase" : "Sales";
				return { filters: { custom_tax_category_type: ["!=", other_side] } };
			});
		},
	};

	[...Object.keys(gaertnerei_berger.tax_category_filter.SIDE_BY_DOCTYPE), "Tax Rule"].forEach((doctype) => {
		frappe.ui.form.on(doctype, {
			setup(frm) {
				gaertnerei_berger.tax_category_filter.setup(frm);
			},
		});
	});
}
