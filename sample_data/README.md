# Sample Excel files: ALL FAKE TEST DATA

Every figure in these files is a **placeholder**, not official SAIL data.

Regenerate them with:
```powershell
python sample_data/make_samples.py
```
The importer refuses auctions that start in the past, so the files are written with a
**bidding date one week after the day you run the script**. Re-run it before a demo if the
files are older than that. (The automated tests build the same workbooks in memory, so
they never go stale.)

## Columns (row 1, exact order and spelling)

`Quarter No | Sector | Location / Block | Type | Floor | Area (sq ft) | Base Rate (Rs.) | EMD Amount (Rs.) | Bidding Date | Start Time | Duration (min)`

Each row creates a quarter AND its auction (bidding slot). Dates and times are India time.
A blank Duration uses the default (5 minutes, `DEFAULT_AUCTION_DURATION_MINUTES`).

## The four files

| File | Content | Expected result |
|---|---|---|
| `quarters_sample.xlsx` | 8 valid quarters (B-214, B-118, C-305, C-112, D-407, D-203, A-021, A-134), base rates 24,000-62,000, EMD 5,000-12,000. Slots from 10:00, two at the same time, one with a blank duration. | 8 quarters + 8 scheduled auctions |
| `quarters_invalid.xlsx` | Row 2 valid, then deliberate errors: duplicate Quarter No (row 3), Area "abc" (4), negative Base Rate (5), missing Quarter No (6), EMD 0 (7), date 31-02-2026 (8), start yesterday (9), time 25:00 and duration 0 (10) | 9 errors listed, **nothing** imported |
| `quarters_bad_header.xlsx` | Column A header is "Quarter Number" | 1 header error, nothing imported |
| `quarters_edge_cases.xlsx` | Valid but awkward: text dates (DD-MM-YYYY, DD/MM/YYYY, YYYY-MM-DD), text times ("09:30", "2:15 PM", "16:45:00"), "1,050"-style numbers, extra spaces, lower-case type, blank duration, a blank row | 4 quarters imported |

Each workbook has a second sheet, "README", saying the data is fake. The importer reads
only the first sheet.
