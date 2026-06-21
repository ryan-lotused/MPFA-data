import argparse
import asyncio
import logging
from pathlib import Path

from utils import add_common_args
from utils import configure_logging
from utils import fetch_full_dataset
from utils import load_payload
from utils import save_endpoint_outputs
from utils import write_text


LIST_URL = "https://www.mpfa.org.hk/en/info-centre/useful-list/scheme-merger-records"
API_URL = "https://www.mpfa.org.hk/api/feature/dataintegration/schememergerrecordsajax"
HEADING_TEXT = "Search on the List of Scheme Merger Records"
DEFAULT_POST_PAYLOAD = {
    "keyword": "",
    "lang": "en",
    "pageNumber": 0,
    "pageSize": 10,
}
DATASET_DIR = Path("data/scheme_merger_records")
DEFAULT_COOKIE_PATH = Path("output/scheme_merger_records.cookies.json")


logger = logging.getLogger("mpfa_scheme_merger_records")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Use Playwright cookies to fetch the MPFA scheme merger records API."
    )
    return add_common_args(parser, default_cookie_path=DEFAULT_COOKIE_PATH).parse_args()


async def main() -> int:
    args = parse_args()
    configure_logging(args.log_level)
    logger.info("Starting MPFA scheme merger records fetch")

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
