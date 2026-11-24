// Copyright (c) 2019, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

// Text fields that Customer and Supplier both have, custom fields included (GitLab #114).
// Same list as TAX_ID_FIELDTYPES in gb_datev/master_data.py, which checks it on save.
const TAX_ID_FIELDTYPES = ["Data", "Small Text"];

frappe.ui.form.on("DATEV Settings", {
	refresh: function (frm) {
		frm.add_custom_button(__("Open DATEV"), () => frappe.set_route("datev"), "fa fa-table");
		set_tax_id_field_options(frm);
	},
});

function set_tax_id_field_options(frm) {
	frappe.model.with_doctype("Customer", () => {
		frappe.model.with_doctype("Supplier", () => {
			const supplier_fields = new Set(
				frappe.meta
					.get_docfields("Supplier")
					.filter((df) => TAX_ID_FIELDTYPES.includes(df.fieldtype))
					.map((df) => df.fieldname)
			);
			const options = frappe.meta
				.get_docfields("Customer")
				.filter((df) => TAX_ID_FIELDTYPES.includes(df.fieldtype) && supplier_fields.has(df.fieldname))
				.map((df) => ({ value: df.fieldname, label: `${__(df.label)} (${df.fieldname})` }));

			for (const fieldname of ["steuernummer_field", "ust_idnr_field"]) {
				// Autocomplete reads df.options only when its input is built
				frm.set_df_property(fieldname, "options", options);
				frm.fields_dict[fieldname].set_data(options);
				frm.refresh_field(fieldname);
			}
		});
	});
}
