frappe.provide("gaertnerei_berger.journal_entry");

gaertnerei_berger.journal_entry = {
	_sync_timeout: null,
	_account_type_cache: {},

	refresh_datev_fields(frm) {
		(frm.doc.accounts || []).forEach((row) => {
			this.ensure_account_type(row.account, () => {
				this.toggle_datev_fields(frm, row);
				if (cint(row.custom_datev_auto_tax)) {
					this.lock_auto_tax_row(frm, row);
				}
			});
		});
	},

	ensure_account_type(account, callback) {
		if (!account) {
			callback && callback("");
			return;
		}
		if (this._account_type_cache[account] !== undefined) {
			callback && callback(this._account_type_cache[account]);
			return;
		}
		frappe.db.get_value("Account", account, "account_type", (r) => {
			this._account_type_cache[account] = (r && r.account_type) || "";
			callback && callback(this._account_type_cache[account]);
		});
	},

	toggle_datev_fields(frm, row) {
		const is_tax = this.is_tax_account(row.account);
		const is_party = this.is_party_account(row.account);
		const hide = is_tax || is_party || cint(row.custom_datev_auto_tax);

		["custom_item_tax_template", "custom_bu_schlussel"].forEach((fieldname) => {
			frm.set_df_property(fieldname, "hidden", hide ? 1 : 0, frm.doc.name, "accounts", row.name);
			frm.set_df_property(fieldname, "read_only", hide ? 1 : 0, frm.doc.name, "accounts", row.name);
		});

		if (hide && !cint(row.custom_datev_auto_tax)) {
			if (row.custom_item_tax_template) {
				frappe.model.set_value(row.doctype, row.name, "custom_item_tax_template", "");
			}
			if (row.custom_bu_schlussel) {
				frappe.model.set_value(row.doctype, row.name, "custom_bu_schlussel", "");
			}
		}

		if (is_tax && row.custom_bu_schlussel) {
			frappe.model.set_value(row.doctype, row.name, "custom_bu_schlussel", "");
		}
		if (is_tax && !cint(row.custom_datev_auto_tax) && row.custom_item_tax_template) {
			frappe.model.set_value(row.doctype, row.name, "custom_item_tax_template", "");
		}
	},

	lock_auto_tax_row(frm, row) {
		["account", "debit_in_account_currency", "credit_in_account_currency", "party_type", "party"].forEach(
			(fieldname) => {
				frm.set_df_property(fieldname, "read_only", 1, frm.doc.name, "accounts", row.name);
			}
		);
	},

	on_account_change(frm, row) {
		this.ensure_account_type(row.account, () => {
			this.toggle_datev_fields(frm, row);
			this.maybe_sync_tax_lines(frm, row);
		});
	},

	on_tax_template_change(frm, row) {
		this.ensure_account_type(row.account, () => {
			if (this.is_tax_account(row.account) || this.is_party_account(row.account)) {
				frappe.model.set_value(row.doctype, row.name, "custom_item_tax_template", "");
				frappe.model.set_value(row.doctype, row.name, "custom_bu_schlussel", "");
				frappe.msgprint(__("Item Tax Template can only be set on revenue/expense lines."));
				return;
			}

			if (!this.has_party_direction(frm)) {
				frappe.show_alert({
					message: __(
						"Set a Customer or Supplier party row first so DATEV can determine sales vs purchase."
					),
					indicator: "orange",
				});
			}

			if (!row.custom_item_tax_template) {
				frappe.model.set_value(row.doctype, row.name, "custom_bu_schlussel", "");
				this.sync_tax_lines(frm);
				return;
			}

			frappe.call({
				method: "gaertnerei_berger.gb_datev.journal_entry.get_item_tax_template_details",
				args: {
					template: row.custom_item_tax_template,
					company: frm.doc.company,
				},
				callback: (response) => {
					const details = response.message;
					if (!details) {
						frappe.msgprint(__("Invalid Item Tax Template for this company."));
						return;
					}
					if (cint(details.tax_detail_count) !== 1) {
						frappe.msgprint({
							message: __(
								"Item Tax Template has {0} tax rows; DATEV export is best-effort and may be wrong. Prefer a single-rate template.",
								[details.tax_detail_count]
							),
							indicator: "orange",
						});
					}
					frappe.model.set_value(
						row.doctype,
						row.name,
						"custom_bu_schlussel",
						details.bu_schluessel || ""
					);
					this.sync_tax_lines(frm);
				},
			});
		});
	},

	maybe_sync_tax_lines(frm, row) {
		if (!row || cint(row.custom_datev_auto_tax)) {
			return;
		}
		if (!row.custom_item_tax_template) {
			return;
		}
		this.sync_tax_lines(frm);
	},

	sync_tax_lines(frm) {
		if (this._sync_timeout) {
			clearTimeout(this._sync_timeout);
		}

		this._sync_timeout = setTimeout(() => {
			frappe.call({
				method: "gaertnerei_berger.gb_datev.journal_entry.sync_journal_entry_datev_tax_lines",
				args: { doc: frm.doc },
				freeze: false,
				callback: (response) => {
					const message = response.message || {};
					const accounts = message.accounts || [];
					if (!accounts.length) {
						this.update_preview_indicator(frm, message.preview);
						return;
					}

					frm.clear_table("accounts");
					accounts.forEach((row) => {
						const child = frm.add_child("accounts");
						Object.keys(row).forEach((key) => {
							if (
								!["name", "idx", "parent", "parenttype", "parentfield", "doctype"].includes(
									key
								)
							) {
								child[key] = row[key];
							}
						});
					});
					frm.refresh_field("accounts");
					this.refresh_datev_fields(frm);
					this.update_preview_indicator(frm, message.preview);
				},
			});
		}, 300);
	},

	clear_tax_row_datev_fields(frm) {
		(frm.doc.accounts || []).forEach((row) => {
			if (this.is_tax_account(row.account)) {
				row.custom_bu_schlussel = "";
				if (!cint(row.custom_datev_auto_tax)) {
					row.custom_item_tax_template = "";
				}
			}
		});
	},

	update_preview_indicator(frm, preview) {
		const apply = (data) => {
			frm.dashboard.clear_headline();
			if (!data) {
				return;
			}
			if (data.missing_bu && data.missing_bu.length) {
				frm.dashboard.set_headline_alert(
					__("DATEV: set Item Tax Template on business rows {0}", [data.missing_bu.join(", ")]),
					"red"
				);
			} else if (data.grouped) {
				const direction_label = data.party_account_type || data.direction || "";
				frm.dashboard.set_headline_alert(
					__("DATEV: will export {0} grouped row(s) ({1} mapping)", [
						data.rows,
						direction_label,
					]),
					"green"
				);
			} else if (data.direction) {
				frm.dashboard.set_headline_alert(
					__("DATEV ({0}): set Item Tax Template on revenue/expense lines to group export", [
						data.party_account_type || data.direction,
					]),
					"orange"
				);
			}
		};

		if (preview) {
			apply(preview);
			return;
		}

		frappe.call({
			method: "gaertnerei_berger.gb_datev.journal_entry.get_journal_entry_datev_preview",
			args: { doc: frm.doc },
			callback: (response) => apply(response.message),
		});
	},

	has_party_direction(frm) {
		return (frm.doc.accounts || []).some((row) => {
			const account_type = this.get_account_type(row.account);
			return (
				(account_type === "Receivable" && row.party_type === "Customer" && row.party) ||
				(account_type === "Payable" && row.party_type === "Supplier" && row.party)
			);
		});
	},

	is_tax_account(account) {
		return this.get_account_type(account) === "Tax";
	},

	is_party_account(account) {
		const account_type = this.get_account_type(account);
		return account_type === "Receivable" || account_type === "Payable";
	},

	get_account_type(account) {
		if (!account) {
			return "";
		}
		return this._account_type_cache[account] || "";
	},
};

frappe.ui.form.on("Journal Entry", {
	refresh(frm) {
		gaertnerei_berger.journal_entry.refresh_datev_fields(frm);
		gaertnerei_berger.journal_entry.update_preview_indicator(frm);
	},

	validate(frm) {
		gaertnerei_berger.journal_entry.clear_tax_row_datev_fields(frm);
	},
});

frappe.ui.form.on("Journal Entry Account", {
	account(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		gaertnerei_berger.journal_entry.on_account_change(frm, row);
	},

	custom_item_tax_template(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		gaertnerei_berger.journal_entry.on_tax_template_change(frm, row);
	},

	debit_in_account_currency(frm, cdt, cdn) {
		gaertnerei_berger.journal_entry.maybe_sync_tax_lines(frm, locals[cdt][cdn]);
	},

	credit_in_account_currency(frm, cdt, cdn) {
		gaertnerei_berger.journal_entry.maybe_sync_tax_lines(frm, locals[cdt][cdn]);
	},

	accounts_add(frm) {
		gaertnerei_berger.journal_entry.refresh_datev_fields(frm);
	},

	accounts_remove(frm) {
		gaertnerei_berger.journal_entry.sync_tax_lines(frm);
	},
});
