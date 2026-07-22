# TCGplayer MTG CSV Converter

This app does four things:

1. Builds and updates a local MTG TCGplayer ID database.
2. Converts your collection CSV format into a minimum-format TCGplayer Seller CSV with **automatic pricing**.
3. Populates **TCG Market Price** from live tcgcsv.com pricing data.
4. Batch-converts many CSV files at once.

## What's New: Automatic Pricing ✨

The converter now automatically fetches real TCGplayer market prices and populates the **TCG Market Price** column.

## Pricing Disclaimer

Prices in generated files are estimates only. They are intended as a close guess for faster listing workflows, not as guaranteed accurate or real-time values. Always review and adjust pricing in TCGplayer before final upload.

**How it works:**
- Analyzes your input to find which Magic sets you own
- Fetches prices only for those sets (efficient, respects rate limits)
- Caches prices for instant re-runs
- Outputs a Seller Portal-compatible 16-column CSV (minimum workflow)

**Example output:**
```
TCGplayer Id,Product Line,Set Name,Product Name,Title,Number,Rarity,Condition,TCG Market Price,...
35630,,,,,,,,0.42,,,,,3,0.42,
```

See [PRICING_IMPLEMENTATION.md](PRICING_IMPLEMENTATION.md) for full details.

## Important: Output Format

The generated `.tcgplayer.csv` file is **now fully compatible** with TCGplayer Seller Portal import.

The converter now outputs one supported schema: `minimum`.

`minimum` uses TCGplayer's 16-column seller import header and fills only the key fields needed for this workflow:
- ✅ `TCG Market Price` (auto-populated from tcgcsv.com)
- ✅ `TCG Marketplace Price` (same value as `TCG Market Price`)
- ✅ `Add to Quantity`
- ✅ `TCGplayer Id`
- ⚠️ Most other columns are intentionally left blank in this mode (`Product Line`, `Set Name`, `Product Name`, `Title`, `Number`, `Rarity`, `Condition`, `TCG Direct Low`, `TCG Low Price With Shipping`, `TCG Low Price`, `Total Quantity`, `Photo URL`)
- ⚠️ Pricing values are approximate and should be verified before publishing live inventory

**Safe workflow:**
1. Run this converter on your collection export
2. Import the generated `.tcgplayer.csv` directly into TCGplayer Seller Portal
3. Done!

## TCGplayer Seller ID vs "normal" TCGplayer ID

This is the most important mapping detail in this repo:

- The input file starts with `Scryfall ID`.
- Scryfall is used as the first bridge to a TCGplayer product ID (`tcgplayer_id` / `tcgplayer_etched_id`).
- The converter then tries to resolve the best Seller-usable ID in this order:
	1. `pricing_custom` export match (preferred when available)
	2. tcgcsv products index match
	3. Scryfall-derived TCGplayer ID fallback

So Scryfall is primarily used to translate your original file into TCGplayer space; seller-specific matching is layered on top when data is available.

During conversion, the log prints:

`ID source usage: pricing_custom_export=..., tcgcsv_products=..., scryfall_fallback=...`

This tells you where IDs came from for that run.

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

## Output format

Only the `minimum` output format is supported.

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
python tcg_csv_converter.py combine --inputs "file1.csv" "file2.csv" --output "combined.tcgplayer.csv" --unmatched-output "combined.unmatched.csv" --skip-unmatched
```

You can also deduplicate in explicit combine mode:

```powershell
python tcg_csv_converter.py combine --inputs "file1.csv" "file2.csv" --output "combined.tcgplayer.csv" --unmatched-output "combined.unmatched.csv" --skip-unmatched --dedupe
```

Each source file writes:

- `<name>.tcgplayer.csv`
- `<name>.unmatched.csv` (only if there are unmatched cards)

When `--combined-output` is used, one merged file is written instead of per-file outputs.

Both `TCG Market Price` and `TCG Marketplace Price` are populated with the fetched market price.

## Keep IDs updated

Re-run this whenever you want fresh mappings for newly added cards:

```powershell
python tcg_csv_converter.py update-db
```

ID refresh is manual by default. No automatic update process is required.
