"""
Generate the sample Excel files used for import tests and demos.

    python sample_data/make_samples.py

ALL DATA IN THESE FILES IS FAKE TEST DATA - placeholder figures, not official
SAIL data. The importer reads only the first sheet; a second "README" sheet in
each file says the data is fake.
"""
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font

HERE = Path(__file__).resolve().parent

HEADERS = [
    "Quarter No", "Sector", "Location / Block", "Type",
    "Floor", "Area (sq ft)", "Base Rate (Rs.)", "Status",
]

VALID_ROWS = [
    ["B-214", "Sector 4", "Near market", "Type B", "2nd", 750, 4500, "Vacant"],
    ["B-118", "Sector 4", "Near market", "Type B", "Ground", 750, 4800, "Vacant"],
    ["C-305", "Sector 2", "Opposite park", "Type C", "3rd", 620, 3600, "Vacant"],
    ["C-112", "Sector 2", "Opposite park", "Type C", "1st", 620, 3900, "Vacant"],
    ["D-407", "Sector 9", "Near school", "Type D", "4th", 480, 2400, "Vacant"],
    ["D-203", "Sector 9", "Near school", "Type D", "2nd", 480, 2700, "Vacant"],
    ["A-021", "Sector 12", "Main road side", "Type A", "Ground", 980, 6200, "Vacant"],
    ["A-134", "Sector 12", "Main road side", "Type A", "1st", 980, 6000, "Vacant"],
]

# Exactly four deliberate errors (row numbers are Excel row numbers):
INVALID_ROWS = [
    ["B-214", "Sector 4", "Near market", "Type B", "2nd", 750, 4500, "Vacant"],     # row 2: valid
    ["B-214", "Sector 4", "Near market", "Type B", "3rd", 750, 4600, "Vacant"],     # row 3: duplicate Quarter No
    ["C-305", "Sector 2", "Opposite park", "Type C", "3rd", "abc", 3600, "Vacant"],  # row 4: non-numeric Area
    ["D-407", "Sector 9", "Near school", "Type D", "4th", 480, -2400, "Vacant"],    # row 5: negative Base Rate
    [None, "Sector 12", "Main road side", "Type A", "Ground", 980, 6200, "Vacant"],  # row 6: missing Quarter No
]

BAD_HEADERS = ["Quarter Number"] + HEADERS[1:]  # "Quarter Number" instead of "Quarter No"


def write(filename, headers, rows, note):
    wb = Workbook()
    ws = wb.active
    ws.title = "Quarters (FAKE DATA)"
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for row in rows:
        ws.append(row)
    for col in "ABCDEFGH":
        ws.column_dimensions[col].width = 18

    readme = wb.create_sheet("README")
    readme.append(["FAKE TEST DATA - placeholder figures, NOT official SAIL data."])
    readme.append([note])

    wb.properties.title = "FAKE test data - SAIL quarter auction training project"
    wb.save(HERE / filename)
    print(f"wrote {HERE / filename}")


if __name__ == "__main__":
    write("quarters_sample.xlsx", HEADERS, VALID_ROWS, "8 valid rows; should import cleanly.")
    write("quarters_invalid.xlsx", HEADERS, INVALID_ROWS,
          "Deliberate errors: duplicate Quarter No (row 3), non-numeric Area (row 4), "
          "negative Base Rate (row 5), missing Quarter No (row 6).")
    write("quarters_bad_header.xlsx", BAD_HEADERS, VALID_ROWS,
          'Header error: column A is "Quarter Number" instead of "Quarter No".')
