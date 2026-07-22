# TCGplayer Seller Import Notes

The generated `.tcgplayer.csv` file is a TCGplayer-ID-mapped conversion output.
It is not guaranteed to match the current TCGplayer Seller Portal CSV import template exactly.

## Verified constraint from TCGplayer help

In TCGplayer's Seller Portal CSV import documentation for pricing and quantity updates,
`TCG Marketplace Price` is required during import.

That means this generated file:

- includes useful `TCGplayer Id` matching data
- includes `Add to Quantity`
- does **not** currently include `TCG Marketplace Price`
- should therefore **not** be treated as a guaranteed ready-to-import Seller Portal pricing CSV

## Current safe use

Use the generated file as:

- a mapped working CSV for review
- a base file for additional transformation
- a source for matching cards to TCGplayer product IDs

## Best path for Seller Portal import

If you want a Seller Portal-compatible import:

1. Export a CSV from TCGplayer Seller Portal first.
2. Match your collection rows into that template by `TCGplayer ID`.
3. Fill at least the required editable fields, especially `TCG Marketplace Price`.
4. Re-import that edited TCGplayer template.

## Best path for adding entirely new products

TCGplayer's current docs point heavily toward:

- Seller Portal add/manage list workflows
- TCGplayer App import to Seller Portal
- export/edit/re-import workflows from Staged or Live inventory

So there may be multiple valid flows, but the current generated example file should not be assumed to be the official seller import template.
