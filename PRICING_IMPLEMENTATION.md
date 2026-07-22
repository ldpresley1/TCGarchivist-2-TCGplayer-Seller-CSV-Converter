# TCG CSV Converter - Pricing Integration Complete ✅

## What's New

The TCG CSV converter now automatically fetches real TCGplayer market prices from the tcgcsv.com API and populates the **TCG Market Price** column in the 16-column tcgplayer_seller format.

## Pricing Disclaimer

Fetched prices are approximate estimates and may lag behind live market changes. Treat them as a close starting point, then verify and adjust prices in TCGplayer before publishing inventory.

## How It Works

### Smart Set-Based Price Fetching

Instead of fetching all 450 Magic set prices upfront (which would waste bandwidth and hit rate limits), the tool now:

1. **Analyzes your input CSV** to identify which Magic sets are present
2. **Fetches the TCGplayer group IDs** for only those sets (one-time fetch)
3. **Retrieves prices only for matched sets** (on-demand per set)
4. **Caches results with timestamps** for subsequent runs (respects rate limits)
5. **Reuses cached prices** for repeat conversions

### Example

**First conversion (cold cache):**
```
Fetching TCGplayer Magic group IDs...
Fetched 440 Magic groups
Fetching prices for 7 set(s)...
  m15: 306 prices
  nph: 188 prices
  m11: 260 prices
  frf: 197 prices
  isd: 282 prices
  m12: 259 prices
Converted: Entire_Collection_Export_2026-06-21.csv -> test_prices.tcgplayer.csv
Rows written: 93
```

**Second conversion (warm cache - instant):**
```
Converted: Entire_Collection_Export_2026-06-21.csv -> test_prices2.tcgplayer.csv
Rows written: 93
```

## Output Format

All 16 columns of the tcgplayer_seller profile are populated:

| Column | Value | Source |
|--------|-------|--------|
| TCGplayer Id | (from database) | Scryfall index |
| Product Line | Magic | Fixed |
| Set Name | (from database) | Scryfall metadata |
| Product Name | (from database) | Scryfall + card name |
| Title | (from input) | Your export |
| Number | (from input) | Your export |
| Rarity | (from database) | Scryfall metadata |
| Condition | Lightly Played | Default (all cards) |
| **TCG Market Price** | **$X.XX** | **tcgcsv.com API** ✅ |
| TCG Direct Low | (empty) | Optional |
| TCG Low Price With Shipping | (empty) | Optional |
| TCG Low Price | (empty) | Optional |
| Total Quantity | (from input) | Your export |
| Add to Quantity | (from input) | Your export |
| TCG Marketplace Price | (empty) | Optional |
| Photo URL | (empty) | Optional |

## Using It

### Command Line

```bash
# Convert with automatic pricing
python tcg_csv_converter.py convert \
    --input "Entire_Collection_Export_2026-06-21.csv" \
    --output "my_collection.tcgplayer.csv" \
    --profile tcgplayer_seller \
    --skip-unmatched

# Batch process multiple exports
python tcg_csv_converter.py batch \
    --input-dir ./exports \
    --output-dir ./converted \
    --profile tcgplayer_seller
```

### GUI

```bash
python tcg_csv_converter_gui.py
```

Or use the Windows launcher:
```
launch_gui.bat
```

## Data Caching

Price cache is stored in `data/tcgplayer_prices.json` with metadata:
- **generated_at**: ISO timestamp of when prices were fetched
- **prices**: Nested dict mapping `set_code → product_id → price`

**Cache Files:**
- `data/tcgplayer_mtg_index.json` - All 115,872 Magic cards with TCGplayer IDs
- `data/tcgplayer_groups.json` - 440 Magic set codes mapped to group IDs (for pricing)
- `data/tcgplayer_prices.json` - Cached prices with timestamp

## Known Limitations

**Sets without TCGplayer prices:**
- "The List" (plst) - Promotional set with limited pricing data
  - Cards still export successfully with all data filled in
  - Just won't have TCG Market Price populated
  - ~2 cards out of typical collection affected

**Rate Limiting:**
- tcgcsv.com: 10,000 requests per 24 hours
- Current design respects this by:
  - Only fetching prices for sets in your input file
  - Caching results for subsequent runs
  - Not fetching all 450 sets upfront

## Workflow

1. **First Run:** ~15 seconds (downloads pricing data for your sets)
2. **Subsequent Runs:** <1 second (uses cache)
3. **Cache Stays Fresh:** Prices update when you re-fetch (manual only - no auto-scheduling)
4. **Manual Updates:** Use `python tcg_csv_converter.py update-db` to refresh card database

## Testing Results

**Test Case:** Entire_Collection_Export_2026-06-21.csv (93 cards)

✅ **93 cards converted successfully**
- 91 cards with TCG Market Prices populated
- 2 cards from "The List" without prices (set not in tcgcsv.com)
- All 16 columns present
- All conditions set to "Lightly Played"
- All set names and rarities from database

**Cache Efficiency:**
- First run: Fetched 6 Magic sets (440 groups fetched once, 6 sets' prices fetched)
- Second run: Zero API calls (all prices cached)
- Batch mode: Skips .tcgplayer.csv output files automatically

## Next Steps

Ready to import into TCGplayer! The CSV file is now in the exact format required by TCGplayer's Seller Portal import tool.
