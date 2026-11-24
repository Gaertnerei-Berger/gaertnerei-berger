# Copyright (c) 2026, Gaertnerei Berger and contributors
# For license information, please see license.txt

"""File-format checks for the EXTF writer against the DATEV-Format spec (#112)."""

import csv
import io
import re
from csv import QUOTE_NONNUMERIC
from unittest import TestCase
from unittest.mock import patch

import frappe

from gaertnerei_berger.utils.datev_constants import AccountNames, DebtorsCreditors, Transactions
from gaertnerei_berger.utils.datev_csv import (
	DatevNumber,
	clean_datev_user_name,
	get_datev_csv,
	get_header,
)

# Header #9 "Exportiert von" per DATEV spec; \w is ASCII only there.
EXPORTED_BY_RE = re.compile(r'"\w{0,25}"', re.ASCII)

SPEC_FIELDS_121_TO_125 = [
	"Abrechnungsreferenz",
	"BVV-Position",
	"EU-Land u. UStID (Ursprung)",
	"EU-Steuersatz (Ursprung)",
	"Abw. Skontokonto",
]


def split_fields(line):
	"""Split one EXTF line on ';' outside quotes and keep the quotes."""
	fields, buffer, in_quotes = [], "", False
	for char in line:
		if char == '"':
			in_quotes = not in_quotes
		if char == ";" and not in_quotes:
			fields.append(buffer)
			buffer = ""
		else:
			buffer += char
	fields.append(buffer)
	return fields


def render_transactions(rows):
	with patch("gaertnerei_berger.utils.datev_csv.get_header", return_value=['"EXTF"']):
		return get_datev_csv(data=rows, filters={"umsatz_decimal_separator": ","}, csv_class=Transactions)


def data_lines(csv_bytes):
	"""Data rows (line 3 onwards) as lists of raw fields."""
	lines = csv_bytes.decode("cp1252").split("\r\n")[2:]
	return [split_fields(line) for line in lines if line]


def booking(**values):
	row = {
		"Umsatz (ohne Soll/Haben-Kz)": "119.00",
		"Soll/Haben-Kennzeichen": "S",
		"Konto": "10307",
		"Gegenkonto (ohne BU-Schlüssel)": "4400",
		"Belegdatum": "2026-08-01",
		"Belegfeld 1": "ACC-SINV-2026-00001",
		"Buchungstext": "Pflanzen",
	}
	row.update(values)
	return row


def column(name):
	return Transactions.COLUMNS.index(name)


class TestExportedBy(TestCase):
	"""Item 1: header #9 must match "\\w{0,25}", so no e-mail address."""

	def test_email_address_becomes_local_part(self):
		self.assertEqual(clean_datev_user_name("max.mustermann@example.com"), "max_mustermann")

	def test_umlauts_and_accents_are_transliterated(self):
		self.assertEqual(clean_datev_user_name("René Müller-Größ"), "Rene_Mueller_Groess")

	def test_name_is_cut_to_25_characters(self):
		cleaned = clean_datev_user_name("Maximilian Alexander Mustermann-Schmidt")
		self.assertLessEqual(len(cleaned), 25)
		self.assertRegex(f'"{cleaned}"', EXPORTED_BY_RE)
		self.assertFalse(cleaned.endswith("_"))

	def test_empty_name_stays_empty(self):
		self.assertEqual(clean_datev_user_name(None), "")
		self.assertEqual(clean_datev_user_name("@example.com"), "")

	def test_header_writes_cleaned_full_name(self):
		header = self._header(Transactions, full_name="Jürgen Gärtner")
		self.assertEqual(header[8], '"Juergen_Gaertner"')

	def test_header_never_writes_the_email_address(self):
		header = self._header(Transactions, full_name="jane.doe@example.com")
		self.assertRegex(header[8], EXPORTED_BY_RE)
		self.assertNotIn("@", header[8])

	def _header(self, csv_class, full_name):
		values = {"default_currency": "EUR", "chart_of_accounts": "SKR04 mit Kontonummern"}
		with (
			patch("gaertnerei_berger.utils.datev_csv.frappe.get_doc", return_value=frappe._dict()),
			patch(
				"gaertnerei_berger.utils.datev_csv.frappe.get_value",
				side_effect=lambda doctype, name, field: values[field],
			),
			patch("gaertnerei_berger.utils.datev_csv.frappe.utils.get_fullname", return_value=full_name),
		):
			return get_header(
				{
					"company": "_Test GmbH",
					"fiscal_year_start": "2026-01-01",
					"from_date": "2026-08-01",
					"to_date": "2026-08-31",
				},
				csv_class,
			)


class TestFormatVersion(TestCase):
	"""Item 2: Buchungsstapel format version 13 has 125 fields in spec order."""

	def test_buchungsstapel_is_version_13_with_125_columns(self):
		self.assertEqual(Transactions.FORMAT_VERSION, "13")
		self.assertEqual(len(Transactions.COLUMNS), 125)
		self.assertEqual(len(set(Transactions.COLUMNS)), 125)

	def test_fields_121_to_125_follow_land(self):
		self.assertEqual(Transactions.COLUMNS[119], "Land")
		self.assertEqual(Transactions.COLUMNS[120:], SPEC_FIELDS_121_TO_125)

	def test_every_line_has_125_fields(self):
		csv_bytes = render_transactions([booking(), booking(Konto="4400", Belegdatum="2026-08-02")])
		lines = csv_bytes.decode("cp1252").split("\r\n")
		self.assertEqual(len(split_fields(lines[1])), 125)
		for fields in data_lines(csv_bytes):
			self.assertEqual(len(fields), 125)

	def test_stammdaten_versions_unchanged(self):
		self.assertEqual(DebtorsCreditors.FORMAT_VERSION, "5")
		self.assertEqual(AccountNames.FORMAT_VERSION, "2")


class TestEncoding(TestCase):
	"""Item 3: files are cp1252, so € survives (latin_1 turned it into ?)."""

	def test_euro_sign_and_umlauts_are_cp1252(self):
		csv_bytes = render_transactions([booking(Buchungstext="Gebühr 5 €")])
		self.assertIn(b'"Geb\xfchr 5 \x80"', csv_bytes)

	def test_header_is_cp1252(self):
		with patch(
			"gaertnerei_berger.utils.datev_csv.get_header",
			return_value=['"EXTF"', '"Rechnungsausgang €"'],
		):
			csv_bytes = get_datev_csv(data=[booking()], filters={}, csv_class=Transactions)
		self.assertTrue(csv_bytes.startswith(b'"EXTF";"Rechnungsausgang \x80"\r\n'))

	def test_column_headings_keep_umlauts(self):
		self.assertIn('"Gegenkonto (ohne BU-Schlüssel)"'.encode("cp1252"), render_transactions([booking()]))


class TestNumericFieldsUnquoted(TestCase):
	"""Item 4: Konto, Gegenkonto, Belegdatum and Fälligkeit are unquoted numbers."""

	def test_konto_gegenkonto_belegdatum_faelligkeit_are_unquoted(self):
		(fields,) = data_lines(render_transactions([booking(**{"Fälligkeit": "2026-08-31"})]))
		self.assertEqual(fields[column("Konto")], "10307")
		self.assertEqual(fields[column("Gegenkonto (ohne BU-Schlüssel)")], "4400")
		self.assertEqual(fields[column("Belegdatum")], "0108")
		self.assertEqual(fields[column("Fälligkeit")], "31082026")

	def test_leading_zeros_are_kept(self):
		(fields,) = data_lines(render_transactions([booking(Konto="0135", Belegdatum="2026-02-03")]))
		self.assertEqual(fields[column("Konto")], "0135")
		self.assertEqual(fields[column("Belegdatum")], "0302")

	def test_integer_and_float_account_numbers(self):
		(fields,) = data_lines(
			render_transactions([booking(Konto=10307.0, **{"Gegenkonto (ohne BU-Schlüssel)": 4400})])
		)
		self.assertEqual(fields[column("Konto")], "10307")
		self.assertEqual(fields[column("Gegenkonto (ohne BU-Schlüssel)")], "4400")

	def test_missing_faelligkeit_is_an_empty_field(self):
		(fields,) = data_lines(render_transactions([booking()]))
		self.assertEqual(fields[column("Fälligkeit")], "")

	def test_text_fields_stay_quoted(self):
		(fields,) = data_lines(render_transactions([booking(**{"BU-Schlüssel": "80"})]))
		self.assertEqual(fields[column("Soll/Haben-Kennzeichen")], '"S"')
		self.assertEqual(fields[column("BU-Schlüssel")], '"80"')
		self.assertEqual(fields[column("Belegfeld 1")], '"ACC-SINV-2026-00001"')
		self.assertEqual(fields[column("Umsatz (ohne Soll/Haben-Kz)")], "119,00")

	def test_rows_still_sorted_by_date_not_by_ttmm_text(self):
		rows = [
			booking(Belegdatum="2026-09-01", **{"Belegfeld 1": "SEP"}),
			booking(Belegdatum="2026-08-15", **{"Belegfeld 1": "AUG"}),
		]
		lines = data_lines(render_transactions(rows))
		self.assertEqual([fields[column("Belegfeld 1")] for fields in lines], ['"AUG"', '"SEP"'])

	def test_datev_number_counts_as_number_for_csv_quoting(self):
		buffer = io.StringIO()
		csv.writer(buffer, delimiter=";", quoting=QUOTE_NONNUMERIC).writerow([DatevNumber("0135"), "text"])
		self.assertEqual(buffer.getvalue(), '0135;"text"\r\n')
		self.assertEqual(float(DatevNumber("0135")), 135.0)


def render_stammdaten(rows, csv_class):
	with patch("gaertnerei_berger.utils.datev_csv.get_header", return_value=['"EXTF"']):
		return get_datev_csv(data=rows, filters={}, csv_class=csv_class)


def stammdaten_field(csv_bytes, csv_class, name):
	return data_lines(csv_bytes)[0][csv_class.COLUMNS.index(name)]


class TestFieldLengths(TestCase):
	"""GitLab #113: DATEV warned REW00967 (too long) on names and Beleginfo - Art."""

	def test_beleginfo_art_is_cut_to_20(self):
		csv_bytes = render_transactions([booking(**{"Beleginfo - Art 5": "Lieferanten-Rechnungsnummer"})])
		self.assertEqual(data_lines(csv_bytes)[0][column("Beleginfo - Art 5")], '"Lieferanten-Rechnung"')

	def test_purchase_invoice_beleginfo_labels_fit(self):
		from gaertnerei_berger.gb_datev.report.datev.datev import get_purchase_invoice_params

		fields = get_purchase_invoice_params({})[0]
		for label in re.findall(r"'([^']+)' as 'Beleginfo - Art \d'", fields):
			self.assertLessEqual(len(label), 20, label)

	def test_buchungstext_is_cut_to_60(self):
		csv_bytes = render_transactions([booking(Buchungstext="x" * 70)])
		self.assertEqual(data_lines(csv_bytes)[0][column("Buchungstext")], '"{}"'.format("x" * 60))

	def test_short_text_stays_as_it_is(self):
		csv_bytes = render_transactions([booking(Buchungstext="Pflanzen")])
		self.assertEqual(data_lines(csv_bytes)[0][column("Buchungstext")], '"Pflanzen"')

	def test_debitor_names_are_cut(self):
		row = {
			"Konto": "10006",
			"Name (Adressatentyp Unternehmen)": "Förderverein Grundschule in der Stried und Umgebung e.V.",
			"Name (Adressatentyp natürl. Person)": "Rechtsanwältin und Notarin Christin Schulze",
			"Ort": "Erbach im Odenwald, Ortsteil Bullau-Ost",
		}
		csv_bytes = render_stammdaten([row], DebtorsCreditors)
		company = stammdaten_field(csv_bytes, DebtorsCreditors, "Name (Adressatentyp Unternehmen)")
		person = stammdaten_field(csv_bytes, DebtorsCreditors, "Name (Adressatentyp natürl. Person)")
		ort = stammdaten_field(csv_bytes, DebtorsCreditors, "Ort")
		self.assertEqual(len(company.strip('"')), 50)
		self.assertEqual(person, '"Rechtsanwältin und Notarin Chr"')
		self.assertLessEqual(len(ort.strip('"')), 30)

	def test_konto_is_never_cut(self):
		csv_bytes = render_stammdaten([{"Konto": "1009655", "Kontenbeschriftung": "x"}], AccountNames)
		self.assertEqual(stammdaten_field(csv_bytes, AccountNames, "Konto").strip('"'), "1009655")

	def test_max_length_columns_exist(self):
		for csv_class in (Transactions, DebtorsCreditors, AccountNames):
			self.assertLessEqual(set(csv_class.MAX_LENGTHS), set(csv_class.COLUMNS))


class TestPersonenkontoLabel(TestCase):
	"""GitLab #113: DATEV puts a Personenkonto's label into "Nachname" (30)."""

	def test_personenkonto_label_is_cut_to_30(self):
		from gaertnerei_berger.gb_datev.report.datev.datev import cut_personenkonto_label

		row = cut_personenkonto_label(
			{"Konto": "10006", "Kontenbeschriftung": "Förderverein Grundschule in der Stried"}, 4
		)
		self.assertEqual(row["Kontenbeschriftung"], "Förderverein Grundschule in de")

	def test_sachkonto_keeps_40(self):
		from gaertnerei_berger.gb_datev.report.datev.datev import cut_personenkonto_label

		label = "Erlöse 19 % USt Pflanzen und Gartenbedarf"[:40]
		row = cut_personenkonto_label({"Konto": "4400", "Kontenbeschriftung": label}, 4)
		self.assertEqual(row["Kontenbeschriftung"], label)

	def test_sachkontenlaenge_from_settings(self):
		from gaertnerei_berger.gb_datev.report.datev.datev import cut_personenkonto_label

		label = "x" * 40
		row = cut_personenkonto_label({"Konto": "10006", "Kontenbeschriftung": label}, 5)
		self.assertEqual(row["Kontenbeschriftung"], label)
