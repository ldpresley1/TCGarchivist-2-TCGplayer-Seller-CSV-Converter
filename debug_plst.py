import urllib.request
import json

url = 'https://tcgcsv.com/tcgplayer/1/groups'
headers = {'User-Agent': 'tcg-csv-converter/1.0', 'Accept': 'application/json'}
req = urllib.request.Request(url, headers=headers)

try:
    with urllib.request.urlopen(req, timeout=10) as response:
        data = json.loads(response.read().decode('utf-8'))
        results = data.get('results', [])
        
        # Look for anything with 'plst' or 'placeholder'
        found = False
        for item in results:
            name = item.get('name', '').lower()
            abbr = item.get('abbreviation', '').lower()
            if 'plst' in name or 'plst' in abbr or 'placeholder' in name:
                print(f"Found: {item.get('name')} ({item.get('abbreviation')})")
                found = True
        
        if not found:
            print("Not found. Showing all with empty abbreviation:")
            for item in results:
                if not item.get('abbreviation', '').strip():
                    print(f"  {item.get('name')}")
except Exception as e:
    print(f'Error: {e}')
