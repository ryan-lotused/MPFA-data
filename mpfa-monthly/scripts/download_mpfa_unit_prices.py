from __future__ import annotations

import argparse
import csv
import re
import socket
import sys
from dataclasses import dataclass
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


LISTING_URL = (
    "https://www.mpfa.org.hk/info-centre/fund-information/monthly-fund-price/"
    "monthly-unit-prices-of-mpf-constituent-funds"
)
USER_AGENT = "Mozilla/5.0 (compatible; mpfa-monthly-unit-prices/1.0)"
XLS_HREF_RE = re.compile(r"/-/media/files/information-centre/fund-information/monthly-fund-price/.+\.xls$", re.I)
DATE_TEXT_RE = re.compile(r"^\d{4}年\d{1,2}月\d{1,2}日$")
FILENAME_RE = re.compile(r"consolidated_list_for_([a-z]{3})_(\d{2})_read_only\.xls$", re.I)
MONTH_ABBR = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")
DOWNLOAD_BASE_URL = "https://www.mpfa.org.hk/-/media/files/information-centre/fund-information/monthly-fund-price/"
REQUEST_TIMEOUT_SECONDS = 12


@dataclass(frozen=True)
class DownloadItem:
    month_key: str
    date_text: str
    url: str
    filename: str
    source: str


class ListingParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._candidate_href: str | None = None
        self._buffer: list[str] = []
        self.items: list[DownloadItem] = []
        self._seen_urls: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        href = dict(attrs).get("href")
        if href and XLS_HREF_RE.search(href):
            self._candidate_href = href
            self._buffer = []

    def handle_data(self, data: str) -> None:
        if self._candidate_href is not None:
            self._buffer.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or self._candidate_href is None:
            return
        text = "".join(self._buffer).strip()
        href = self._candidate_href
        self._candidate_href = None
        self._buffer = []
        if not text or not DATE_TEXT_RE.match(text):
            return
        url = urljoin(LISTING_URL, href)
        if url in self._seen_urls:
            return
        self._seen_urls.add(url)
        filename = Path(href).name
        self.items.append(
            DownloadItem(
                month_key=month_key_from_filename(filename),
                date_text=text,
                url=url,
                filename=filename,
                source="listing",
            )
        )


def fetch_text(url: str) -> str:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        return response.read().decode("utf-8", errors="replace")


def download_binary(url: str, destination: Path) -> None:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        destination.write_bytes(response.read())


def url_exists(url: str) -> bool:
    request = Request(url, headers={"User-Agent": USER_AGENT}, method="HEAD")
    try:
        with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            status = getattr(response, "status", response.getcode())
            content_type = response.headers.get("Content-Type", "")
            return status == 200 and "html" not in content_type.lower()
    except HTTPError as error:
        if error.code == 405:
            fallback = Request(url, headers={"User-Agent": USER_AGENT})
            with urlopen(fallback, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                status = getattr(response, "status", response.getcode())
                content_type = response.headers.get("Content-Type", "")
                return status == 200 and "html" not in content_type.lower()
        if error.code == 404:
            return False
        raise
    except (TimeoutError, socket.timeout, URLError):
        return False


def month_key_from_filename(filename: str) -> str:
    match = FILENAME_RE.match(filename)
    if not match:
        raise ValueError(f"Unrecognized MPFA filename pattern: {filename}")
    month = MONTH_ABBR.index(match.group(1).lower()) + 1
    year = 2000 + int(match.group(2))
    return f"{year:04d}-{month:02d}"


def iter_month_keys(start: str, end: str) -> Iterable[str]:
    year, month = map(int, start.split("-"))
    end_year, end_month = map(int, end.split("-"))
    while (year, month) <= (end_year, end_month):
        yield f"{year:04d}-{month:02d}"
        if month == 12:
            year += 1
            month = 1
        else:
            month += 1


def build_filename(month_key: str) -> str:
    year, month = map(int, month_key.split("-"))
    return f"consolidated_list_for_{MONTH_ABBR[month - 1]}_{year % 100:02d}_read_only.xls"


def probe_history(start: str, end: str, verbose: bool = False) -> list[DownloadItem]:
    items: list[DownloadItem] = []
    for index, month_key in enumerate(iter_month_keys(start, end), start=1):
        filename = build_filename(month_key)
        url = urljoin(DOWNLOAD_BASE_URL, filename)
        if url_exists(url):
            if verbose:
                print(f"found {month_key}")
            items.append(
                DownloadItem(
                    month_key=month_key,
                    date_text=month_key,
                    url=url,
                    filename=filename,
                    source="probed",
                )
            )
        elif verbose and index % 12 == 0:
            print(f"checked through {month_key}")
    return items


def merge_items(*groups: Iterable[DownloadItem]) -> list[DownloadItem]:
    merged: dict[str, DownloadItem] = {}
    for group in groups:
        for item in group:
            merged[item.filename] = item
    return sorted(merged.values(), key=lambda item: item.month_key)


def iter_items(listing_url: str = LISTING_URL) -> list[DownloadItem]:
    parser = ListingParser()
    parser.feed(fetch_text(listing_url))
    return parser.items


def write_manifest(items: Iterable[DownloadItem], destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["month_key", "date_text", "filename", "url", "source"])
        writer.writeheader()
        for item in items:
            writer.writerow(
                {
                    "month_key": item.month_key,
                    "date_text": item.date_text,
                    "filename": item.filename,
                    "url": item.url,
                    "source": item.source,
                }
            )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download MPFA monthly unit price XLS workbooks and write a manifest."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/raw"),
        help="Directory for downloaded XLS files.",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("data/raw/download_manifest.csv"),
        help="CSV manifest path.",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip files that already exist locally.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Download only the first N files from the listing.",
    )
    parser.add_argument(
        "--listing-url",
        default=LISTING_URL,
        help="Override the MPFA listing page URL for testing.",
    )
    parser.add_argument(
        "--probe-history",
        action="store_true",
        help="Probe the monthly filename pattern outside the current listing page.",
    )
    parser.add_argument(
        "--history-start",
        default="2000-12",
        help="First month to probe in YYYY-MM format when --probe-history is set.",
    )
    parser.add_argument(
        "--history-end",
        default=date.today().strftime("%Y-%m"),
        help="Last month to probe in YYYY-MM format when --probe-history is set.",
    )
    parser.add_argument(
        "--probe-only",
        action="store_true",
        help="Write the manifest without downloading files.",
    )
    parser.add_argument(
        "--history-only",
        action="store_true",
        help="Use only probed historical URLs and skip the current listing page.",
    )
    return parser.parse_args()


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    output_dir: Path = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    listing_items = [] if args.history_only else iter_items(args.listing_url)
    history_items = probe_history(args.history_start, args.history_end, verbose=True) if args.probe_history else []
    items = merge_items(listing_items, history_items)
    if args.limit is not None:
        items = items[: args.limit]

    write_manifest(items, args.manifest)
    print(f"wrote manifest: {args.manifest}")
    if args.probe_only:
        print(f"found {len(items)} files")
        return 0

    for item in items:
        destination = output_dir / item.filename
        if args.skip_existing and destination.exists():
            print(f"skip {item.filename}")
            continue
        print(f"download {item.filename} <- {item.date_text}")
        download_binary(item.url, destination)
    return 0


if __name__ == "__main__":
    sys.exit(main())
