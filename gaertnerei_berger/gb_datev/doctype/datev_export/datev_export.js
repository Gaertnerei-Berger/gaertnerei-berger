frappe.ui.form.on("DATEV Export", {
	refresh(frm) {
		if (frm.doc.export_file && frm.doc.status === "Generated") {
			frm.add_custom_button(__("Download ZIP"), () => {
				window.open(frappe.urllib.get_full_url(frm.doc.export_file));
			});
		}
	},
});
