// Copyright (c) 2026, Gaertnerei Berger and contributors
// For license information, please see license.txt

// One-time Sales Invoice DATEV backfill (GitLab #96). This script only handles the look of
// the button; the "runs only once" rule is enforced on the server.

frappe.ui.form.on("Gaertnerei Berger Settings", {
	refresh(frm) {
		render_si_datev_backfill_info(frm);

		const done = frm.doc.si_datev_backfill_done;
		// Set the label through the field definition: the Button control rewrites its text
		// from df.label on every refresh, so a direct .text() change would not stick.
		frm.set_df_property(
			"run_si_datev_backfill",
			"label",
			done
				? __("Already executed (one-time operation)")
				: __("Run once: Fill DATEV fields on Sales Invoices")
		);

		const $button = frm.get_field("run_si_datev_backfill").$input;
		if ($button) {
			$button
				.prop("disabled", !!done)
				.toggleClass("btn-warning", !done)
				.toggleClass("btn-default", !!done);
		}

		if (done) {
			frm.dashboard.set_headline_alert(
				__(
					"Sales Invoice DATEV backfill was executed on {0} by {1}. This operation cannot be run again.",
					[
						frappe.datetime.str_to_user(frm.doc.si_datev_backfill_on),
						frappe.utils.escape_html(frm.doc.si_datev_backfill_by || ""),
					]
				),
				"green"
			);
		} else {
			frm.dashboard.set_headline_alert(
				__("One-time operation pending: DATEV fields on Sales Invoices have not been filled yet."),
				"orange"
			);
		}
	},

	run_si_datev_backfill(frm) {
		if (frm.doc.si_datev_backfill_done) return;

		frappe.confirm(
			__(
				"<p><b>This is a one-time operation.</b> It can be executed only once and cannot be undone.</p><p>It fills empty DATEV fields (Account No, BU-Schlüssel) on all Sales Invoices. Existing values are kept. No timestamps, amounts, taxes or GL entries are changed.</p><p>Do you want to run it now?</p>"
			),
			() => {
				frappe.call({
					method: "gaertnerei_berger.gaertnerei_berger.doctype.gaertnerei_berger_settings.gaertnerei_berger_settings.run_sales_invoice_datev_backfill",
					freeze: true,
					freeze_message: __("Filling DATEV fields on Sales Invoices..."),
					callback(r) {
						const lines = Object.entries(r.message || {}).map(
							([label, count]) => `${__(label)}: <b>${cint(count)}</b>`
						);
						frappe.msgprint({
							title: __("DATEV fields filled"),
							indicator: "green",
							message: lines.join("<br>"),
						});
						frm.reload_doc();
					},
				});
			}
		);
	},
});

// Rendered here instead of in the HTML field's options, because Frappe does not translate
// static HTML field content.
function render_si_datev_backfill_info(frm) {
	frm.get_field("si_datev_backfill_info").$wrapper.html(`
		<div class="text-muted small">
			<p><b>${__("Fill DATEV fields on Sales Invoices")}</b></p>
			<p>${__(
				"Fills the empty DATEV fields of all existing Sales Invoices from their current sources: Account No (from Debit To), item Account No (from Income Account) and item BU-Schlüssel (from Item Tax Template)."
			)}</p>
			<ul>
				<li>${__("This is a one-time operation. It can be executed only once and cannot be undone.")}</li>
				<li>${__("Only empty fields are filled. Existing values are kept.")}</li>
				<li>${__("No timestamps, amounts, taxes or GL entries are changed.")}</li>
			</ul>
		</div>
	`);
}
