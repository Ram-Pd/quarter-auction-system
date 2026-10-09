"""
Excel import of quarters.

Two phases:
  1. Validate the header and EVERY row, collecting all errors (nothing saved).
  2. Only if there are zero errors, save all rows inside one transaction.
"""
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from zipfile import BadZipFile

from django.db import IntegrityError, transaction
from django.db.models.functions import Upper
from openpyxl import load_workbook

from .models import Quarter

EXPECTED_HEADERS = [
    "Quarter No", "Sector", "Location / Block", "Type",
    "Floor", "Area (sq ft)", "Base Rate (Rs.)", "Status",
]
MAX_DATA_ROWS = 2000  # protects the server from huge uploads

# Accepts "Type B", "type b", "B" -> "B"
TYPE_LOOKUP = {}
for _value, _label in Quarter.QuarterType.choices:
    TYPE_LOOKUP[_value.lower()] = _value
    TYPE_LOOKUP[_label.lower()] = _value


@dataclass
class RowError:
    row: int | None      # Excel row number (1 = header); None = whole-file problem
    column: str | None   # header name, e.g. "Area (sq ft)"
    message: str

    def __str__(self):
        where = []
        if self.row is not None:
            where.append(f"Row {self.row}")
        if self.column:
            where.append(self.column)
        return f"{', '.join(where)}: {self.message}" if where else self.message


@dataclass
class ImportResult:
    created: int = 0
    errors: list[RowError] = field(default_factory=list)

    @property
    def ok(self):
        return not self.errors


# ---------- cell helpers ----------

def _clean_text(value):
    """Cell -> stripped string ('' for blank). 214.0 -> '214'."""
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return " ".join(str(value).split())  # trims and collapses inner whitespace


def _parse_positive_decimal(value, max_digits, decimal_places=2):
    """Return (Decimal, None) or (None, error message)."""
    if isinstance(value, bool):  # True/False are ints in Python; reject them
        return None, "must be a number"
    if isinstance(value, (int, float)):
        text = str(value)
    else:
        text = _clean_text(value).replace(",", "")  # "4,500" -> "4500"
    if text == "":
        return None, "is required"
    try:
        number = Decimal(text)
    except InvalidOperation:
        return None, f"must be a number (got '{_clean_text(value)}')"
    if not number.is_finite():
        return None, "must be a number"
    if number <= 0:
        return None, f"must be greater than 0 (got {_clean_text(value)})"
    if -number.as_tuple().exponent > decimal_places:
        return None, f"can have at most {decimal_places} decimal places"
    if number >= Decimal(10) ** (max_digits - decimal_places):
        return None, "is too large"
    return number, None


# ---------- main entry point ----------

def import_quarters(uploaded_file) -> ImportResult:
    """Validate an .xlsx file and, if fully valid, create all quarters."""
    result = ImportResult()

    try:
        workbook = load_workbook(uploaded_file, read_only=True, data_only=True)
    except (BadZipFile, KeyError, OSError, ValueError):
        result.errors.append(RowError(None, None, "File is not a valid .xlsx Excel workbook."))
        return result

    try:
        sheet = workbook.worksheets[0]
        rows = sheet.iter_rows(values_only=True)

        # --- header ---
        header = next(rows, None)
        if header is None:
            result.errors.append(RowError(None, None, "The sheet is empty."))
            return result
        result.errors.extend(_check_header(header))
        if result.errors:
            return result  # columns can't be trusted, so don't read data rows

        # --- data rows ---
        quarters = []
        first_seen = {}  # quarter_no -> row where it first appeared
        data_rows = 0
        for row_no, cells in enumerate(rows, start=2):
            cells = list(cells) + [None] * (len(EXPECTED_HEADERS) - len(cells))
            if all(_clean_text(c) == "" for c in cells):
                continue  # skip blank rows
            data_rows += 1
            if data_rows > MAX_DATA_ROWS:
                result.errors.append(RowError(
                    None, None, f"Too many rows: the limit is {MAX_DATA_ROWS} quarters per file."))
                return result
            quarter_no, quarter, errors = _validate_row(row_no, cells[:len(EXPECTED_HEADERS)])
            result.errors.extend(errors)
            # Duplicate checks run even if other columns in this row had errors,
            # so the admin sees every problem in one go.
            if quarter_no:
                if quarter_no in first_seen:
                    result.errors.append(RowError(
                        row_no, "Quarter No",
                        f"'{quarter_no}' is duplicated in this file "
                        f"(first seen at row {first_seen[quarter_no]})."))
                    continue
                first_seen[quarter_no] = row_no
            if quarter is not None:
                quarters.append(quarter)
    finally:
        workbook.close()

    if data_rows == 0 and not result.errors:
        result.errors.append(RowError(None, None, "The file has a header but no data rows."))

    # --- duplicates against the database ---
    existing = set(
        Quarter.objects.annotate(qn=Upper("quarter_no"))
        .filter(qn__in=list(first_seen))
        .values_list("qn", flat=True)
    )
    for quarter_no in sorted(existing, key=first_seen.get):
        result.errors.append(RowError(
            first_seen[quarter_no], "Quarter No",
            f"'{quarter_no}' already exists in the database."))

    if result.errors:
        result.errors.sort(key=lambda e: (e.row or 0))
        return result

    # --- save: all or nothing ---
    try:
        with transaction.atomic():
            Quarter.objects.bulk_create(quarters)
    except IntegrityError:
        # e.g. another admin imported the same quarter a moment ago
        result.errors.append(RowError(
            None, None, "Import cancelled: a quarter number was saved by someone else "
                        "during the import. Nothing was imported; please try again."))
        return result

    result.created = len(quarters)
    return result


def _check_header(header):
    errors = []
    header = [_clean_text(h) for h in header]
    # Ignore empty trailing columns (Excel often keeps formatting there).
    while header and header[-1] == "":
        header.pop()
    for i, expected in enumerate(EXPECTED_HEADERS):
        found = header[i] if i < len(header) else ""
        if found != expected:
            col = chr(ord("A") + i)
            errors.append(RowError(
                1, f"Column {col}",
                f"expected header '{expected}', found '{found}'" if found
                else f"missing header '{expected}'"))
    for i in range(len(EXPECTED_HEADERS), len(header)):
        if header[i]:
            errors.append(RowError(1, f"Column {chr(ord('A') + i)}",
                                   f"unexpected extra column '{header[i]}'"))
    return errors


def _validate_row(row_no, cells):
    """Return (quarter_no, unsaved Quarter or None, list of RowError)."""
    errors = []
    values = dict(zip(EXPECTED_HEADERS, cells))

    def text(column, max_length):
        value = _clean_text(values[column])
        if value == "":
            errors.append(RowError(row_no, column, "is required"))
        elif len(value) > max_length:
            errors.append(RowError(row_no, column, f"must be at most {max_length} characters"))
        return value

    quarter_no = text("Quarter No", 20).upper()
    sector = text("Sector", 100)
    location = text("Location / Block", 150)
    floor = text("Floor", 20)

    type_text = _clean_text(values["Type"])
    quarter_type = TYPE_LOOKUP.get(type_text.lower())
    if quarter_type is None:
        allowed = ", ".join(label for _, label in Quarter.QuarterType.choices)
        errors.append(RowError(row_no, "Type",
                               "is required" if not type_text
                               else f"must be one of {allowed} (got '{type_text}')"))

    area, err = _parse_positive_decimal(values["Area (sq ft)"], max_digits=8)
    if err:
        errors.append(RowError(row_no, "Area (sq ft)", err))
    base_rate, err = _parse_positive_decimal(values["Base Rate (Rs.)"], max_digits=12)
    if err:
        errors.append(RowError(row_no, "Base Rate (Rs.)", err))

    status_text = _clean_text(values["Status"])
    if status_text and status_text.lower() != "vacant":
        errors.append(RowError(row_no, "Status",
                               f"must be 'Vacant' for imported quarters (got '{status_text}')"))

    if errors:
        return quarter_no, None, errors
    return quarter_no, Quarter(
        quarter_no=quarter_no, sector=sector, location_block=location,
        quarter_type=quarter_type, floor=floor, area_sqft=area,
        base_rate=base_rate, status=Quarter.Status.VACANT,
    ), []
