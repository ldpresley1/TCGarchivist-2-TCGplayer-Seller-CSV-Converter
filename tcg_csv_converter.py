#!/usr/bin/env python3
"""TCGplayer MTG ID updater and CSV converter.

This tool uses Scryfall bulk data to maintain a local index of TCGplayer MTG IDs,
then converts collection CSV files into TCGplayer import-ready CSV files.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import pathlib
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

SCRYFALL_BULK_ENDPOINTS = [
    "https://api.scryfall.com/bulk-data/default-cards",
    "https://api.scryfall.com/bulk-data",
]
DEFAULT_DB_PATH = pathlib.Path("data/tcgplayer_mtg_index.json")
DEFAULT_PRICE_CACHE_PATH = pathlib.Path("data/tcgplayer_prices.json")
DEFAULT_GROUPS_CACHE_PATH = pathlib.Path("data/tcgplayer_groups.json")
TCGCSV_GROUPS_ENDPOINT = "https://tcgcsv.com/tcgplayer/1/groups"
TCGCSV_PRICES_ENDPOINT = "https://tcgcsv.com/tcgplayer/1"
TCGCSV_LAST_UPDATED = "https://tcgcsv.com/last-updated.txt"
SELLER_EXPORT_PATTERNS = [
    "*pricing_custom*.csv",
    "*MyPricing*.csv",
    "*mypricing*.csv",
]
DEFAULT_FALLBACK_PRICE = 0.10
SET_NAME_ALIASES = {
    "3rd edition": "revised edition",
    "third edition": "revised edition",
    "revised": "revised edition",
    "4th edition": "fourth edition",
    "5th edition": "fifth edition",
    "6th edition": "classic sixth edition",
    "sixth edition": "classic sixth edition",
    "7th edition": "7th edition",
    "eighth edition": "8th edition",
    "limited edition alpha": "alpha edition",
    "limited edition beta": "beta edition",
    "unlimited": "unlimited edition",
    "the list": "the list reprints",
}
SET_CODE_NAME_OVERRIDES = {
    "2ed": "Unlimited Edition",
    "3ed": "Revised Edition",
    "lea": "Alpha Edition",
    "leb": "Beta Edition",
    "nem": "Nemesis",
    "plst": "The List Reprints",
}
SELLER_EXPORT_REQUIRED_HEADERS = {
    "TCGplayer Id",
    "Set Name",
    "Product Name",
    "Number",
    "Condition",
}


@dataclass
class CardLookupResult:
    tcgplayer_id: Optional[int]
    match_reason: str


def now_utc_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def normalize_finish(value: str) -> str:
    raw = (value or "").strip().lower()
    if raw in {"foil", "foiled"}:
        return "foil"
    if raw in {"etched", "etched foil", "foil etched"}:
        return "etched"
    return "normal"


def normalize_collector_number(value: str) -> str:
    text = (value or "").strip().lower()
    # Handles values like "M11-191" by using the trailing collector section.
    if "-" in text:
        text = text.split("-")[-1]
    return text


def normalize_name(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def primary_face_name(value: str) -> str:
    """Return front-face name for split names like 'A // B'."""
    raw = (value or "").strip()
    if "//" in raw:
        raw = raw.split("//", 1)[0].strip()
    return raw


def normalize_set_name(value: str) -> str:
    text = (value or "").strip().lower()
    text = re.sub(r"\([^)]*\)", "", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return SET_NAME_ALIASES.get(text, text)


def normalize_condition_name(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def resolve_set_name_from_code(set_code: str, set_code_to_name: Dict[str, str]) -> str:
    code = (set_code or "").strip().lower()
    if not code:
        return ""
    explicit = set_code_to_name.get(code, "")
    if explicit:
        return explicit
    return SET_CODE_NAME_OVERRIDES.get(code, "")


def parse_collector_set_hint(value: str) -> str:
    """Extract set code hint from collector values like M15-138."""
    raw = (value or "").strip().lower()
    if "-" not in raw:
        return ""
    prefix = raw.split("-", 1)[0]
    return re.sub(r"[^a-z0-9]+", "", prefix)


def detect_seller_export_file(input_path: pathlib.Path) -> Optional[pathlib.Path]:
    """Find latest seller export file (pricing_custom/MyPricing) near the input/workspace."""
    search_dirs: List[pathlib.Path] = [
        input_path.parent,
        pathlib.Path.cwd(),
        pathlib.Path.home() / "Documents",
    ]
    seen: set = set()
    candidates: List[pathlib.Path] = []

    for directory in search_dirs:
        try:
            resolved = directory.resolve()
        except Exception:
            resolved = directory
        key = str(resolved).lower()
        if key in seen:
            continue
        seen.add(key)

        if not directory.exists() or not directory.is_dir():
            continue

        for pattern in SELLER_EXPORT_PATTERNS:
            for candidate in directory.glob(pattern):
                if candidate.is_file() and is_valid_seller_export_file(candidate):
                    candidates.append(candidate)

    if not candidates:
        return None
    return max(candidates, key=lambda path: (seller_export_filename_priority(path.name), path.stat().st_mtime))


def seller_export_filename_priority(name: str) -> int:
    lowered = (name or "").strip().lower()
    if "pricing_custom_export" in lowered:
        return 3
    if lowered.startswith("tcgplayer__pricing_custom"):
        return 2
    if "mypricing" in lowered:
        return 1
    return 0


def is_valid_seller_export_file(path: pathlib.Path) -> bool:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            headers = set(reader.fieldnames or [])
            return SELLER_EXPORT_REQUIRED_HEADERS.issubset(headers)
    except Exception:
        return False


def load_seller_export_index(
    export_path: pathlib.Path,
) -> Tuple[
    Dict[Tuple[str, str, str], int],
    Dict[Tuple[str, str, str, str], int],
    Dict[Tuple[str, str], int],
    Dict[Tuple[str, str, str], int],
    Dict[Tuple[str, str], int],
    Dict[Tuple[str, str, str], int],
    Dict[Tuple[str, str], int],
    Dict[Tuple[str, str, str], int],
    Dict[str, int],
    Dict[Tuple[str, str], int],
    Dict[int, dict],
]:
    """Load seller export index.

    Returns:
    - by_set_number_name[(set_name_norm, collector_norm, name_norm)] -> product_id
    - by_number_name_unique[(collector_norm, name_norm)] -> product_id when unique across sets
    """
    by_set_number_name: Dict[Tuple[str, str, str], int] = {}
    by_set_number_name_condition: Dict[Tuple[str, str, str, str], int] = {}
    by_number_name_values: Dict[Tuple[str, str], set] = {}
    by_number_name_condition_values: Dict[Tuple[str, str, str], set] = {}
    by_set_number_values: Dict[Tuple[str, str], set] = {}
    by_set_number_condition_values: Dict[Tuple[str, str, str], set] = {}
    by_set_name_values: Dict[Tuple[str, str], set] = {}
    by_set_name_condition_values: Dict[Tuple[str, str, str], set] = {}
    by_name_values: Dict[str, set] = {}
    by_name_condition_values: Dict[Tuple[str, str], set] = {}
    details_by_id: Dict[int, dict] = {}

    with export_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            pid = safe_int(row.get("TCGplayer Id"))
            if pid is None:
                continue

            set_name = normalize_set_name(row.get("Set Name", ""))
            collector = normalize_collector_number(row.get("Number", "") or "")
            name = normalize_name(row.get("Product Name", "") or "")
            condition = normalize_condition_name(row.get("Condition", "") or "")
            if not name:
                continue

            if set_name and collector:
                by_set_number_name[(set_name, collector, name)] = pid
                if condition:
                    by_set_number_name_condition[(set_name, collector, name, condition)] = pid
                    by_set_number_condition_values.setdefault((set_name, collector, condition), set()).add(pid)
                by_set_number_values.setdefault((set_name, collector), set()).add(pid)

            if collector:
                by_number_name_values.setdefault((collector, name), set()).add(pid)
                if condition:
                    by_number_name_condition_values.setdefault((collector, name, condition), set()).add(pid)
            if set_name:
                by_set_name_values.setdefault((set_name, name), set()).add(pid)
                if condition:
                    by_set_name_condition_values.setdefault((set_name, name, condition), set()).add(pid)
            by_name_values.setdefault(name, set()).add(pid)
            if condition:
                by_name_condition_values.setdefault((name, condition), set()).add(pid)
            details_by_id[pid] = {
                "set_name": (row.get("Set Name", "") or "").strip(),
                "name": (row.get("Product Name", "") or "").strip(),
                "number": (row.get("Number", "") or "").strip(),
                "rarity": (row.get("Rarity", "") or "").strip(),
                "condition": (row.get("Condition", "") or "").strip(),
            }

    by_number_name_unique: Dict[Tuple[str, str], int] = {}
    for key, values in by_number_name_values.items():
        if len(values) == 1:
            by_number_name_unique[key] = next(iter(values))

    by_number_name_condition_unique: Dict[Tuple[str, str, str], int] = {}
    for key, values in by_number_name_condition_values.items():
        if len(values) == 1:
            by_number_name_condition_unique[key] = next(iter(values))

    by_set_number_unique: Dict[Tuple[str, str], int] = {}
    for key, values in by_set_number_values.items():
        if len(values) == 1:
            by_set_number_unique[key] = next(iter(values))

    by_set_number_condition_unique: Dict[Tuple[str, str, str], int] = {}
    for key, values in by_set_number_condition_values.items():
        if len(values) == 1:
            by_set_number_condition_unique[key] = next(iter(values))

    by_set_name_unique: Dict[Tuple[str, str], int] = {}
    for key, values in by_set_name_values.items():
        if len(values) == 1:
            by_set_name_unique[key] = next(iter(values))

    by_set_name_condition_unique: Dict[Tuple[str, str, str], int] = {}
    for key, values in by_set_name_condition_values.items():
        if len(values) == 1:
            by_set_name_condition_unique[key] = next(iter(values))

    by_name_unique: Dict[str, int] = {}
    for key, values in by_name_values.items():
        if len(values) == 1:
            by_name_unique[key] = next(iter(values))

    by_name_condition_unique: Dict[Tuple[str, str], int] = {}
    for key, values in by_name_condition_values.items():
        if len(values) == 1:
            by_name_condition_unique[key] = next(iter(values))

    return (
        by_set_number_name,
        by_set_number_name_condition,
        by_number_name_unique,
        by_number_name_condition_unique,
        by_set_number_unique,
        by_set_number_condition_unique,
        by_set_name_unique,
        by_set_name_condition_unique,
        by_name_unique,
        by_name_condition_unique,
        details_by_id,
    )


def lookup_seller_export_id(
    row: dict,
    metadata: Optional[CardMetadata],
    selected_condition: str,
    set_code_to_name: Dict[str, str],
    by_set_number_name: Dict[Tuple[str, str, str], int],
    by_set_number_name_condition: Dict[Tuple[str, str, str, str], int],
    by_number_name_unique: Dict[Tuple[str, str], int],
    by_number_name_condition_unique: Dict[Tuple[str, str, str], int],
    by_set_number_unique: Dict[Tuple[str, str], int],
    by_set_number_condition_unique: Dict[Tuple[str, str, str], int],
    by_set_name_unique: Dict[Tuple[str, str], int],
    by_set_name_condition_unique: Dict[Tuple[str, str, str], int],
    by_name_unique: Dict[str, int],
    by_name_condition_unique: Dict[Tuple[str, str], int],
) -> Optional[int]:
    collector_raw = row.get("Collector number", "") or ""
    collector = normalize_collector_number(collector_raw)
    if not collector:
        return None

    input_name = row.get("Name", "") or ""
    name_candidates = [normalize_name(input_name)]
    front_face = normalize_name(primary_face_name(input_name))
    if front_face and front_face not in name_candidates:
        name_candidates.append(front_face)
    if metadata is not None:
        name_candidates.append(normalize_name(metadata.name))
    name_candidates = [value for value in name_candidates if value]
    if not name_candidates:
        return None

    set_code = (row.get("Set code", "") or "").strip().lower()
    set_candidates: List[str] = []
    if set_code:
        set_candidates.append(normalize_set_name(resolve_set_name_from_code(set_code, set_code_to_name)))
    if set_code == "plst":
        hinted_set_code = parse_collector_set_hint(collector_raw)
        if hinted_set_code:
            set_candidates.append(
                normalize_set_name(resolve_set_name_from_code(hinted_set_code, set_code_to_name))
            )
    if metadata is not None:
        set_candidates.append(normalize_set_name(metadata.set_name))
    set_candidates = [value for value in set_candidates if value]

    finish = normalize_finish(row.get("Finish", ""))
    cond_base = normalize_condition_name(selected_condition)
    cond_candidates: List[str] = []
    if finish in {"foil", "etched"} and cond_base:
        cond_candidates.append(f"{cond_base} foil")
    if cond_base:
        cond_candidates.append(cond_base)

    allow_cross_set_number_fallback = not set_candidates or set_code == "plst"

    for set_name in set_candidates:
        for name in name_candidates:
            for cond in cond_candidates:
                pid = by_set_number_name_condition.get((set_name, collector, name, cond))
                if pid is not None:
                    return pid

    for set_name in set_candidates:
        for cond in cond_candidates:
            pid = by_set_number_condition_unique.get((set_name, collector, cond))
            if pid is not None:
                return pid

    for set_name in set_candidates:
        for name in name_candidates:
            pid = by_set_number_name.get((set_name, collector, name))
            if pid is not None:
                return pid

    for set_name in set_candidates:
        pid = by_set_number_unique.get((set_name, collector))
        if pid is not None:
            return pid

    for set_name in set_candidates:
        for name in name_candidates:
            for cond in cond_candidates:
                pid = by_set_name_condition_unique.get((set_name, name, cond))
                if pid is not None:
                    return pid

    for set_name in set_candidates:
        for name in name_candidates:
            pid = by_set_name_unique.get((set_name, name))
            if pid is not None:
                return pid

    if allow_cross_set_number_fallback:
        for name in name_candidates:
            for cond in cond_candidates:
                pid = by_number_name_condition_unique.get((collector, name, cond))
                if pid is not None:
                    return pid

        for name in name_candidates:
            pid = by_number_name_unique.get((collector, name))
            if pid is not None:
                return pid

    # The List often carries non-original set codes (e.g. M15-138 under plst).
    if (row.get("Set code", "") or "").strip().lower() == "plst":
        for name in name_candidates:
            for cond in cond_candidates:
                pid = by_name_condition_unique.get((name, cond))
                if pid is not None:
                    return pid
        for name in name_candidates:
            pid = by_name_unique.get(name)
            if pid is not None:
                return pid

    return None


def safe_int(value: object) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def fetch_json(url: str, headers: Optional[Dict[str, str]] = None) -> object:
    if headers is None:
        headers = {}
    default_headers = {
        "User-Agent": "tcg-csv-converter/1.0",
        "Accept": "application/json",
    }
    default_headers.update(headers)
    request = urllib.request.Request(url, headers=default_headers)
    with urllib.request.urlopen(request) as response:
        return json.load(response)


def load_price_cache(cache_path: pathlib.Path) -> Dict[str, Dict[str, Optional[float]]]:
    """Load cached prices: {set_code: {product_id: price}}."""
    if cache_path.exists():
        with cache_path.open("r", encoding="utf-8") as handle:
            try:
                data = json.load(handle)
                if isinstance(data, dict) and "prices" in data:
                    return data.get("prices", {})
                return data if isinstance(data, dict) else {}
            except (json.JSONDecodeError, ValueError):
                return {}
    return {}


def save_price_cache(cache_path: pathlib.Path, prices: Dict[str, Dict[str, Optional[float]]]) -> None:
    """Save prices cache with metadata."""
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with cache_path.open("w", encoding="utf-8") as handle:
        json.dump({
            "generated_at": now_utc_iso(),
            "prices": prices,
        }, handle, ensure_ascii=True)


def load_groups_cache(cache_path: pathlib.Path) -> Dict[str, int]:
    """Load cached mapping of set_code -> groupId."""
    if cache_path.exists():
        with cache_path.open("r", encoding="utf-8") as handle:
            try:
                return json.load(handle)
            except (json.JSONDecodeError, ValueError):
                return {}
    return {}


def save_groups_cache(cache_path: pathlib.Path, groups: Dict[str, int]) -> None:
    """Save mapping of set_code -> groupId."""
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with cache_path.open("w", encoding="utf-8") as handle:
        json.dump(groups, handle, ensure_ascii=True)


def fetch_magic_groups() -> Dict[str, int]:
    """Fetch all Magic set groups from tcgcsv.com and return abbreviation (set_code) -> groupId mapping."""
    try:
        data = fetch_json(TCGCSV_GROUPS_ENDPOINT)
        if not isinstance(data, dict) or "results" not in data:
            print("Warning: Could not parse groups response")
            return {}

        groups_mapping = {}
        for item in data.get("results", []):
            if not isinstance(item, dict):
                continue
            group_id = item.get("groupId")
            abbreviation = (item.get("abbreviation") or "").strip().lower()
            if group_id and abbreviation:
                groups_mapping[abbreviation] = group_id

        print(f"Fetched {len(groups_mapping)} Magic groups")
        return groups_mapping
    except Exception as exc:
        print(f"Warning: Failed to fetch groups: {exc}")
        return {}


def fetch_magic_group_names() -> Dict[str, str]:
    """Fetch set_code -> set_name mapping from tcgcsv groups endpoint."""
    try:
        data = fetch_json(TCGCSV_GROUPS_ENDPOINT)
        if not isinstance(data, dict) or "results" not in data:
            return {}
        mapping: Dict[str, str] = {}
        for item in data.get("results", []):
            if not isinstance(item, dict):
                continue
            abbreviation = (item.get("abbreviation") or "").strip().lower()
            name = (item.get("name") or "").strip()
            if abbreviation and name:
                mapping[abbreviation] = name
        return mapping
    except Exception:
        return {}


def fetch_prices_for_group(group_id: int) -> Dict[str, Optional[float]]:
    """Fetch market prices for a specific group and return product_id -> price mapping."""
    try:
        url = f"{TCGCSV_PRICES_ENDPOINT}/{group_id}/prices"
        data = fetch_json(url)

        if not isinstance(data, dict) or "results" not in data:
            return {}

        prices = {}
        for price_entry in data.get("results", []):
            if not isinstance(price_entry, dict):
                continue
            product_id = price_entry.get("productId")
            market_price = price_entry.get("marketPrice")
            if product_id and market_price is not None:
                try:
                    prices[str(product_id)] = float(market_price)
                except (ValueError, TypeError):
                    prices[str(product_id)] = None

        return prices
    except Exception:
        return {}


def _extended_data_value(entry: dict, key: str) -> str:
    extended = entry.get("extendedData")
    if not isinstance(extended, list):
        return ""
    for item in extended:
        if not isinstance(item, dict):
            continue
        if (item.get("name") or "").strip().lower() == key.lower():
            return str(item.get("value") or "").strip()
    return ""


def fetch_products_for_group(group_id: int) -> List[dict]:
    try:
        url = f"{TCGCSV_PRICES_ENDPOINT}/{group_id}/products"
        data = fetch_json(url)
        if not isinstance(data, dict) or "results" not in data:
            return []
        results = data.get("results", [])
        return results if isinstance(results, list) else []
    except Exception:
        return []


def prepare_seller_product_index_for_input(
    input_path: pathlib.Path,
) -> Tuple[Dict[Tuple[str, str, str], dict], Dict[Tuple[str, str], dict]]:
    """Build tcgcsv product indexes keyed by:
    - (set_code, collector, normalized_name)
    - unique (set_code, collector) fallback when name variants differ.
    """
    set_codes_needed = set()
    with input_path.open("r", encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        for row in reader:
            set_code = (row.get("Set code", "") or "").strip().lower()
            if set_code:
                set_codes_needed.add(set_code)

    groups_mapping = load_groups_cache(DEFAULT_GROUPS_CACHE_PATH)
    if not groups_mapping:
        groups_mapping = fetch_magic_groups()
        if groups_mapping:
            save_groups_cache(DEFAULT_GROUPS_CACHE_PATH, groups_mapping)

    index: Dict[Tuple[str, str, str], dict] = {}
    by_set_collector_values: Dict[Tuple[str, str], List[dict]] = {}
    group_names = fetch_magic_group_names()
    for set_code in sorted(set_codes_needed):
        group_id = groups_mapping.get(set_code)
        if not group_id:
            continue
        products = fetch_products_for_group(group_id)
        for product in products:
            if not isinstance(product, dict):
                continue
            product_id = safe_int(product.get("productId"))
            if product_id is None:
                continue
            product_name = str(product.get("name") or "").strip()
            number = normalize_collector_number(_extended_data_value(product, "Number"))
            if not number or not product_name:
                continue
            rarity_raw = _extended_data_value(product, "Rarity").strip().lower()
            rarity_map = {
                "c": "common",
                "u": "uncommon",
                "r": "rare",
                "m": "mythic",
                "l": "land",
                "s": "special",
            }
            entry = {
                "tcgplayer_id": product_id,
                "name": product_name,
                "set_code": set_code,
                "set_name": group_names.get(set_code, ""),
                "rarity": rarity_map.get(rarity_raw, rarity_raw),
                "match_reason": "tcgcsv_products",
            }
            index[(set_code, number, normalize_name(product_name))] = entry
            by_set_collector_values.setdefault((set_code, number), []).append(entry)

    by_set_collector_unique: Dict[Tuple[str, str], dict] = {}
    for key, entries in by_set_collector_values.items():
        unique_ids = {safe_int(item.get("tcgplayer_id")) for item in entries}
        unique_ids.discard(None)
        if len(unique_ids) == 1:
            by_set_collector_unique[key] = entries[0]

    return index, by_set_collector_unique


def lookup_seller_product(
    product_index: Dict[Tuple[str, str, str], dict],
    product_index_set_collector_unique: Dict[Tuple[str, str], dict],
    row: dict,
) -> Optional[CardMetadata]:
    set_code = (row.get("Set code", "") or "").strip().lower()
    collector = normalize_collector_number(row.get("Collector number", "") or "")
    name = normalize_name(row.get("Name", "") or "")
    if not set_code or not collector or not name:
        return None
    entry = product_index.get((set_code, collector, name))
    if not isinstance(entry, dict):
        entry = product_index_set_collector_unique.get((set_code, collector))
    if not isinstance(entry, dict):
        return None
    pid = safe_int(entry.get("tcgplayer_id"))
    if pid is None:
        return None
    return CardMetadata(
        tcgplayer_id=pid,
        name=entry.get("name", row.get("Name", "")),
        set_code=entry.get("set_code", set_code),
        set_name=entry.get("set_name", ""),
        rarity=entry.get("rarity", ""),
        match_reason=entry.get("match_reason", "tcgcsv_products"),
    )


def get_default_cards_download_uri() -> Tuple[str, str]:
    for endpoint in SCRYFALL_BULK_ENDPOINTS:
        payload = fetch_json(endpoint)
        if not isinstance(payload, dict):
            continue

        # Preferred endpoint returns the default_cards object directly.
        if payload.get("type") == "default_cards" and payload.get("download_uri"):
            return payload["download_uri"], payload.get("updated_at", "")

        # Fallback endpoint returns a list in the "data" field.
        records = payload.get("data")
        if isinstance(records, list):
            for item in records:
                if item.get("type") == "default_cards" and item.get("download_uri"):
                    return item["download_uri"], item.get("updated_at", "")

    raise RuntimeError("Scryfall default_cards feed not found.")


def build_index(cards: Iterable[dict]) -> dict:
    by_scryfall_id: Dict[str, dict] = {}
    by_set_collector_finish: Dict[str, dict] = {}
    by_name_set_number_finish: Dict[str, dict] = {}

    total_cards = 0
    indexed_cards = 0

    for card in cards:
        total_cards += 1

        tcgplayer_id = safe_int(card.get("tcgplayer_id"))
        tcgplayer_etched_id = safe_int(card.get("tcgplayer_etched_id"))
        if tcgplayer_id is None and tcgplayer_etched_id is None:
            continue

        scryfall_id = (card.get("id") or "").strip().lower()
        name = (card.get("name") or "").strip()
        name_lower = name.lower()
        set_code = (card.get("set") or "").strip().lower()
        set_name = (card.get("set_name") or "").strip()
        collector_number = normalize_collector_number(card.get("collector_number") or "")
        rarity = (card.get("rarity") or "").strip()

        finish_map = {
            "normal": tcgplayer_id,
            "foil": tcgplayer_id,
            "etched": tcgplayer_etched_id or tcgplayer_id,
        }

        card_data = {
            "name": name,
            "set_code": set_code,
            "set_name": set_name,
            "rarity": rarity,
            "normal": finish_map["normal"],
            "foil": finish_map["foil"],
            "etched": finish_map["etched"],
        }

        if scryfall_id:
            by_scryfall_id[scryfall_id] = card_data

        if set_code and collector_number:
            for finish in ("normal", "foil", "etched"):
                pid = finish_map.get(finish)
                if pid is None:
                    continue
                key = f"{set_code}|{collector_number}|{finish}"
                by_set_collector_finish[key] = card_data

        if name and set_code and collector_number:
            for finish in ("normal", "foil", "etched"):
                pid = finish_map.get(finish)
                if pid is None:
                    continue
                key = f"{name_lower}|{set_code}|{collector_number}|{finish}"
                by_name_set_number_finish[key] = card_data

        indexed_cards += 1

    return {
        "meta": {
            "generated_at": now_utc_iso(),
            "total_cards_seen": total_cards,
            "cards_with_tcgplayer_ids": indexed_cards,
        },
        "by_scryfall_id": by_scryfall_id,
        "by_set_collector_finish": by_set_collector_finish,
        "by_name_set_number_finish": by_name_set_number_finish,
    }


def update_database(db_path: pathlib.Path) -> None:
    print("Fetching Scryfall bulk metadata...")
    download_uri, updated_at = get_default_cards_download_uri()

    print("Downloading and parsing default_cards feed (this may take a bit)...")
    cards = fetch_json(download_uri)
    if not isinstance(cards, list):
        raise RuntimeError("Unexpected default_cards payload format.")

    print("Building local TCGplayer lookup index...")
    index = build_index(cards)
    index["meta"]["scryfall_default_cards_updated_at"] = updated_at

    db_path.parent.mkdir(parents=True, exist_ok=True)
    with db_path.open("w", encoding="utf-8", newline="") as handle:
        json.dump(index, handle, ensure_ascii=True)

    print(f"Database updated: {db_path}")
    print(f"Cards scanned: {index['meta']['total_cards_seen']}")
    print(f"Cards indexed: {index['meta']['cards_with_tcgplayer_ids']}")


def update_groups_cache(cache_path: pathlib.Path = DEFAULT_GROUPS_CACHE_PATH) -> None:
    """Fetch and update the TCGplayer groups cache."""
    print("Fetching TCGplayer Magic groups...")
    groups = fetch_magic_groups()
    if groups:
        save_groups_cache(cache_path, groups)
        print(f"Groups cache updated: {cache_path}")
    else:
        print("Warning: No groups were fetched")


def update_all_data(db_path: pathlib.Path = DEFAULT_DB_PATH) -> None:
    """Update both TCGplayer card IDs and group mappings (for new set releases)."""
    print("=" * 60)
    print("Updating all data: TCGplayer IDs and Magic group mappings...")
    print("=" * 60)
    update_database(db_path)
    print()
    update_groups_cache()
    print("=" * 60)
    print("All data updated successfully!")
    print("=" * 60)


def load_database(db_path: pathlib.Path) -> dict:
    if not db_path.exists():
        raise FileNotFoundError(
            f"Database not found at {db_path}. Run update-db first to create it."
        )
    with db_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


@dataclass
class CardMetadata:
    tcgplayer_id: int
    name: str
    set_code: str
    set_name: str
    rarity: str
    match_reason: str
    collector_number: str = ""


def lookup_card_metadata(db: dict, row: dict) -> Optional[CardMetadata]:
    finish = normalize_finish(row.get("Finish", ""))
    scryfall_id = (row.get("Scryfall ID", "") or "").strip().lower()
    if scryfall_id:
        entry = db.get("by_scryfall_id", {}).get(scryfall_id)
        if isinstance(entry, dict):
            pid = safe_int(entry.get(finish) or entry.get("normal"))
            if pid is not None:
                return CardMetadata(
                    tcgplayer_id=pid,
                    name=entry.get("name", ""),
                    set_code=entry.get("set_code", ""),
                    set_name=entry.get("set_name", ""),
                    rarity=entry.get("rarity", ""),
                    match_reason="scryfall_id",
                )

    set_code = (row.get("Set code", "") or "").strip().lower()
    collector = normalize_collector_number(row.get("Collector number", "") or "")
    if set_code and collector:
        key = f"{set_code}|{collector}|{finish}"
        entry = db.get("by_set_collector_finish", {}).get(key)
        if isinstance(entry, dict):
            pid = safe_int(entry.get(finish) or entry.get("normal"))
            if pid is not None:
                return CardMetadata(
                    tcgplayer_id=pid,
                    name=entry.get("name", ""),
                    set_code=entry.get("set_code", ""),
                    set_name=entry.get("set_name", ""),
                    rarity=entry.get("rarity", ""),
                    match_reason="set_collector_finish",
                )

    name = (row.get("Name", "") or "").strip().lower()
    if name and set_code and collector:
        key = f"{name}|{set_code}|{collector}|{finish}"
        entry = db.get("by_name_set_number_finish", {}).get(key)
        if isinstance(entry, dict):
            pid = safe_int(entry.get(finish) or entry.get("normal"))
            if pid is not None:
                return CardMetadata(
                    tcgplayer_id=pid,
                    name=entry.get("name", ""),
                    set_code=entry.get("set_code", ""),
                    set_name=entry.get("set_name", ""),
                    rarity=entry.get("rarity", ""),
                    match_reason="name_set_collector_finish",
                )

    return None


def lookup_tcgplayer_id(db: dict, row: dict) -> CardLookupResult:
    """Legacy lookup for backward compatibility."""
    metadata = lookup_card_metadata(db, row)
    if metadata is not None:
        return CardLookupResult(metadata.tcgplayer_id, metadata.match_reason)
    return CardLookupResult(None, "unmatched")


def build_output_row(
    profile: str,
    source_row: dict,
    tcgplayer_id: int,
    quantity: str,
    condition: str,
    language: str,
    metadata: Optional[CardMetadata] = None,
    price: Optional[float] = None,
) -> dict:
    resolved_price = price if price is not None else DEFAULT_FALLBACK_PRICE

    if profile in {"minimum", "seller_blank_3"}:
        price_str = f"{resolved_price:.2f}"
        return {
            "TCGplayer Id": tcgplayer_id,
            "Product Line": "",
            "Set Name": "",
            "Product Name": "",
            "Title": "",
            "Number": "",
            "Rarity": "",
            "Condition": "",
            "TCG Market Price": price_str,
            "TCG Direct Low": "",
            "TCG Low Price With Shipping": "",
            "TCG Low Price": "",
            "Total Quantity": "",
            "Add to Quantity": quantity,
            "TCG Marketplace Price": price_str,
            "Photo URL": "",
        }

    if profile in {"minimal", "upload_safe"}:
        return {
            "TCGplayer Id": tcgplayer_id,
            "Add to Quantity": quantity,
        }

    if profile == "id_qty_price":
        price_str = f"{resolved_price:.2f}"
        return {
            "TCGplayer Id": tcgplayer_id,
            "Add to Quantity": quantity,
            "Price": price_str,
        }

    if profile in {"detailed", "tcgplayer_seller"}:
        price_str = f"{resolved_price:.2f}"
        output_number = ""
        if metadata is not None and metadata.collector_number:
            output_number = metadata.collector_number
        else:
            output_number = normalize_collector_number(source_row.get("Collector number", "") or "")
        return {
            "TCGplayer Id": tcgplayer_id,
            "Product Line": "Magic",
            "Set Name": metadata.set_name if metadata else "",
            "Product Name": metadata.name if metadata else source_row.get("Name", ""),
            "Title": "",
            "Number": output_number,
            "Rarity": metadata.rarity if metadata else "",
            "Condition": condition,
            "TCG Market Price": price_str,
            "TCG Direct Low": "",
            "TCG Low Price With Shipping": "",
            "TCG Low Price": "",
            "Total Quantity": "",
            "Add to Quantity": quantity,
            "TCG Marketplace Price": price_str,
            "Photo URL": "",
        }

    return {
        "TCGplayer Id": tcgplayer_id,
        "Product Name": source_row.get("Name", ""),
        "Set Code": source_row.get("Set code", ""),
        "Collector Number": source_row.get("Collector number", ""),
        "Printing": normalize_finish(source_row.get("Finish", "")).title(),
        "Condition": condition,
        "Language": language,
        "Add to Quantity": quantity,
    }


def output_headers(profile: str) -> List[str]:
    if profile in {"minimum", "seller_blank_3"}:
        return [
            "TCGplayer Id",
            "Product Line",
            "Set Name",
            "Product Name",
            "Title",
            "Number",
            "Rarity",
            "Condition",
            "TCG Market Price",
            "TCG Direct Low",
            "TCG Low Price With Shipping",
            "TCG Low Price",
            "Total Quantity",
            "Add to Quantity",
            "TCG Marketplace Price",
            "Photo URL",
        ]

    if profile in {"minimal", "upload_safe"}:
        return ["TCGplayer Id", "Add to Quantity"]
    if profile == "id_qty_price":
        return ["TCGplayer Id", "Add to Quantity", "Price"]
    if profile in {"detailed", "tcgplayer_seller"}:
        return [
            "TCGplayer Id",
            "Product Line",
            "Set Name",
            "Product Name",
            "Title",
            "Number",
            "Rarity",
            "Condition",
            "TCG Market Price",
            "TCG Direct Low",
            "TCG Low Price With Shipping",
            "TCG Low Price",
            "Total Quantity",
            "Add to Quantity",
            "TCG Marketplace Price",
            "Photo URL",
        ]
    return [
        "TCGplayer Id",
        "Product Name",
        "Set Code",
        "Collector Number",
        "Printing",
        "Condition",
        "Language",
        "Add to Quantity",
    ]


def prepare_pricing_for_input(input_path: pathlib.Path) -> Dict[str, Dict[str, Optional[float]]]:
    """Ensure pricing data is loaded for all sets used by the input file."""
    groups_mapping = load_groups_cache(DEFAULT_GROUPS_CACHE_PATH)
    if not groups_mapping:
        print("Fetching TCGplayer Magic group IDs...")
        groups_mapping = fetch_magic_groups()
        if groups_mapping:
            save_groups_cache(DEFAULT_GROUPS_CACHE_PATH, groups_mapping)

    set_codes_needed = set()
    with input_path.open("r", encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        for row in reader:
            set_code = (row.get("Set code", "") or "").strip().lower()
            if set_code:
                set_codes_needed.add(set_code)

    price_cache = load_price_cache(DEFAULT_PRICE_CACHE_PATH)
    sets_to_fetch = [s for s in set_codes_needed if s not in price_cache]
    if sets_to_fetch:
        print(f"Fetching prices for {len(sets_to_fetch)} set(s)...")
        for set_code in sets_to_fetch:
            group_id = groups_mapping.get(set_code)
            if group_id:
                prices = fetch_prices_for_group(group_id)
                if prices:
                    price_cache[set_code] = prices
                    print(f"  {set_code}: {len(prices)} prices")
                else:
                    price_cache[set_code] = {}
            else:
                price_cache[set_code] = {}
        save_price_cache(DEFAULT_PRICE_CACHE_PATH, price_cache)

    return price_cache


def convert_rows_for_file(
    db: dict,
    input_path: pathlib.Path,
    profile: str,
    condition: str,
    language: str,
    skip_unmatched: bool,
    price_cache: Dict[str, Dict[str, Optional[float]]],
    seller_product_index: Optional[Dict[Tuple[str, str, str], dict]] = None,
    seller_product_index_set_collector_unique: Optional[Dict[Tuple[str, str], dict]] = None,
    seller_export_set_number_name: Optional[Dict[Tuple[str, str, str], int]] = None,
    seller_export_set_number_name_condition: Optional[Dict[Tuple[str, str, str, str], int]] = None,
    seller_export_number_name_unique: Optional[Dict[Tuple[str, str], int]] = None,
    seller_export_number_name_condition_unique: Optional[Dict[Tuple[str, str, str], int]] = None,
    seller_export_set_number_unique: Optional[Dict[Tuple[str, str], int]] = None,
    seller_export_set_number_condition_unique: Optional[Dict[Tuple[str, str, str], int]] = None,
    seller_export_set_name_unique: Optional[Dict[Tuple[str, str], int]] = None,
    seller_export_set_name_condition_unique: Optional[Dict[Tuple[str, str, str], int]] = None,
    seller_export_name_unique: Optional[Dict[str, int]] = None,
    seller_export_name_condition_unique: Optional[Dict[Tuple[str, str], int]] = None,
    set_code_to_name: Optional[Dict[str, str]] = None,
) -> Tuple[List[dict], List[dict]]:
    output_rows: List[dict] = []
    unmatched_rows: List[dict] = []
    seller_matches = 0
    seller_export_matches = 0
    scryfall_fallback_matches = 0
    strict_seller_ids = (
        seller_export_set_number_name is not None
        and seller_export_set_number_name_condition is not None
        and seller_export_number_name_unique is not None
        and seller_export_number_name_condition_unique is not None
        and seller_export_set_number_unique is not None
        and seller_export_set_number_condition_unique is not None
        and seller_export_set_name_unique is not None
        and seller_export_set_name_condition_unique is not None
        and seller_export_name_unique is not None
        and seller_export_name_condition_unique is not None
    )

    with input_path.open("r", encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        required = {"Name", "Set code", "Collector number", "Finish", "Quantity", "Scryfall ID"}
        missing = sorted(required.difference(set(reader.fieldnames or [])))
        if missing:
            raise ValueError(
                f"Input file {input_path} is missing required columns: {', '.join(missing)}"
            )

        for row in reader:
            quantity_raw = (row.get("Quantity", "") or "").strip()
            quantity_value = re.sub(r"[^0-9]", "", quantity_raw) or "0"

            base_metadata = lookup_card_metadata(db, row)
            seller_metadata = (
                lookup_seller_product(seller_product_index, seller_product_index_set_collector_unique or {}, row)
                if seller_product_index is not None
                else None
            )

            metadata: Optional[CardMetadata] = None

            if (
                seller_export_set_number_name is not None
                and seller_export_set_number_name_condition is not None
                and seller_export_number_name_unique is not None
                and seller_export_number_name_condition_unique is not None
                and seller_export_set_number_unique is not None
                and seller_export_set_number_condition_unique is not None
                and seller_export_set_name_unique is not None
                and seller_export_set_name_condition_unique is not None
                and seller_export_name_unique is not None
                and seller_export_name_condition_unique is not None
                and set_code_to_name is not None
            ):
                seller_export_id = lookup_seller_export_id(
                    row=row,
                    metadata=base_metadata,
                    selected_condition=condition,
                    set_code_to_name=set_code_to_name,
                    by_set_number_name=seller_export_set_number_name,
                    by_set_number_name_condition=seller_export_set_number_name_condition,
                    by_number_name_unique=seller_export_number_name_unique,
                    by_number_name_condition_unique=seller_export_number_name_condition_unique,
                    by_set_number_unique=seller_export_set_number_unique,
                    by_set_number_condition_unique=seller_export_set_number_condition_unique,
                    by_set_name_unique=seller_export_set_name_unique,
                    by_set_name_condition_unique=seller_export_set_name_condition_unique,
                    by_name_unique=seller_export_name_unique,
                    by_name_condition_unique=seller_export_name_condition_unique,
                )
                if seller_export_id is not None:
                    seller_export_matches += 1
                    enriched = seller_metadata or base_metadata
                    metadata = CardMetadata(
                        tcgplayer_id=seller_export_id,
                        name=(enriched.name if enriched is not None else row.get("Name", "")),
                        set_code=(
                            enriched.set_code
                            if enriched is not None
                            else (row.get("Set code", "") or "").strip().lower()
                        ),
                        set_name=(
                            enriched.set_name
                            if enriched is not None
                            else set_code_to_name.get((row.get("Set code", "") or "").strip().lower(), "")
                        ),
                        rarity=enriched.rarity if enriched is not None else "",
                        match_reason="pricing_custom_export",
                    )

            # Priority after pricing_custom: seller catalog IDs, then legacy DB fallback.
            if metadata is None and seller_metadata is not None:
                seller_matches += 1
                if base_metadata is not None:
                    metadata = CardMetadata(
                        tcgplayer_id=seller_metadata.tcgplayer_id,
                        name=base_metadata.name or seller_metadata.name,
                        set_code=base_metadata.set_code or seller_metadata.set_code,
                        set_name=base_metadata.set_name or seller_metadata.set_name,
                        rarity=base_metadata.rarity or seller_metadata.rarity,
                        match_reason=seller_metadata.match_reason,
                        collector_number=base_metadata.collector_number or seller_metadata.collector_number,
                    )
                else:
                    metadata = seller_metadata

            if metadata is None and base_metadata is not None and not strict_seller_ids:
                scryfall_fallback_matches += 1
                metadata = base_metadata

            if metadata is None:
                issue_row = dict(row)
                issue_row["_reason"] = "No TCGplayer ID match"
                unmatched_rows.append(issue_row)
                if skip_unmatched:
                    continue
                raise ValueError(
                    f"Could not match row: Name={row.get('Name')} Set={row.get('Set code')} "
                    f"Collector={row.get('Collector number')} Finish={row.get('Finish')}"
                )

            set_code_lower = (row.get("Set code", "") or "").strip().lower()
            set_prices = price_cache.get(set_code_lower, {})
            price_candidates: List[str] = [str(metadata.tcgplayer_id)]
            if seller_metadata is not None:
                price_candidates.append(str(seller_metadata.tcgplayer_id))
            if base_metadata is not None:
                price_candidates.append(str(base_metadata.tcgplayer_id))

            card_price: Optional[float] = None
            for pid in dict.fromkeys(price_candidates):
                if pid in set_prices:
                    card_price = set_prices.get(pid)
                    break

            output_rows.append(
                build_output_row(
                    profile=profile,
                    source_row=row,
                    tcgplayer_id=metadata.tcgplayer_id,
                    quantity=quantity_value,
                    condition=condition,
                    language=language,
                    metadata=metadata,
                    price=card_price,
                )
            )

    print(
        f"ID source usage: pricing_custom_export={seller_export_matches}, "
        f"tcgcsv_products={seller_matches}, "
        f"scryfall_fallback={scryfall_fallback_matches}"
    )

    return output_rows, unmatched_rows


def write_output_csv(profile: str, output_path: pathlib.Path, rows: List[dict]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=output_headers(profile))
        writer.writeheader()
        writer.writerows(rows)


def _to_int(value: object) -> int:
    text = str(value or "").strip()
    if not text:
        return 0
    try:
        return int(text)
    except ValueError:
        return 0


def dedupe_output_rows(profile: str, rows: List[dict]) -> List[dict]:
    """Deduplicate rows and sum quantity columns for combined outputs."""
    if not rows:
        return rows

    if profile in {"minimal", "upload_safe", "id_qty_price", "minimum", "seller_blank_3"}:
        key_fields = ["TCGplayer Id"]
    elif profile in {"detailed", "tcgplayer_seller"}:
        key_fields = [
            "TCGplayer Id",
            "Condition",
        ]
    else:
        key_fields = [
            "TCGplayer Id",
            "Condition",
            "Language",
        ]

    grouped: Dict[Tuple[str, ...], dict] = {}
    ordered_keys: List[Tuple[str, ...]] = []
    for row in rows:
        key = tuple(str(row.get(field, "")) for field in key_fields)
        existing = grouped.get(key)
        if existing is None:
            grouped[key] = dict(row)
            ordered_keys.append(key)
            continue

        existing["Add to Quantity"] = str(
            _to_int(existing.get("Add to Quantity")) + _to_int(row.get("Add to Quantity"))
        )
        if "Total Quantity" in existing:
            existing["Total Quantity"] = str(
                _to_int(existing.get("Total Quantity")) + _to_int(row.get("Total Quantity"))
            )

    return [grouped[key] for key in ordered_keys]


def convert_file(
    db: dict,
    input_path: pathlib.Path,
    output_path: pathlib.Path,
    unmatched_path: Optional[pathlib.Path],
    profile: str,
    condition: str,
    language: str,
    skip_unmatched: bool,
) -> None:
    price_cache = prepare_pricing_for_input(input_path)
    seller_product_index, seller_product_index_set_collector_unique = prepare_seller_product_index_for_input(input_path)
    set_code_to_name = fetch_magic_group_names()
    seller_export_set_number_name: Optional[Dict[Tuple[str, str, str], int]] = None
    seller_export_set_number_name_condition: Optional[Dict[Tuple[str, str, str, str], int]] = None
    seller_export_number_name_unique: Optional[Dict[Tuple[str, str], int]] = None
    seller_export_number_name_condition_unique: Optional[Dict[Tuple[str, str, str], int]] = None
    seller_export_set_number_unique: Optional[Dict[Tuple[str, str], int]] = None
    seller_export_set_number_condition_unique: Optional[Dict[Tuple[str, str, str], int]] = None
    seller_export_set_name_unique: Optional[Dict[Tuple[str, str], int]] = None
    seller_export_set_name_condition_unique: Optional[Dict[Tuple[str, str, str], int]] = None
    seller_export_name_unique: Optional[Dict[str, int]] = None
    seller_export_name_condition_unique: Optional[Dict[Tuple[str, str], int]] = None
    seller_export_path = detect_seller_export_file(input_path)
    if seller_export_path is not None:
        (
            seller_export_set_number_name,
            seller_export_set_number_name_condition,
            seller_export_number_name_unique,
            seller_export_number_name_condition_unique,
            seller_export_set_number_unique,
            seller_export_set_number_condition_unique,
            seller_export_set_name_unique,
            seller_export_set_name_condition_unique,
            seller_export_name_unique,
            seller_export_name_condition_unique,
            _,
        ) = load_seller_export_index(seller_export_path)
        print(f"Using pricing_custom export: {seller_export_path}")
    else:
        print("No pricing_custom export found; falling back to online/local mapping.")
    output_rows, unmatched_rows = convert_rows_for_file(
        db=db,
        input_path=input_path,
        profile=profile,
        condition=condition,
        language=language,
        skip_unmatched=skip_unmatched,
        price_cache=price_cache,
        seller_product_index=seller_product_index,
        seller_product_index_set_collector_unique=seller_product_index_set_collector_unique,
        seller_export_set_number_name=seller_export_set_number_name,
        seller_export_set_number_name_condition=seller_export_set_number_name_condition,
        seller_export_number_name_unique=seller_export_number_name_unique,
        seller_export_number_name_condition_unique=seller_export_number_name_condition_unique,
        seller_export_set_number_unique=seller_export_set_number_unique,
        seller_export_set_number_condition_unique=seller_export_set_number_condition_unique,
        seller_export_set_name_unique=seller_export_set_name_unique,
        seller_export_set_name_condition_unique=seller_export_set_name_condition_unique,
        seller_export_name_unique=seller_export_name_unique,
        seller_export_name_condition_unique=seller_export_name_condition_unique,
        set_code_to_name=set_code_to_name,
    )

    write_output_csv(profile, output_path, output_rows)

    if unmatched_path and unmatched_rows:
        unmatched_path.parent.mkdir(parents=True, exist_ok=True)
        headers = list(unmatched_rows[0].keys())
        with unmatched_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=headers)
            writer.writeheader()
            writer.writerows(unmatched_rows)

    save_price_cache(DEFAULT_PRICE_CACHE_PATH, price_cache)

    print(f"Converted: {input_path} -> {output_path}")
    print(f"Rows written: {len(output_rows)}")
    print(f"Rows unmatched: {len(unmatched_rows)}")
    if unmatched_path and unmatched_rows:
        print(f"Unmatched report: {unmatched_path}")

    if profile == "tcgplayer_seller":
        unpriced_cards = [
            (row.get("Product Name", ""), row.get("Set Name", ""))
            for row in output_rows
            if not (row.get("TCG Market Price", "") or "").strip()
        ]
        if unpriced_cards:
            print(f"\nWarning: {len(unpriced_cards)} card(s) without pricing:")
            for card_name, set_name in unpriced_cards[:10]:
                print(f"  - {card_name} ({set_name})")
            if len(unpriced_cards) > 10:
                print(f"  ... and {len(unpriced_cards) - 10} more")


def iter_csv_files(input_dir: pathlib.Path, pattern: str) -> Iterable[pathlib.Path]:
    for path in sorted(input_dir.glob(pattern)):
        if path.is_file():
            lower_name = path.name.lower()
            if lower_name.endswith(".tcgplayer.csv") or lower_name.endswith(".unmatched.csv"):
                continue
            yield path


def run_batch(
    db: dict,
    input_dir: pathlib.Path,
    output_dir: Optional[pathlib.Path],
    pattern: str,
    profile: str,
    condition: str,
    language: str,
    skip_unmatched: bool,
    combined_output_path: Optional[pathlib.Path] = None,
    combined_unmatched_path: Optional[pathlib.Path] = None,
    dedupe_combined: bool = False,
) -> None:
    files = list(iter_csv_files(input_dir, pattern))
    if not files:
        print(
            "No input files found for batch conversion "
            f"(input_dir={input_dir}, pattern={pattern})."
        )
        print(
            "Note: files ending with .tcgplayer.csv and .unmatched.csv are skipped "
            "to avoid re-processing outputs."
        )
        return

    if combined_output_path is None and output_dir is None:
        raise ValueError("Output directory is required unless --combined-output is provided.")

    if combined_output_path is None and output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)

    combined_rows: List[dict] = []
    combined_unmatched_rows: List[dict] = []

    converted = 0
    for src in files:
        try:
            price_cache = prepare_pricing_for_input(src)
            seller_product_index, seller_product_index_set_collector_unique = prepare_seller_product_index_for_input(src)
            set_code_to_name = fetch_magic_group_names()
            seller_export_set_number_name: Optional[Dict[Tuple[str, str, str], int]] = None
            seller_export_set_number_name_condition: Optional[Dict[Tuple[str, str, str, str], int]] = None
            seller_export_number_name_unique: Optional[Dict[Tuple[str, str], int]] = None
            seller_export_number_name_condition_unique: Optional[Dict[Tuple[str, str, str], int]] = None
            seller_export_set_number_unique: Optional[Dict[Tuple[str, str], int]] = None
            seller_export_set_number_condition_unique: Optional[Dict[Tuple[str, str, str], int]] = None
            seller_export_set_name_unique: Optional[Dict[Tuple[str, str], int]] = None
            seller_export_set_name_condition_unique: Optional[Dict[Tuple[str, str, str], int]] = None
            seller_export_name_unique: Optional[Dict[str, int]] = None
            seller_export_name_condition_unique: Optional[Dict[Tuple[str, str], int]] = None
            seller_export_path = detect_seller_export_file(src)
            if seller_export_path is not None:
                (
                    seller_export_set_number_name,
                    seller_export_set_number_name_condition,
                    seller_export_number_name_unique,
                    seller_export_number_name_condition_unique,
                    seller_export_set_number_unique,
                    seller_export_set_number_condition_unique,
                    seller_export_set_name_unique,
                    seller_export_set_name_condition_unique,
                    seller_export_name_unique,
                    seller_export_name_condition_unique,
                    _,
                ) = load_seller_export_index(seller_export_path)
                print(f"Using pricing_custom export: {seller_export_path}")
            else:
                print("No pricing_custom export found; falling back to online/local mapping.")
            output_rows, unmatched_rows = convert_rows_for_file(
                db=db,
                input_path=src,
                profile=profile,
                condition=condition,
                language=language,
                skip_unmatched=skip_unmatched,
                price_cache=price_cache,
                seller_product_index=seller_product_index,
                seller_product_index_set_collector_unique=seller_product_index_set_collector_unique,
                seller_export_set_number_name=seller_export_set_number_name,
                seller_export_set_number_name_condition=seller_export_set_number_name_condition,
                seller_export_number_name_unique=seller_export_number_name_unique,
                seller_export_number_name_condition_unique=seller_export_number_name_condition_unique,
                seller_export_set_number_unique=seller_export_set_number_unique,
                seller_export_set_number_condition_unique=seller_export_set_number_condition_unique,
                seller_export_set_name_unique=seller_export_set_name_unique,
                seller_export_set_name_condition_unique=seller_export_set_name_condition_unique,
                seller_export_name_unique=seller_export_name_unique,
                seller_export_name_condition_unique=seller_export_name_condition_unique,
                set_code_to_name=set_code_to_name,
            )

            if combined_output_path is not None:
                combined_rows.extend(output_rows)
                for unmatched in unmatched_rows:
                    tagged = dict(unmatched)
                    tagged["_source_file"] = str(src)
                    combined_unmatched_rows.append(tagged)
                print(f"Converted for combined output: {src} ({len(output_rows)} rows)")
            else:
                out_name = f"{src.stem}.tcgplayer.csv"
                unmatched_name = f"{src.stem}.unmatched.csv"
                output_path = output_dir / out_name
                unmatched_path = output_dir / unmatched_name
                write_output_csv(profile, output_path, output_rows)
                if unmatched_rows:
                    unmatched_path.parent.mkdir(parents=True, exist_ok=True)
                    headers = list(unmatched_rows[0].keys())
                    with unmatched_path.open("w", encoding="utf-8", newline="") as handle:
                        writer = csv.DictWriter(handle, fieldnames=headers)
                        writer.writeheader()
                        writer.writerows(unmatched_rows)
                print(f"Converted: {src} -> {output_path}")
                print(f"Rows written: {len(output_rows)}")
                print(f"Rows unmatched: {len(unmatched_rows)}")

            save_price_cache(DEFAULT_PRICE_CACHE_PATH, price_cache)
            converted += 1
        except Exception as exc:  # pragma: no cover - CLI level reporting
            print(f"Failed on {src}: {exc}", file=sys.stderr)

    if combined_output_path is not None:
        if dedupe_combined:
            combined_rows = dedupe_output_rows(profile, combined_rows)
        write_output_csv(profile, combined_output_path, combined_rows)
        print(f"Combined output written: {combined_output_path}")
        print(f"Combined rows written: {len(combined_rows)}")
        print(f"Combined rows unmatched: {len(combined_unmatched_rows)}")
        if combined_unmatched_path and combined_unmatched_rows:
            combined_unmatched_path.parent.mkdir(parents=True, exist_ok=True)
            headers = list(combined_unmatched_rows[0].keys())
            with combined_unmatched_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=headers)
                writer.writeheader()
                writer.writerows(combined_unmatched_rows)
            print(f"Combined unmatched report: {combined_unmatched_path}")

        if profile == "tcgplayer_seller":
            unpriced_cards = [
                (row.get("Product Name", ""), row.get("Set Name", ""))
                for row in combined_rows
                if not (row.get("TCG Market Price", "") or "").strip()
            ]
            if unpriced_cards:
                print(f"\nWarning: {len(unpriced_cards)} card(s) without pricing:")
                for card_name, set_name in unpriced_cards[:10]:
                    print(f"  - {card_name} ({set_name})")
                if len(unpriced_cards) > 10:
                    print(f"  ... and {len(unpriced_cards) - 10} more")

    print(f"Batch complete. Files converted: {converted}/{len(files)}")


def run_combine_files(
    db: dict,
    input_files: List[pathlib.Path],
    combined_output_path: pathlib.Path,
    profile: str,
    condition: str,
    language: str,
    skip_unmatched: bool,
    combined_unmatched_path: Optional[pathlib.Path] = None,
    dedupe: bool = False,
) -> None:
    files = [path for path in input_files if path.is_file()]
    if not files:
        raise ValueError("No valid input files were provided.")

    combined_rows: List[dict] = []
    combined_unmatched_rows: List[dict] = []
    converted = 0

    for src in files:
        try:
            price_cache = prepare_pricing_for_input(src)
            seller_product_index, seller_product_index_set_collector_unique = prepare_seller_product_index_for_input(src)
            set_code_to_name = fetch_magic_group_names()
            seller_export_set_number_name: Optional[Dict[Tuple[str, str, str], int]] = None
            seller_export_set_number_name_condition: Optional[Dict[Tuple[str, str, str, str], int]] = None
            seller_export_number_name_unique: Optional[Dict[Tuple[str, str], int]] = None
            seller_export_number_name_condition_unique: Optional[Dict[Tuple[str, str, str], int]] = None
            seller_export_set_number_unique: Optional[Dict[Tuple[str, str], int]] = None
            seller_export_set_number_condition_unique: Optional[Dict[Tuple[str, str, str], int]] = None
            seller_export_set_name_unique: Optional[Dict[Tuple[str, str], int]] = None
            seller_export_set_name_condition_unique: Optional[Dict[Tuple[str, str, str], int]] = None
            seller_export_name_unique: Optional[Dict[str, int]] = None
            seller_export_name_condition_unique: Optional[Dict[Tuple[str, str], int]] = None
            seller_export_path = detect_seller_export_file(src)
            if seller_export_path is not None:
                (
                    seller_export_set_number_name,
                    seller_export_set_number_name_condition,
                    seller_export_number_name_unique,
                    seller_export_number_name_condition_unique,
                    seller_export_set_number_unique,
                    seller_export_set_number_condition_unique,
                    seller_export_set_name_unique,
                    seller_export_set_name_condition_unique,
                    seller_export_name_unique,
                    seller_export_name_condition_unique,
                    _,
                ) = load_seller_export_index(seller_export_path)
                print(f"Using pricing_custom export: {seller_export_path}")
            else:
                print("No pricing_custom export found; falling back to online/local mapping.")
            output_rows, unmatched_rows = convert_rows_for_file(
                db=db,
                input_path=src,
                profile=profile,
                condition=condition,
                language=language,
                skip_unmatched=skip_unmatched,
                price_cache=price_cache,
                seller_product_index=seller_product_index,
                seller_product_index_set_collector_unique=seller_product_index_set_collector_unique,
                seller_export_set_number_name=seller_export_set_number_name,
                seller_export_set_number_name_condition=seller_export_set_number_name_condition,
                seller_export_number_name_unique=seller_export_number_name_unique,
                seller_export_number_name_condition_unique=seller_export_number_name_condition_unique,
                seller_export_set_number_unique=seller_export_set_number_unique,
                seller_export_set_number_condition_unique=seller_export_set_number_condition_unique,
                seller_export_set_name_unique=seller_export_set_name_unique,
                seller_export_set_name_condition_unique=seller_export_set_name_condition_unique,
                seller_export_name_unique=seller_export_name_unique,
                seller_export_name_condition_unique=seller_export_name_condition_unique,
                set_code_to_name=set_code_to_name,
            )
            combined_rows.extend(output_rows)
            for unmatched in unmatched_rows:
                tagged = dict(unmatched)
                tagged["_source_file"] = str(src)
                combined_unmatched_rows.append(tagged)
            save_price_cache(DEFAULT_PRICE_CACHE_PATH, price_cache)
            converted += 1
            print(f"Converted for combined output: {src} ({len(output_rows)} rows)")
        except Exception as exc:
            print(f"Failed on {src}: {exc}", file=sys.stderr)

    if dedupe:
        combined_rows = dedupe_output_rows(profile, combined_rows)

    write_output_csv(profile, combined_output_path, combined_rows)
    print(f"Combined output written: {combined_output_path}")
    print(f"Combined rows written: {len(combined_rows)}")
    print(f"Combined rows unmatched: {len(combined_unmatched_rows)}")
    if combined_unmatched_path and combined_unmatched_rows:
        combined_unmatched_path.parent.mkdir(parents=True, exist_ok=True)
        headers = list(combined_unmatched_rows[0].keys())
        with combined_unmatched_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=headers)
            writer.writeheader()
            writer.writerows(combined_unmatched_rows)
        print(f"Combined unmatched report: {combined_unmatched_path}")

    if profile == "tcgplayer_seller":
        unpriced_cards = [
            (row.get("Product Name", ""), row.get("Set Name", ""))
            for row in combined_rows
            if not (row.get("TCG Market Price", "") or "").strip()
        ]
        if unpriced_cards:
            print(f"\nWarning: {len(unpriced_cards)} card(s) without pricing:")
            for card_name, set_name in unpriced_cards[:10]:
                print(f"  - {card_name} ({set_name})")
            if len(unpriced_cards) > 10:
                print(f"  ... and {len(unpriced_cards) - 10} more")


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="tcg_csv_converter",
        description="Update MTG TCGplayer IDs and convert collection CSV files.",
    )
    parser.add_argument(
        "--db",
        default=str(DEFAULT_DB_PATH),
        help="Path to local JSON ID database file.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("update-db", help="Refresh local TCGplayer ID database from Scryfall.")

    convert = subparsers.add_parser("convert", help="Convert one input CSV file.")
    convert.add_argument("--input", required=True, help="Source collection CSV path.")
    convert.add_argument("--output", required=True, help="Converted CSV output path.")
    convert.add_argument(
        "--unmatched-output",
        default="",
        help="Optional unmatched row report CSV path.",
    )
    convert.add_argument(
        "--profile",
        choices=["minimum", "detailed"],
        default="minimum",
        help="Output schema profile.",
    )
    convert.add_argument("--condition", default="Lightly Played", help="Default card condition for output.")
    convert.add_argument("--language", default="English", help="Default card language for output.")
    convert.add_argument(
        "--skip-unmatched",
        action="store_true",
        help="Skip unmatched cards instead of stopping conversion.",
    )

    batch = subparsers.add_parser("batch", help="Convert many CSV files in one run.")
    batch.add_argument("--input-dir", required=True, help="Directory with source CSV files.")
    batch.add_argument("--output-dir", default="", help="Directory for converted files.")
    batch.add_argument(
        "--combined-output",
        default="",
        help="Optional single CSV output path that combines all converted rows.",
    )
    batch.add_argument(
        "--combined-unmatched-output",
        default="",
        help="Optional unmatched row report path for combined output mode.",
    )
    batch.add_argument("--pattern", default="*.csv", help="Glob pattern for source files.")
    batch.add_argument(
        "--profile",
        choices=["minimum", "detailed"],
        default="minimum",
        help="Output schema profile.",
    )
    batch.add_argument("--condition", default="Lightly Played", help="Default card condition for output.")
    batch.add_argument("--language", default="English", help="Default card language for output.")
    batch.add_argument(
        "--skip-unmatched",
        action="store_true",
        help="Skip unmatched cards instead of stopping conversion.",
    )
    batch.add_argument(
        "--dedupe",
        action="store_true",
        help="When using combined output, merge duplicate cards and sum quantities.",
    )

    combine = subparsers.add_parser("combine", help="Combine selected CSV files into one output CSV.")
    combine.add_argument(
        "--inputs",
        nargs="+",
        required=True,
        help="Specific source CSV files to combine.",
    )
    combine.add_argument("--output", required=True, help="Combined CSV output path.")
    combine.add_argument(
        "--unmatched-output",
        default="",
        help="Optional unmatched row report CSV path for combined mode.",
    )
    combine.add_argument(
        "--profile",
        choices=["minimum", "detailed"],
        default="minimum",
        help="Output schema profile.",
    )
    combine.add_argument("--condition", default="Lightly Played", help="Default card condition for output.")
    combine.add_argument("--language", default="English", help="Default card language for output.")
    combine.add_argument(
        "--skip-unmatched",
        action="store_true",
        help="Skip unmatched cards instead of stopping conversion.",
    )
    combine.add_argument(
        "--dedupe",
        action="store_true",
        help="Merge duplicate cards in combined output and sum quantities.",
    )

    return parser.parse_args(argv)


def main(argv: List[str]) -> int:
    args = parse_args(argv)
    db_path = pathlib.Path(args.db)

    try:
        if args.command == "update-db":
            update_database(db_path)
            return 0

        db = load_database(db_path)

        if args.command == "convert":
            unmatched = pathlib.Path(args.unmatched_output) if args.unmatched_output else None
            convert_file(
                db=db,
                input_path=pathlib.Path(args.input),
                output_path=pathlib.Path(args.output),
                unmatched_path=unmatched,
                profile=args.profile,
                condition=args.condition,
                language=args.language,
                skip_unmatched=args.skip_unmatched,
            )
            return 0

        if args.command == "batch":
            output_dir = pathlib.Path(args.output_dir) if args.output_dir else None
            combined_output = pathlib.Path(args.combined_output) if args.combined_output else None
            combined_unmatched = (
                pathlib.Path(args.combined_unmatched_output)
                if args.combined_unmatched_output
                else None
            )
            run_batch(
                db=db,
                input_dir=pathlib.Path(args.input_dir),
                output_dir=output_dir,
                pattern=args.pattern,
                profile=args.profile,
                condition=args.condition,
                language=args.language,
                skip_unmatched=args.skip_unmatched,
                combined_output_path=combined_output,
                combined_unmatched_path=combined_unmatched,
                dedupe_combined=args.dedupe,
            )
            return 0

        if args.command == "combine":
            unmatched = pathlib.Path(args.unmatched_output) if args.unmatched_output else None
            run_combine_files(
                db=db,
                input_files=[pathlib.Path(p) for p in args.inputs],
                combined_output_path=pathlib.Path(args.output),
                combined_unmatched_path=unmatched,
                profile=args.profile,
                condition=args.condition,
                language=args.language,
                skip_unmatched=args.skip_unmatched,
                dedupe=args.dedupe,
            )
            return 0

        raise ValueError(f"Unsupported command: {args.command}")

    except urllib.error.URLError as exc:
        print(f"Network error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
