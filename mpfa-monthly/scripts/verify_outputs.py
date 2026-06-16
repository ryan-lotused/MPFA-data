from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path


RAW_FILENAME_RE = re.compile(r"consolidated_list_for_([a-z]{3})_(\d{2})_read_only\.xls$", re.I)
MONTH_ABBR = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")


def month_key_from_raw_filename(filename: str) -> str:
    match = RAW_FILENAME_RE.match(filename)
    if not match:
        raise ValueError(f"Unexpected raw workbook name: {filename}")
    month = MONTH_ABBR.index(match.group(1).lower()) + 1
    year = 2000 + int(match.group(2))
    return f"{year:04d}-{month:02d}"


def collect_raw_months(raw_dir: Path) -> set[str]:
    return {month_key_from_raw_filename(path.name) for path in raw_dir.glob("consolidated_list_for_*_read_only.xls")}


def collect_processed_months(processed_dir: Path, suffix: str) -> set[str]:
    return {path.name[:7] for path in processed_dir.glob(f"????-??_{suffix}.csv")}


def count_dash_prices(processed_dir: Path) -> int:
    dash_rows = 0
    for path in processed_dir.glob("*_prices.csv"):
        with path.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                if row.get("price_hkd", "").strip() == "--":
                    dash_rows += 1
    return dash_rows


def check_bid_offer_consistency(processed_dir: Path) -> tuple[int, int]:
    rows_with_bid_offer = 0
    mismatches = 0
    for path in processed_dir.glob("*_prices.csv"):
        with path.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                bid = row.get("bid_price_hkd", "").strip()
                offer = row.get("offer_price_hkd", "").strip()
                price = row.get("price_hkd", "").strip()
                if not bid and not offer:
                    continue
                rows_with_bid_offer += 1
                try:
                    avg = (float(bid) + float(offer)) / 2
                    if abs(float(price) - avg) > 1e-9:
                        mismatches += 1
                except ValueError:
                    mismatches += 1
    return rows_with_bid_offer, mismatches


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify MPFA raw and processed month coverage.")
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw"))
    parser.add_argument("--processed-dir", type=Path, default=Path("data/processed"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    raw_months = collect_raw_months(args.raw_dir)
    price_months = collect_processed_months(args.processed_dir, "prices")
    note_months = collect_processed_months(args.processed_dir, "notes")

    missing_price_months = sorted(raw_months - price_months)
    missing_note_months = sorted(raw_months - note_months)
    extra_price_months = sorted(price_months - raw_months)
    extra_note_months = sorted(note_months - raw_months)
    dash_rows = count_dash_prices(args.processed_dir)
    rows_with_bid_offer, bid_offer_mismatches = check_bid_offer_consistency(args.processed_dir)

    print(f"raw_months={len(raw_months)}")
    print(f"price_months={len(price_months)}")
    print(f"note_months={len(note_months)}")
    print(f"missing_price_months={missing_price_months}")
    print(f"missing_note_months={missing_note_months}")
    print(f"extra_price_months={extra_price_months}")
    print(f"extra_note_months={extra_note_months}")
    print(f"dash_price_rows={dash_rows}")
    print(f"rows_with_bid_offer={rows_with_bid_offer}")
    print(f"bid_offer_mismatches={bid_offer_mismatches}")

    if any(
        (
            missing_price_months,
            missing_note_months,
            extra_price_months,
            extra_note_months,
            dash_rows,
            bid_offer_mismatches,
        )
    ):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
