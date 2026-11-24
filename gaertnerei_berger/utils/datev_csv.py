import datetime
import re
import unicodedata
import zipfile
from csv import QUOTE_NONNUMERIC
from decimal import ROUND_HALF_UP, Decimal
from io import BytesIO

import frappe
import pandas as pd
from frappe import _

from .datev_constants import DataCategory

UMSATZ_COLUMN = "Umsatz (ohne Soll/Haben-Kz)"

# DATEV reads ISO-8859-1 / Windows CodePage 1252. Only cp1252 has the € sign;
# latin_1 would turn it into "?".
DATEV_ENCODING = "cp1252"

# Digits-only Buchungsstapel fields that DATEV wants as unquoted numbers.
# Belegdatum (#10) and Fälligkeit (#117) get the same treatment after formatting.
UNQUOTED_ACCOUNT_COLUMNS = ("Konto", "Gegenkonto (ohne BU-Schlüssel)")

# Debitoren/Kreditoren and Kontenbeschriftungen: Konto #1 is an unquoted number too.
STAMMDATEN_CATEGORIES = (DataCategory.DEBTORS_CREDITORS, DataCategory.ACCOUNT_NAMES)

# Debitoren/Kreditoren #18 and #156 allow digits only: "[\d]{0,10}".
POSTCODE_COLUMNS = ("Postleitzahl", "Postleitzahl (Rechnungsadresse)")

# Header #9 "Exportiert von" allows "\w{0,25}" (ASCII letters, digits, underscore).
EXPORTED_BY_MAX_LENGTH = 25
UMLAUTS = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue", "ß": "ss"})


class DatevAmount(Decimal):
	"""Amount that renders with two decimals and a DATEV decimal separator.

	It stays a number, so QUOTE_NONNUMERIC leaves it unquoted like DATEV expects.
	"""

	separator = ","

	def __str__(self):
		return f"{self:.2f}".replace(".", self.separator)


class DatevNumber(str):
	"""Digits-only text (account number, TTMM date) that is written without quotes.

	The csv module's QUOTE_NONNUMERIC leaves a field unquoted when it supports
	float(). Keeping it a str keeps leading zeros, e.g. SKR04 account 0135 or the
	Belegdatum 0108.
	"""

	def __float__(self):
		return float(str.__str__(self) or 0)


def as_datev_number(value):
	"""Return value as DatevNumber; empty values become an empty, unquoted field."""
	if value is None or (not isinstance(value, str) and pd.isna(value)):
		return DatevNumber("")

	if isinstance(value, float) and value.is_integer():
		value = int(value)

	return DatevNumber(str(value).strip())


def clean_datev_user_name(name):
	"""Turn a user's name into a valid header #9 "Exportiert von" ("\\w{0,25}").

	"René Müller" -> "Rene_Mueller", "max.mustermann@example.com" -> "max_mustermann".
	"""
	name = (name or "").split("@")[0].translate(UMLAUTS)
	name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
	name = re.sub(r"[^A-Za-z0-9_]+", "_", name).strip("_")
	return name[:EXPORTED_BY_MAX_LENGTH].rstrip("_")


def cut_text(value, max_length):
	"""Cut a text to DATEV's max. field length (GitLab #113); other values stay as they are."""
	if isinstance(value, str) and len(value) > max_length:
		return value[:max_length].rstrip()
	return value


def clean_postcode(value):
	"""Keep only the digits of a Postleitzahl: "D-64760" -> "64760" (GitLab #116).

	DATEV allows digits only. Non-text values (empty cells) stay as they are.
	"""
	if isinstance(value, str):
		return re.sub(r"[^0-9]", "", value)
	return value


def format_datev_amount(value, separator=","):
	"""Return Umsatz as DatevAmount (e.g. 100,00) for Decimal, float, int or str input."""
	if value is None or (isinstance(value, str) and not value.strip()) or pd.isna(value):
		return value

	amount = DatevAmount(Decimal(str(value).strip()).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
	amount.separator = separator
	return amount


def get_datev_csv(data, filters, csv_class):
	"""
	Fill in missing columns and return a CSV in DATEV Format.

	For automatic processing, DATEV requires the first line of the CSV file to
	hold meta data such as the length of account numbers oder the category of
	the data.

	Arguments:
	data -- array of dictionaries
	filters -- dict
	csv_class -- defines DATA_CATEGORY, FORMAT_NAME and COLUMNS
	"""
	empty_df = pd.DataFrame(columns=csv_class.COLUMNS)
	data_df = pd.DataFrame.from_records(data)
	result = pd.concat([empty_df, data_df], ignore_index=True)

	if csv_class.DATA_CATEGORY == DataCategory.DEBTORS_CREDITORS:
		# Before the length cut, so "D-64760" keeps all five digits (GitLab #116)
		for column in POSTCODE_COLUMNS:
			result[column] = result[column].map(clean_postcode)

	for column, max_length in getattr(csv_class, "MAX_LENGTHS", {}).items():
		result[column] = result[column].map(lambda value, n=max_length: cut_text(value, n))

	if csv_class.DATA_CATEGORY == DataCategory.TRANSACTIONS:
		result["Belegdatum"] = pd.to_datetime(result["Belegdatum"])

		result["Beleginfo - Inhalt 6"] = pd.to_datetime(result["Beleginfo - Inhalt 6"])
		result["Beleginfo - Inhalt 6"] = result["Beleginfo - Inhalt 6"].dt.strftime("%d%m%Y")

		result["Fälligkeit"] = pd.to_datetime(result["Fälligkeit"])
		result["Fälligkeit"] = result["Fälligkeit"].dt.strftime("%d%m%Y").map(as_datev_number)

		result = result.sort_values(by="Belegdatum", kind="stable", ignore_index=True)

		# Format after sorting: TTMM as text would sort by day, not by date.
		result["Belegdatum"] = result["Belegdatum"].dt.strftime("%d%m").map(as_datev_number)
		for column in UNQUOTED_ACCOUNT_COLUMNS:
			result[column] = result[column].map(as_datev_number).astype(object)

		# pandas applies `decimal` to float columns only; grouped rows carry Decimal or str.
		separator = filters.get("umsatz_decimal_separator") or ","
		result[UMSATZ_COLUMN] = (
			result[UMSATZ_COLUMN].map(lambda value: format_datev_amount(value, separator)).astype(object)
		)

	if csv_class.DATA_CATEGORY == DataCategory.ACCOUNT_NAMES:
		result["Sprach-ID"] = "de-DE"

	if csv_class.DATA_CATEGORY in STAMMDATEN_CATEGORIES:
		# Konto #1 is digits only, written without quotes (GitLab #116)
		result["Konto"] = result["Konto"].map(as_datev_number).astype(object)

	data = result.to_csv(
		# Reason for str(';'): https://github.com/pandas-dev/pandas/issues/6035
		sep=";",
		# Decimal separator for Umsatz and other numeric columns (DATEV Settings)
		decimal=filters.get("umsatz_decimal_separator") or ",",
		# format any other date column as DDMM
		date_format="%d%m",
		# Windows line terminator
		lineterminator="\r\n",
		# Do not number rows
		index=False,
		# Use all columns defined above
		columns=csv_class.COLUMNS,
		# Quote text fields. Numbers (DatevAmount, DatevNumber) stay unquoted.
		quoting=QUOTE_NONNUMERIC,
	)

	data = data.encode(DATEV_ENCODING, errors="replace")

	header = get_header(filters, csv_class)
	header = ";".join(header).encode(DATEV_ENCODING, errors="replace")

	# 1st Row: Header with meta data
	# 2nd Row: Data heading (Überschrift der Nutzdaten), included in `data` here.
	# 3rd - nth Row: Data (Nutzdaten)
	return header + b"\r\n" + data


def get_header(filters, csv_class):
	description = filters.get("voucher_type", csv_class.FORMAT_NAME)
	company = filters.get("company")
	datev_settings = frappe.get_doc("DATEV Settings", {"client": company})
	default_currency = frappe.get_value("Company", company, "default_currency")
	coa = frappe.get_value("Company", company, "chart_of_accounts")
	coa_short_code = "04" if "SKR04" in coa else ("03" if "SKR03" in coa else "")

	header = [
		# DATEV format
		# "DTVF" = created by DATEV software,
		# "EXTF" = created by other software
		'"EXTF"',
		# version of the DATEV format
		# 141 = 1.41,
		# 510 = 5.10,
		# 720 = 7.20
		"700",
		csv_class.DATA_CATEGORY,
		f'"{csv_class.FORMAT_NAME}"',
		# Format version (regarding format name)
		csv_class.FORMAT_VERSION,
		# Generated on
		datetime.datetime.now().strftime("%Y%m%d%H%M%S") + "000",
		# Imported on -- stays empty
		"",
		# Origin. Any two symbols, will be replaced by "SV" on import.
		'"EN"',
		# I = Exported by: "\w{0,25}", so a cleaned name, never the e-mail address
		f'"{clean_datev_user_name(frappe.utils.get_fullname(frappe.session.user))}"',
		# J = Imported by -- stays empty
		"",
		# K = Tax consultant number (Beraternummer)
		datev_settings.get("consultant_number", "0000000"),
		# L = Tax client number (Mandantennummer)
		datev_settings.get("client_number", "00000"),
		# M = Start of the fiscal year (Wirtschaftsjahresbeginn)
		frappe.utils.formatdate(filters.get("fiscal_year_start"), "yyyyMMdd"),
		# N = Length of account numbers (Sachkontenlänge)
		str(filters.get("account_number_length", 4)),
		# O = Transaction batch start date (YYYYMMDD)
		frappe.utils.formatdate(filters.get("from_date"), "yyyyMMdd")
		if csv_class.DATA_CATEGORY == DataCategory.TRANSACTIONS
		else "",
		# P = Transaction batch end date (YYYYMMDD)
		frappe.utils.formatdate(filters.get("to_date"), "yyyyMMdd")
		if csv_class.DATA_CATEGORY == DataCategory.TRANSACTIONS
		else "",
		# Q = Description (for example, "Sales Invoice") Max. 30 chars
		'"{}"'.format(_(description)) if csv_class.DATA_CATEGORY == DataCategory.TRANSACTIONS else "",
		# R = Diktatkürzel
		"",
		# S = Buchungstyp
		# 1 = Transaction batch (Finanzbuchführung),
		# 2 = Annual financial statement (Jahresabschluss)
		"1" if csv_class.DATA_CATEGORY == DataCategory.TRANSACTIONS else "",
		# T = Rechnungslegungszweck
		# 0 oder leer = vom Rechnungslegungszweck unabhängig
		# 50 = Handelsrecht
		# 30 = Steuerrecht
		# 64 = IFRS
		# 40 = Kalkulatorik
		# 11 = Reserviert
		# 12 = Reserviert
		"0" if csv_class.DATA_CATEGORY == DataCategory.TRANSACTIONS else "",
		# U = Festschreibung
		# TODO: Filter by Accounting Period. In export for closed Accounting Period, this will be "1"
		"0",
		# V = Default currency, for example, "EUR"
		f'"{default_currency}"' if csv_class.DATA_CATEGORY == DataCategory.TRANSACTIONS else "",
		# reserviert
		"",
		# Derivatskennzeichen
		"",
		# reserviert
		"",
		# reserviert
		"",
		# SKR
		f'"{coa_short_code}"',
		# Branchen-Lösungs-ID
		"",
		# reserviert
		"",
		# reserviert
		"",
		# Anwendungsinformation (Verarbeitungskennzeichen der abgebenden Anwendung)
		"",
	]
	return header


def zip_and_download(zip_filename, csv_files):
	"""
	Put CSV files in a zip archive and send that to the client.

	Params:
	zip_filename	Name of the zip file
	csv_files		list of dicts [{'file_name': 'my_file.csv', 'csv_data': 'comma,separated,values'}]
	"""
	frappe.response["filecontent"] = build_datev_zip_bytes(csv_files)
	frappe.response["filename"] = zip_filename
	frappe.response["type"] = "binary"


def build_datev_zip_bytes(csv_files):
	zip_buffer = BytesIO()

	zip_file = zipfile.ZipFile(zip_buffer, mode="w", compression=zipfile.ZIP_DEFLATED)
	for csv_file in csv_files:
		zip_file.writestr(csv_file.get("file_name"), csv_file.get("csv_data"))

	zip_file.close()
	return zip_buffer.getvalue()
