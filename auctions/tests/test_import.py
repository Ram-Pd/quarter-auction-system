from decimal import Decimal
from io import BytesIO
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from openpyxl import Workbook

from auctions.importers import EXPECTED_HEADERS, import_quarters
from auctions.models import Quarter

SAMPLES = Path(settings.BASE_DIR) / "sample_data"
GOOD_ROW = ["B-214", "Sector 4", "Near market", "Type B", "2nd", 750, 4500, "Vacant"]


def xlsx(rows, headers=EXPECTED_HEADERS):
    """Build an in-memory .xlsx file from a list of rows."""
    wb = Workbook()
    ws = wb.active
    if headers is not None:
        ws.append(headers)
    for row in rows:
        ws.append(row)
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def messages(result):
    return [str(e) for e in result.errors]


class SampleFileTests(TestCase):
    """The three files in sample_data/ behave as documented."""

    def test_valid_sample_imports_all_eight(self):
        result = import_quarters(SAMPLES / "quarters_sample.xlsx")
        self.assertEqual(messages(result), [])
        self.assertEqual(result.created, 8)
        self.assertEqual(Quarter.objects.count(), 8)
        q = Quarter.objects.get(quarter_no="A-021")
        self.assertEqual(q.quarter_type, "A")
        self.assertEqual(q.floor, "Ground")
        self.assertEqual(q.area_sqft, Decimal("980"))
        self.assertEqual(q.base_rate, Decimal("6200"))
        self.assertEqual(q.status, Quarter.Status.VACANT)

    def test_invalid_sample_reports_all_four_errors_and_saves_nothing(self):
        result = import_quarters(SAMPLES / "quarters_invalid.xlsx")
        found = {(e.row, e.column) for e in result.errors}
        self.assertEqual(found, {
            (3, "Quarter No"),        # duplicate B-214
            (4, "Area (sq ft)"),      # "abc"
            (5, "Base Rate (Rs.)"),   # -2400
            (6, "Quarter No"),        # missing
        })
        self.assertEqual(result.created, 0)
        self.assertEqual(Quarter.objects.count(), 0)  # row 2 was valid but NOT saved

    def test_bad_header_sample_is_rejected(self):
        result = import_quarters(SAMPLES / "quarters_bad_header.xlsx")
        self.assertEqual(len(result.errors), 1)
        self.assertEqual(result.errors[0].row, 1)
        self.assertIn("expected header 'Quarter No', found 'Quarter Number'", result.errors[0].message)
        self.assertEqual(Quarter.objects.count(), 0)

    def test_importing_same_file_twice_rejects_all_as_existing(self):
        import_quarters(SAMPLES / "quarters_sample.xlsx")
        result = import_quarters(SAMPLES / "quarters_sample.xlsx")
        self.assertEqual(len(result.errors), 8)
        self.assertTrue(all("already exists in the database" in m for m in messages(result)))
        self.assertEqual(Quarter.objects.count(), 8)


class ValidationRuleTests(TestCase):
    def test_duplicate_against_database_case_insensitive(self):
        import_quarters(xlsx([GOOD_ROW]))
        result = import_quarters(xlsx([["b-214"] + GOOD_ROW[1:]]))
        self.assertEqual(messages(result), ["Row 2, Quarter No: 'B-214' already exists in the database."])

    def test_whitespace_commas_blank_rows_and_type_spelling(self):
        rows = [
            ["  c-305 ", "  Sector   2 ", "Opposite park", "type c", "3rd", "620", "4,500", " vacant "],
            [None] * 8,                     # blank row
            ["", "  ", None, "", "", "", "", ""],  # whitespace-only row
            ["D-407", "Sector 9", "Near school", "D", "4th", 480.5, "2,400.75", ""],  # blank status ok
        ]
        result = import_quarters(xlsx(rows))
        self.assertEqual(messages(result), [])
        self.assertEqual(result.created, 2)
        c = Quarter.objects.get(quarter_no="C-305")
        self.assertEqual(c.sector, "Sector 2")
        self.assertEqual(c.quarter_type, "C")
        self.assertEqual(c.base_rate, Decimal("4500"))
        d = Quarter.objects.get(quarter_no="D-407")
        self.assertEqual(d.area_sqft, Decimal("480.5"))
        self.assertEqual(d.base_rate, Decimal("2400.75"))

    def test_numeric_quarter_no_stored_as_text(self):
        result = import_quarters(xlsx([[214] + GOOD_ROW[1:]]))
        self.assertTrue(result.ok)
        self.assertTrue(Quarter.objects.filter(quarter_no="214").exists())

    def test_every_error_in_a_row_is_reported(self):
        result = import_quarters(xlsx([["", "", "", "Type Z", "", "x", 0, "Allotted"]]))
        self.assertEqual(
            [e.column for e in result.errors],
            ["Quarter No", "Sector", "Location / Block", "Floor", "Type",
             "Area (sq ft)", "Base Rate (Rs.)", "Status"],
        )

    def test_row_with_other_errors_still_checked_for_duplicates(self):
        rows = [GOOD_ROW, ["B-214", "Sector 4", "Near market", "Type B", "2nd", "abc", 4500, "Vacant"]]
        result = import_quarters(xlsx(rows))
        self.assertEqual({(e.row, e.column) for e in result.errors},
                         {(3, "Area (sq ft)"), (3, "Quarter No")})

    def test_too_many_decimal_places_and_too_large(self):
        result = import_quarters(xlsx([
            ["X-1"] + GOOD_ROW[1:5] + ["750.123", 4500, "Vacant"],
            ["X-2"] + GOOD_ROW[1:5] + [750, "99999999999", "Vacant"],
        ]))
        self.assertEqual(messages(result), [
            "Row 2, Area (sq ft): can have at most 2 decimal places",
            "Row 3, Base Rate (Rs.): is too large",
        ])

    def test_missing_extra_and_misordered_headers(self):
        headers = ["Sector", "Quarter No"] + EXPECTED_HEADERS[2:7] + [None, "Notes"]
        result = import_quarters(xlsx([], headers=headers))
        self.assertEqual(messages(result), [
            "Row 1, Column A: expected header 'Quarter No', found 'Sector'",
            "Row 1, Column B: expected header 'Sector', found 'Quarter No'",
            "Row 1, Column H: missing header 'Status'",
            "Row 1, Column I: unexpected extra column 'Notes'",
        ])

    def test_header_only_file(self):
        self.assertEqual(messages(import_quarters(xlsx([]))),
                         ["The file has a header but no data rows."])

    def test_empty_sheet(self):
        self.assertEqual(messages(import_quarters(xlsx([], headers=None))), ["The sheet is empty."])

    def test_not_an_excel_file(self):
        result = import_quarters(BytesIO(b"this is not a spreadsheet"))
        self.assertEqual(messages(result), ["File is not a valid .xlsx Excel workbook."])


class ImportAdminPageTests(TestCase):
    def setUp(self):
        self.url = reverse("admin:auctions_quarter_import")
        self.admin = User.objects.create_superuser("admin", "admin@example.com", "pass")

    def upload(self, path_or_bytes, name="quarters.xlsx", **kwargs):
        data = path_or_bytes.read_bytes() if isinstance(path_or_bytes, Path) else path_or_bytes
        return self.client.post(self.url, {"file": SimpleUploadedFile(name, data)}, **kwargs)

    def test_requires_login(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login/", response["Location"])

    def test_staff_without_add_permission_is_forbidden(self):
        staff = User.objects.create_user("viewer", password="pass", is_staff=True)
        self.client.force_login(staff)
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_changelist_has_import_button(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("admin:auctions_quarter_changelist"))
        self.assertContains(response, "Import from Excel")
        self.assertContains(response, self.url)

    def test_successful_upload_redirects_with_message(self):
        self.client.force_login(self.admin)
        response = self.upload(SAMPLES / "quarters_sample.xlsx", follow=True)
        self.assertRedirects(response, reverse("admin:auctions_quarter_changelist"))
        self.assertContains(response, "Imported 8 quarter(s) successfully.")
        self.assertEqual(Quarter.objects.count(), 8)

    def test_invalid_upload_shows_error_table(self):
        self.client.force_login(self.admin)
        response = self.upload(SAMPLES / "quarters_invalid.xlsx")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Nothing was imported. The file has 4 errors.")
        self.assertContains(response, "must be a number (got &#x27;abc&#x27;)")
        self.assertEqual(Quarter.objects.count(), 0)

    def test_wrong_extension_rejected(self):
        self.client.force_login(self.admin)
        response = self.upload(b"a,b,c", name="quarters.csv")
        self.assertContains(response, "File extension")
        self.assertEqual(Quarter.objects.count(), 0)
