frappe.query_reports["DATEV"] = {
	filters: [
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default:
				frappe.defaults.get_user_default("Company") || frappe.defaults.get_global_default("Company"),
			reqd: 1,
		},
		{
			fieldname: "from_date",
			label: __("From Date"),
			default: moment().subtract(1, "month").startOf("month").format(),
			fieldtype: "Date",
			reqd: 1,
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			default: moment().subtract(1, "month").endOf("month").format(),
			fieldtype: "Date",
			reqd: 1,
		},
		{
			fieldname: "voucher_type",
			label: __("Voucher Type"),
			fieldtype: "Select",
			options:
				"\nSales Invoice\nPurchase Invoice\nPayment Entry\nExpense Claim\nPayroll Entry\nBank Reconciliation\nAsset\nStock Entry\nJournal Entry",
		},
	],
	onload: function (query_report) {
		let company = frappe.query_report.get_filter_value("company");
		frappe.db.exists("DATEV Settings", company).then((settings_exist) => {
			if (!settings_exist) {
				frappe.confirm(
					__("DATEV Settings for your Company are missing. Would you like to create them now?"),
					() => frappe.new_doc("DATEV Settings", { company: company })
				);
			}
		});

		query_report.page.set_primary_action(__("Download DATEV File"), async () => {
			const values = query_report.get_values();
			if (!values || !(await check_datev_settings(values.company))) return;

			const filters = encodeURIComponent(JSON.stringify(values));
			window.open(
				`/api/method/gaertnerei_berger.gb_datev.report.datev.datev.download_datev_csv?filters=${filters}`
			);
		});

		query_report.page.add_menu_item(__("Change DATEV Settings"), () => {
			let company = frappe.query_report.get_filter_value("company"); // read company from filters again – it might have changed by now.
			frappe.set_route("Form", "DATEV Settings", company);
		});
	},
};

// Before an export: the DATEV Settings must name the Steuernummer and USt-IdNr fields (GitLab #114).
// Resolves true when they are set; otherwise shows a dialog that leads to DATEV Settings.
function check_datev_settings(company) {
	return frappe
		.xcall("gaertnerei_berger.gb_datev.report.datev.datev.check_datev_settings", { company })
		.then((result) => {
			if (!result.missing.length) return true;

			const dialog = new frappe.ui.Dialog({
				title: __("DATEV Settings incomplete"),
				fields: [{ fieldtype: "HTML", fieldname: "message", options: `<p>${result.message}</p>` }],
				primary_action_label: __("Open DATEV Settings"),
				primary_action() {
					dialog.hide();
					if (result.settings_exist) {
						frappe.set_route("Form", "DATEV Settings", company);
					} else {
						frappe.new_doc("DATEV Settings", { client: company });
					}
				},
			});
			dialog.show();
			return false;
		});
}
