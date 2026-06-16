from __future__ import annotations

import argparse
import csv
import io
import re
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

import msoffcrypto
import xlrd


HEADER_DATE_RE = re.compile(r"as at\s+(\d{1,2}\.\d{1,2}\.\d{4})", re.I)
NOTE_CODE_RE = re.compile(r"^\s*(\d+)\s+(.*)$")
NOTE_SUBCODE_RE = re.compile(r"^\s*([a-z])\s+(.*)$", re.I)
DEFAULT_XLS_PASSWORD = "VelvetSweatshop"


@dataclass
class PriceRecord:
    source_file: str
    snapshot_date: str
    month_label: str
    trustee_en: str
    trustee_zh: str
    scheme_en: str
    scheme_zh: str
    fund_en: str
    fund_zh: str
    price_hkd: str
    bid_price_hkd: str
    offer_price_hkd: str
    notes_en: str
    notes_zh: str


@dataclass
class NoteRecord:
    source_file: str
    snapshot_date: str
    month_label: str
    note_code: str
    language: str
    text: str


def contains_cjk(value: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in value)


def normalize_text(value: object) -> str:
    if value is None:
        return ""
    text = str(value).replace("\xa0", " ").strip()
    return re.sub(r"\s+", " ", text)


def extract_snapshot_date(sheet: xlrd.sheet.Sheet) -> str:
    for row_index in range(min(sheet.nrows, 10)):
        for cell in sheet.row_values(row_index):
            text = normalize_text(cell)
            match = HEADER_DATE_RE.search(text)
            if match:
                day, month, year = map(int, match.group(1).split("."))
                return datetime(year, month, day).date().isoformat()
    raise ValueError("Could not find snapshot date in workbook header.")


def extract_month_label(sheet: xlrd.sheet.Sheet) -> str:
    value = normalize_text(sheet.cell_value(0, 0))
    match = re.search(r"\(([^)]+)\)", value)
    return match.group(1) if match else value


def find_note_start(sheet: xlrd.sheet.Sheet) -> int:
    for row_index in range(sheet.nrows):
        first_cell = normalize_text(sheet.cell_value(row_index, 0))
        if first_cell in {"Note:", "備註:"}:
            return row_index
    return sheet.nrows


def parse_price(value: object) -> str:
    if value in ("", None):
        return ""
    if isinstance(value, str):
        text = normalize_text(value)
        if text == "--":
            return ""
        return text
    if isinstance(value, float):
        return format(value, ".10g")
    return normalize_text(value)


def format_decimal(value: float) -> str:
    return format(value, ".10g")


def split_price_fields(raw_price: str) -> tuple[str, str, str]:
    if not raw_price:
        return "", "", ""
    if "/" not in raw_price:
        return raw_price, "", ""
    parts = [part.strip() for part in raw_price.split("/")]
    if len(parts) != 2:
        return raw_price, "", ""
    try:
        bid = float(parts[0])
        offer = float(parts[1])
    except ValueError:
        return raw_price, "", ""
    avg = (bid + offer) / 2
    return format_decimal(avg), format_decimal(bid), format_decimal(offer)


def open_workbook(path: Path) -> xlrd.book.Book:
    try:
        return xlrd.open_workbook(path.as_posix())
    except xlrd.biffh.XLRDError as error:
        if "encrypted" not in str(error).lower():
            raise
        with path.open("rb") as handle:
            office_file = msoffcrypto.OfficeFile(handle)
            office_file.load_key(password=DEFAULT_XLS_PASSWORD)
            buffer = io.BytesIO()
            office_file.decrypt(buffer)
        return xlrd.open_workbook(file_contents=buffer.getvalue())


def parse_prices(path: Path) -> list[PriceRecord]:
    workbook = open_workbook(path)
    sheet = workbook.sheet_by_index(0)
    snapshot_date = extract_snapshot_date(sheet)
    month_label = extract_month_label(sheet)
    note_start = find_note_start(sheet)

    trustee_en = trustee_zh = ""
    scheme_en = scheme_zh = ""
    pending: PriceRecord | None = None
    records: list[PriceRecord] = []

    for row_index in range(7, note_start):
        trustee = normalize_text(sheet.cell_value(row_index, 0))
        scheme = normalize_text(sheet.cell_value(row_index, 1))
        fund = normalize_text(sheet.cell_value(row_index, 2))
        raw_price = parse_price(sheet.cell_value(row_index, 3))
        price_hkd, bid_price_hkd, offer_price_hkd = split_price_fields(raw_price)
        notes = normalize_text(sheet.cell_value(row_index, 4))

        if not any((trustee, scheme, fund, raw_price, notes)):
            continue

        is_chinese = contains_cjk(" ".join((trustee, scheme, fund)))

        if is_chinese:
            if trustee:
                trustee_zh = trustee
            if scheme:
                scheme_zh = scheme
            if pending is not None and fund:
                pending.trustee_zh = trustee_zh
                pending.scheme_zh = scheme_zh
                pending.fund_zh = fund
                pending.notes_zh = notes
                records.append(pending)
                pending = None
            continue

        if pending is not None:
            records.append(pending)

        if trustee:
            trustee_en = trustee
        if scheme:
            scheme_en = scheme

        pending = PriceRecord(
            source_file=path.name,
            snapshot_date=snapshot_date,
            month_label=month_label,
            trustee_en=trustee_en,
            trustee_zh="",
            scheme_en=scheme_en,
            scheme_zh="",
            fund_en=fund,
            fund_zh="",
            price_hkd=price_hkd,
            bid_price_hkd=bid_price_hkd,
            offer_price_hkd=offer_price_hkd,
            notes_en=notes,
            notes_zh="",
        )

    if pending is not None:
        records.append(pending)

    return records


def parse_notes(path: Path) -> list[NoteRecord]:
    workbook = open_workbook(path)
    sheet = workbook.sheet_by_index(0)
    snapshot_date = extract_snapshot_date(sheet)
    month_label = extract_month_label(sheet)
    note_start = find_note_start(sheet)

    records: list[NoteRecord] = []
    current_code = ""
    last_emitted_code = ""

    for row_index in range(note_start, sheet.nrows):
        text = normalize_text(sheet.cell_value(row_index, 0))
        if not text or text in {"Note:", "備註:"}:
            continue

        language = "zh" if contains_cjk(text) else "en"
        code = ""
        detail = text

        if language == "en":
            match = NOTE_CODE_RE.match(text)
            if match:
                code = match.group(1)
                current_code = code
                detail = match.group(2).strip()
            else:
                sub_match = NOTE_SUBCODE_RE.match(text)
                if sub_match and current_code:
                    code = f"{current_code}{sub_match.group(1).lower()}"
                    detail = sub_match.group(2).strip()
                elif current_code:
                    code = current_code
        else:
            code = last_emitted_code or current_code

        last_emitted_code = code
        records.append(
            NoteRecord(
                source_file=path.name,
                snapshot_date=snapshot_date,
                month_label=month_label,
                note_code=code,
                language=language,
                text=detail,
            )
        )

    return records


def write_csv(records: Iterable[object], destination: Path) -> None:
    rows = [asdict(record) for record in records]
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        destination.write_text("", encoding="utf-8")
        return
    with destination.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def collect_workbooks(input_path: Path) -> list[Path]:
    if input_path.is_file():
        return [input_path]
    return sorted(input_path.glob("*.xls"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Transform MPFA monthly unit price workbooks into normalized CSV files."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("data/raw"),
        help="Single XLS file or directory of XLS files.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/processed"),
        help="Directory for per-month CSV outputs.",
    )
    parser.add_argument(
        "--combined-prices-output",
        type=Path,
        default=Path("data/processed/all_prices.csv"),
        help="Optional combined prices CSV output path.",
    )
    parser.add_argument(
        "--combined-notes-output",
        type=Path,
        default=Path("data/processed/all_notes.csv"),
        help="Optional combined notes CSV output path.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    workbooks = collect_workbooks(args.input)
    if not workbooks:
        raise FileNotFoundError(f"No .xls files found under {args.input}")

    all_prices: list[PriceRecord] = []
    all_notes: list[NoteRecord] = []

    for workbook in workbooks:
        print(f"etl {workbook.name}")
        prices = parse_prices(workbook)
        notes = parse_notes(workbook)
        if not prices:
            raise ValueError(f"No price rows parsed from {workbook}")
        all_prices.extend(prices)
        all_notes.extend(notes)
        month_key = prices[0].snapshot_date[:7]
        prices_output = args.output_dir / f"{month_key}_prices.csv"
        notes_output = args.output_dir / f"{month_key}_notes.csv"
        write_csv(prices, prices_output)
        write_csv(notes, notes_output)
        print(f"wrote {prices_output}")
        print(f"wrote {notes_output}")

    if args.combined_prices_output:
        write_csv(all_prices, args.combined_prices_output)
        print(f"wrote {args.combined_prices_output}")
    if args.combined_notes_output:
        write_csv(all_notes, args.combined_notes_output)
        print(f"wrote {args.combined_notes_output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
