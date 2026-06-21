import argparse
import asyncio
import logging
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs
from urllib.parse import urlparse

from utils import add_common_args
from utils import configure_logging
from utils import fetch_full_dataset
from utils import load_payload
from utils import save_endpoint_outputs
from utils import write_text


LIST_URL = "https://www.mpfa.org.hk/en/info-centre/useful-list/approved-constituent-funds"
API_URL = "https://www.mpfa.org.hk/api/feature/dataintegration/data-constitude-fund"
HEADING_TEXT = "Search on the List of Approved Constituent Funds"
DEFAULT_POST_PAYLOAD = {
    "fund": "",
    "scheme": "*",
    "invManager": "",
    "currentUrl": "/en/info-centre/useful-list/approved-constituent-funds",
    "fundType": "",
    "lang": "en",
    "pageNumber": 0,
    "pageSize": 10,
}
DATASET_DIR = Path("data/constituent_funds")
DEFAULT_COOKIE_PATH = Path("output/constituent_funds.cookies.json")


logger = logging.getLogger("mpfa_constituent_funds")


class FragmentParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.spans: list[str] = []
        self.href: str | None = None
        self._capture_span = False
        self._span_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = dict(attrs)
        if tag == "a" and self.href is None:
            self.href = attrs_dict.get("href")
        if tag == "span":
            self._capture_span = True
            self._span_parts = []

    def handle_data(self, data: str) -> None:
        if self._capture_span:
            self._span_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "span" and self._capture_span:
            text = "".join(self._span_parts).strip()
            if text:
                self.spans.append(text)
            self._capture_span = False
            self._span_parts = []


def parse_fragment(value: str) -> FragmentParser:
    parser = FragmentParser()
    parser.feed(value)
    parser.close()
    return parser


def clean_constituent_fund_rows(rows: list[dict[str, str]]) -> list[dict[str, str | None]]:
    cleaned_rows: list[dict[str, str | None]] = []
    for row in rows:
        fund_fragment = parse_fragment(row["FUND_NAME"])
        scheme_fragment = parse_fragment(row["SCHEME_NAME"])

        fund_name_eng = fund_fragment.spans[0].strip() if len(fund_fragment.spans) >= 1 else None
        fund_name_tc = fund_fragment.spans[1].strip() if len(fund_fragment.spans) >= 2 else None
        scheme_name_eng = scheme_fragment.spans[0].strip() if len(scheme_fragment.spans) >= 1 else None
        scheme_name_tc = scheme_fragment.spans[1].strip() if len(scheme_fragment.spans) >= 2 else None

        fund_id = None
        if fund_fragment.href:
            query = parse_qs(urlparse(fund_fragment.href).query)
            fund_ids = query.get("id")
            if fund_ids:
                fund_id = fund_ids[0].strip() or None

        cleaned_rows.append(
            {
                "FUND_ID": fund_id,
                "FUND_NAME": fund_name_eng or None,
                "FUND_NAME_TC": fund_name_tc or None,
                "SCHEME_NAME": scheme_name_eng or None,
                "SCHEME_NAME_TC": scheme_name_tc or None,
                "APR_DATE": row.get("APR_DATE"),
            }
        )
    return cleaned_rows


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Use Playwright cookies to fetch the MPFA approved constituent funds API."
    )
    return add_common_args(parser, default_cookie_path=DEFAULT_COOKIE_PATH).parse_args()


async def main() -> int:
    args = parse_args()
    configure_logging(args.log_level)
    logger.info("Starting MPFA constituent fund fetch")

    payload = load_payload(args.payload, DEFAULT_POST_PAYLOAD)
    raw_text, decoded_payload, decoded_rows, status_code = await fetch_full_dataset(
        list_url=LIST_URL,
        api_url=API_URL,
        heading_text=HEADING_TEXT,
        payload=payload,
        headless=not args.show_browser,
        timeout_ms=args.timeout_ms,
        user_agent=args.user_agent,
        cookies_output=args.cookies_output,
        logger=logger,
    )

    (
        raw_dated_output_path,
        raw_latest_output_path,
        cleaned_dated_output_path,
        cleaned_latest_output_path,
    ) = save_endpoint_outputs(
        raw_text=raw_text,
        decoded_payload=decoded_payload,
        decoded_rows=decoded_rows,
        dataset_dir=DATASET_DIR,
        cleaned_row_transform=clean_constituent_fund_rows,
    )

    if args.output:
        write_text(args.output, raw_text)

    print(f"Fetched API response successfully with HTTP {status_code}.")
    print(f"Response body length: {len(raw_text)} characters")
    print(f"Saved raw response to {raw_dated_output_path}")
    print(f"Saved latest raw response to {raw_latest_output_path}")
    print(f"Saved cleaned response to {cleaned_dated_output_path}")
    print(f"Saved latest cleaned response to {cleaned_latest_output_path}")

    if not args.output:
        print(raw_text)

    logger.info("Fetch completed successfully")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
