# TCGplayer MTG CSV Converter

This app does four things:

1. Builds and updates a local MTG TCGplayer ID database.
2. Converts your collection CSV format into a TCGplayer-ID-mapped CSV with **automatic pricing**.
3. Populates **TCG Market Price** from live tcgcsv.com pricing data.
4. Batch-converts many CSV files at once.

## What's New: Automatic Pricing ✨

The converter now automatically fetches real TCGplayer market prices and populates the **TCG Market Price** column.

**How it works:**
- Analyzes your input to find which Magic sets you own
- Fetches prices only for those sets (efficient, respects rate limits)
- Caches prices for instant re-runs
- Outputs in exact TCGplayer Seller Portal format (16 columns)

**Example output:**
```
TCGplayer Id,Product Line,Set Name,Product Name,Title,Number,Rarity,Condition,TCG Market Price,...
35630,Magic,Magic 2011,Wurm's Tooth,,222,uncommon,Lightly Played,0.42,...
```

See [PRICING_IMPLEMENTATION.md](PRICING_IMPLEMENTATION.md) for full details.

## Important: TCGplayer Format

The generated `.tcgplayer.csv` file is **now fully compatible** with TCGplayer Seller Portal import.

The 16-column format matches exactly what TCGplayer exports and imports, including:
- ✅ `TCG Market Price` (auto-populated from tcgcsv.com)
- ✅ `Condition` (all cards set to "Lightly Played")
- ✅ All required columns for import

**Safe workflow:**
1. Run this converter on your collection export
2. Import the generated `.tcgplayer.csv` directly into TCGplayer Seller Portal
3. Done!

## Why this uses Scryfall data

TCGplayer MTG IDs are available in Scryfall's card data (`tcgplayer_id` and `tcgplayer_etched_id`).
That gives a stable, scriptable way to keep IDs up to date without managing TCGplayer API credentials.

## Requirements

- Python 3.9+
- Internet connection for `update-db`

No third-party packages are required.

## Input CSV expected format

The converter expects these headers in each input CSV:

- `Name`
- `Set code`
- `Collector number`
- `Finish`
- `Quantity`
- `Scryfall ID`

Your existing export file in this folder already matches this schema.

## Quick start

From this folder:

```powershell
python tcg_csv_converter.py update-db
```

Or launch the GUI:

```powershell
python tcg_csv_converter_gui.py
```

Or on Windows, double-click `launch_gui.bat`.

The GUI provides buttons for:

- Manual ID update (runs only when clicked)
- Single-file conversion
- Batch conversion

Convert your current file:

```powershell
python tcg_csv_converter.py convert --input "Entire_Collection_Export_2026-06-21.csv" --output "Entire_Collection_Export_2026-06-21.tcgplayer.csv" --unmatched-output "Entire_Collection_Export_2026-06-21.unmatched.csv" --skip-unmatched
```

## Output profiles

- `detailed` (default):
  - `TCGplayer Id`
  - `Product Name`
  - `Set Code`
  - `Collector Number`
  - `Printing`
  - `Condition`
  - `Language`
  - `Add to Quantity`

- `minimal`:
  - `TCGplayer Id`
  - `Add to Quantity`

Example with minimal profile:

```powershell
python tcg_csv_converter.py convert --input "input.csv" --output "output.csv" --profile minimal --skip-unmatched
```

## Batch conversion

Convert all CSV files in a folder:

```powershell
python tcg_csv_converter.py batch --input-dir "." --output-dir "out" --pattern "*.csv" --skip-unmatched
```

Combine multiple CSV files into one output CSV:

```powershell
python tcg_csv_converter.py batch --input-dir "." --combined-output "combined.tcgplayer.csv" --combined-unmatched-output "combined.unmatched.csv" --pattern "*.csv" --skip-unmatched
```

Add `--dedupe` to merge duplicate cards in the combined file and sum `Add to Quantity`:

```powershell
python tcg_csv_converter.py batch --input-dir "." --combined-output "combined.tcgplayer.csv" --combined-unmatched-output "combined.unmatched.csv" --pattern "*.csv" --skip-unmatched --dedupe
```

Or choose exact files (multi-file picker equivalent for CLI):

```powershell
python tcg_csv_converter.py combine --inputs "file1.csv" "file2.csv" --output "combined.tcgplayer.csv" --unmatched-output "combined.unmatched.csv" --profile tcgplayer_seller --skip-unmatched
```

You can also deduplicate in explicit combine mode:

```powershell
python tcg_csv_converter.py combine --inputs "file1.csv" "file2.csv" --output "combined.tcgplayer.csv" --unmatched-output "combined.unmatched.csv" --profile tcgplayer_seller --skip-unmatched --dedupe
```

Each source file writes:

- `<name>.tcgplayer.csv`
- `<name>.unmatched.csv` (only if there are unmatched cards)

When `--combined-output` is used, one merged file is written instead of per-file outputs.

In `tcgplayer_seller` profile, both `TCG Market Price` and `TCG Marketplace Price` are now populated with the fetched market price.

## Keep IDs updated

Re-run this whenever you want fresh mappings for newly added cards:

```powershell
python tcg_csv_converter.py update-db
```

ID refresh is manual by default. No automatic update process is required.
