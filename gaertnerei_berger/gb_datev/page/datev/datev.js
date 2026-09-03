frappe.pages["datev"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("DATEV"),
		single_column: true,
	});

	page.datev = new gaertnerei_berger.DatevPage(page);
};

frappe.provide("gaertnerei_berger");

gaertnerei_berger.DatevPage = class DatevPage {
	constructor(page) {
		this.page = page;
		this.wrapper = $(page.body);
		this.connection_doctypes = [
			"DATEV Settings",
			"DATEV Mapping",
			"DATEV Unternehmen Online Settings",
			"DATEV Export",
		];
		this.make_filters();
		this.make_dashboard();
		this.setup_primary_action();
		this.refresh_company_data();
	}

	make_filters() {
		this.company_field = this.page.add_field({
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default:
				frappe.defaults.get_user_default("Company") ||
				frappe.defaults.get_global_default("Company"),
			reqd: 1,
			change: () => this.refresh_company_data(),
		});

		this.from_date_field = this.page.add_field({
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			default: frappe.datetime.add_months(frappe.datetime.month_start(), -1),
			reqd: 1,
			change: () => this.sync_to_date_for_month_start(),
		});

		this.to_date_field = this.page.add_field({
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			default: frappe.datetime.add_days(frappe.datetime.month_start(), -1),
			reqd: 1,
		});

		this.voucher_type_field = this.page.add_field({
			fieldname: "voucher_type",
			label: __("Voucher Type"),
			fieldtype: "Select",
			options:
				"\nSales Invoice\nPurchase Invoice\nPayment Entry\nExpense Claim\nPayroll Entry\nBank Reconciliation\nAsset\nStock Entry\nJournal Entry",
		});

		this.remarks_field = this.page.add_field({
			fieldname: "remarks",
			label: __("Remarks"),
			fieldtype: "Small Text",
		});
	}

	sync_to_date_for_month_start() {
		const from_date = this.from_date_field.get_value();
		if (!from_date || moment(from_date).date() !== 1) {
			return;
		}

		const month_end = frappe.datetime.add_days(
			frappe.datetime.add_months(from_date, 1),
			-1
		);
		this.to_date_field.set_value(month_end);
	}

	make_dashboard() {
		this.dashboard = $('<div class="form-dashboard"></div>').appendTo(this.wrapper);
		this.make_connections();
		this.make_exports_section();
	}

	make_dashboard_section(label, css_class) {
		const section = $(`
			<div class="row form-dashboard-section ${css_class || ""}">
				<div class="section-head">${label}</div>
				<div class="section-body"></div>
			</div>
		`).appendTo(this.dashboard);

		return section.find(".section-body");
	}

	make_connections() {
		this.connections_body = this.make_dashboard_section(__("Connections"), "form-links");
		this.transactions_area = $('<div class="transactions"></div>').appendTo(this.connections_body);

		const internal_links = {};
		this.connection_doctypes.forEach((doctype) => {
			internal_links[doctype] = true;
		});

		$(frappe.render_template("form_links", {
			transactions: [
				{
					label: __("Configuration"),
					items: [
						"DATEV Settings",
						"DATEV Mapping",
						"DATEV Unternehmen Online Settings",
					],
				},
				{
					label: __("Exports"),
					items: ["DATEV Export"],
				},
			],
			internal_links,
		})).appendTo(this.transactions_area);

		this.transactions_area.find(".badge-link").on("click", (event) => {
			event.preventDefault();
			this.open_connection($(event.currentTarget).closest(".document-link"));
		});
	}

	open_connection($link) {
		const doctype = $link.attr("data-doctype");
		const company = this.company_field.get_value();

		if (doctype === "DATEV Settings") {
			if (!company) {
				frappe.msgprint(__("Please select a Company first."));
				return;
			}
			frappe.set_route("Form", "DATEV Settings", company);
			return;
		}

		if (doctype === "DATEV Mapping") {
			frappe.set_route("List", "DATEV Mapping");
			return;
		}

		if (doctype === "DATEV Unternehmen Online Settings") {
			frappe.set_route(
				"Form",
				"DATEV Unternehmen Online Settings",
				"DATEV Unternehmen Online Settings"
			);
			return;
		}

		if (doctype === "DATEV Export") {
			if (company) {
				frappe.route_options = { company };
			}
			frappe.set_route("List", "DATEV Export", "List");
		}
	}

	set_connection_count(doctype, count) {
		const $link = this.transactions_area.find(`.document-link[data-doctype="${doctype}"]`);
		if (!$link.length) {
			return;
		}

		$link.find(".open-notification").addClass("hidden");
		$link
			.find(".count")
			.removeClass("hidden")
			.text(cint(count) > 99 ? "99+" : count)
			.attr("title", __("Count of linked documents"));
	}

	refresh_connections() {
		const company = this.company_field.get_value();
		if (!company) {
			this.connection_doctypes.forEach((doctype) => this.set_connection_count(doctype, 0));
			return;
		}

		frappe.call({
			method: "gaertnerei_berger.gb_datev.report.datev.datev.get_datev_connection_counts",
			args: { company },
			callback: (response) => {
				const counts = response.message || {};
				this.connection_doctypes.forEach((doctype) => {
					this.set_connection_count(doctype, counts[doctype] || 0);
				});
			},
		});
	}

	make_exports_section() {
		this.exports_body = this.make_dashboard_section(__("Recent Exports"));
		this.exports_table = $('<div class="datev-exports-table"></div>').appendTo(this.exports_body);
	}

	setup_primary_action() {
		this.page.set_primary_action(__("Create DATEV Export"), () => this.create_export(false));
		this.page.add_inner_button(
			__("Preview Transactions"),
			() => {
				const values = this.get_values();
				if (values) {
					frappe.set_route("query-report", "DATEV", values);
				}
			},
			__("View")
		);
	}

	get_values() {
		const values = {
			company: this.company_field.get_value(),
			from_date: this.from_date_field.get_value(),
			to_date: this.to_date_field.get_value(),
			voucher_type: this.voucher_type_field.get_value(),
			remarks: this.remarks_field.get_value(),
		};

		if (!values.company || !values.from_date || !values.to_date) {
			frappe.msgprint(__("Company, From Date and To Date are required."));
			return null;
		}

		return values;
	}

	create_export(force) {
		const values = this.get_values();
		if (!values) return;

		frappe.call({
			method: "gaertnerei_berger.gb_datev.report.datev.datev.create_datev_export",
			args: {
				company: values.company,
				from_date: values.from_date,
				to_date: values.to_date,
				voucher_type: values.voucher_type,
				remarks: values.remarks,
				force: force ? 1 : 0,
			},
			freeze: true,
			freeze_message: __("Creating DATEV Export..."),
			callback: (response) => {
				const message = response.message || {};
				if (message.duplicate) {
					const existing = message.existing || {};
					frappe.confirm(
						__(
							"An export for this period already exists ({0} on {1}). Create another export anyway?",
							[existing.name, frappe.datetime.str_to_user(existing.posting_date)]
						),
						() => this.create_export(true)
					);
					return;
				}

				frappe.show_alert({
					message: __("DATEV Export {0} created", [message.name]),
					indicator: "green",
				});
				this.refresh_company_data();

				if (message.export_file) {
					window.open(frappe.urllib.get_full_url(message.export_file));
				}

				frappe.set_route("Form", "DATEV Export", message.name);
			},
		});
	}

	refresh_company_data() {
		this.refresh_connections();
		this.refresh_exports();
	}

	refresh_exports() {
		const company = this.company_field.get_value();
		if (!company) {
			this.exports_table.empty();
			return;
		}

		frappe.call({
			method: "gaertnerei_berger.gb_datev.report.datev.datev.get_recent_datev_exports",
			args: { company, limit: 10 },
			callback: (response) => {
				this.render_exports(response.message || []);
			},
		});
	}

	render_exports(rows) {
		this.exports_table.empty();

		if (!rows.length) {
			this.exports_table.append(`<p class="text-muted">${__("No exports yet.")}</p>`);
			return;
		}

		const table = $(`
			<table class="table table-bordered table-hover">
				<thead>
					<tr>
						<th>${__("Export")}</th>
						<th>${__("Period")}</th>
						<th>${__("Posting Date")}</th>
						<th>${__("Exported By")}</th>
						<th>${__("Rows")}</th>
						<th>${__("Status")}</th>
					</tr>
				</thead>
				<tbody></tbody>
			</table>
		`).appendTo(this.exports_table);

		const tbody = table.find("tbody");
		rows.forEach((row) => {
			const period = `${frappe.datetime.str_to_user(row.from_date)} – ${frappe.datetime.str_to_user(row.to_date)}`;
			$(`
				<tr>
					<td><a href="/app/datev-export/${row.name}">${row.name}</a></td>
					<td>${period}</td>
					<td>${frappe.datetime.str_to_user(row.posting_date)}</td>
					<td>${row.exported_by || ""}</td>
					<td>${row.row_count || 0}</td>
					<td>${row.status || ""}</td>
				</tr>
			`).appendTo(tbody);
		});
	}
};
