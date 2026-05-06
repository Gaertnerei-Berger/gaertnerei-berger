frappe.ui.form.on("DATEV Mapping", {
	refresh(frm) {
		if (frm.doc.voucher_type) {
			frm.trigger("voucher_type");
		}
	},

	voucher_type(frm) {
		if (!frm.doc.voucher_type) {
			frm.fields_dict.mapping_fields.grid.update_docfield_property("map_to_field", "options", "");
			frm.refresh_field("mapping_fields");
			return;
		}

		frappe.call({
			method: "gaertnerei_berger.gb_datev.doctype.datev_mapping.datev_mapping.get_map_to_field_options",
			args: { voucher_type: frm.doc.voucher_type },
		}).then((r) => {
			const options = ["", ...(r.message || [])].join("\n");
			frm.fields_dict.mapping_fields.grid.update_docfield_property("map_to_field", "options", options);
			frm.refresh_field("mapping_fields");
		});
	},
});
