import csv

# Check the final output has prices
with open('test_prices.tcgplayer.csv', 'r') as f:
    reader = csv.DictReader(f)
    rows = list(reader)
    
    # Count rows with prices
    with_price = sum(1 for r in rows if r.get('TCG Market Price', '').strip())
    print(f'Total rows: {len(rows)}')
    print(f'Rows with prices: {with_price}')
    print(f'Rows without prices: {len(rows) - with_price}')
    
    # Show sample
    if rows:
        r = rows[0]
        print(f'\nSample row:')
        print(f"  Name: {r.get('Product Name')}")
        print(f"  Set: {r.get('Set Name')}")
        print(f"  Price: ${r.get('TCG Market Price')}")
