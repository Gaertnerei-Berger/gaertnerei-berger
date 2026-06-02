app_name = "gaertnerei_berger"
app_title = "Gaertnerei Berger"
app_publisher = "Gaertnerei Berger"
app_description = "DATEV integration for ERPNext"
required_apps = ["frappe/erpnext"]
app_icon = "octicon octicon-file-directory"
app_color = "grey"
app_email = "info@gaertnerei-berger.de"
app_license = "GPLv3"

fixtures = [
	{
		"dt": "Custom Field",
		"filters": [
			[
				"name",
				"in",
				[
					"Item Tax Template-custom_datev_section",
					"Item Tax Template-custom_bu_schlussel",
					"Journal Entry Account-custom_datev_section",
					"Journal Entry Account-custom_datev_account_no",
					"Journal Entry Account-custom_datev_code",
					"Party Account-debtor_creditor_number",
					"Payment Entry-custom_datev_section",
					"Payment Entry-custom_datev_account_no",
					"Payment Entry-custom_datev_against_account_no",
					"Payment Entry-custom_datev_end_section",
					"Purchase Invoice-custom_datev_section",
					"Purchase Invoice-custom_datev_account_no",
					"Purchase Invoice-custom_datev_end_section",
					"Purchase Invoice Item-datev_settings_section",
					"Purchase Invoice Item-custom_datev_account_no",
					"Purchase Invoice Item-custom_bu_schlussel",
					"Purchase Invoice Item-datev_settings_end_section",
					"Sales Invoice-custom_datev_section",
					"Sales Invoice-custom_datev_account_no",
					"Sales Invoice-custom_datev_end_section",
					"Sales Invoice Item-datev_settings_section",
					"Sales Invoice Item-custom_datev_account_no",
					"Sales Invoice Item-custom_bu_schlussel",
					"Sales Invoice Item-datev_settings_end_section",
				],
			]
		],
	}
]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/gaertnerei_berger/css/gaertnerei_berger.css"
# app_include_js = "/assets/gaertnerei_berger/js/gaertnerei_berger.js"

# include js, css files in header of web template
# web_include_css = "/assets/gaertnerei_berger/css/gaertnerei_berger.css"
# web_include_js = "/assets/gaertnerei_berger/js/gaertnerei_berger.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "gaertnerei_berger/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# "Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# "methods": "gaertnerei_berger.utils.jinja_methods",
# "filters": "gaertnerei_berger.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "gaertnerei_berger.install.before_install"
# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "gaertnerei_berger.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# "Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# "Event": "frappe.desk.doctype.event.event.has_permission",
# }

# DocType Class
# ---------------
# Override standard doctype classes

# override_doctype_class = {
# "ToDo": "custom_app.overrides.CustomToDo"
# }

# Document Events
# ---------------
# Hook on document methods and events

doc_events = {
	"*": {
		"on_submit": "gaertnerei_berger.gb_datev.doctype.datev_unternehmen_online_settings.datev_unternehmen_online_settings.send",
	},
}

# Scheduled Tasks
# ---------------

# scheduler_events = {
# "all": [
# "gaertnerei_berger.tasks.all"
# ],
# "daily": [
# "gaertnerei_berger.tasks.daily"
# ],
# "hourly": [
# "gaertnerei_berger.tasks.hourly"
# ],
# "weekly": [
# "gaertnerei_berger.tasks.weekly"
# ],
# "monthly": [
# "gaertnerei_berger.tasks.monthly"
# ],
# }

# Testing
# -------

# before_tests = "gaertnerei_berger.install.before_tests"

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# "frappe.desk.doctype.event.event.get_events": "gaertnerei_berger.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# "Task": "gaertnerei_berger.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]


# User Data Protection
# --------------------

# user_data_fields = [
# {
# "doctype": "{doctype_1}",
# "filter_by": "{filter_by}",
# "redact_fields": ["{field_1}", "{field_2}"],
# "partial": 1,
# },
# {
# "doctype": "{doctype_2}",
# "filter_by": "{filter_by}",
# "partial": 1,
# },
# {
# "doctype": "{doctype_3}",
# "strict": False,
# },
# {
# "doctype": "{doctype_4}"
# }
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# "gaertnerei_berger.auth.validate"# ]
