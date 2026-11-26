frappe.ui.form.on("DATEV Export", {
	refresh(frm) {
		if (frm.doc.master_data_warnings) {
			frm.dashboard.set_headline_alert(
				__("Some Customers or Suppliers have no Debitor/Kreditor number and are missing from the master data files. See Master Data Warnings."),
				"orange"
			);
		}

		if (frm.doc.export_file && frm.doc.status === "Generated") {
			frm.add_custom_button(__("Download ZIP"), () => {
				window.open(frappe.urllib.get_full_url(frm.doc.export_file));
			});
		}
	},
});
