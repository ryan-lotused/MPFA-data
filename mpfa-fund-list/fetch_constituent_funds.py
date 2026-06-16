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

    raw_output_path, latest_output_path = save_endpoint_outputs(
        raw_text=raw_text,
        decoded_payload=decoded_payload,
        decoded_rows=decoded_rows,
        dataset_dir=DATASET_DIR,
    )

    if args.output:
        write_text(args.output, raw_text)

    print(f"Fetched API response successfully with HTTP {status_code}.")
    print(f"Response body length: {len(raw_text)} characters")
    print(f"Saved raw response to {raw_output_path}")
    print(f"Saved cleaned response to {latest_output_path}")

    if not args.output:
        print(raw_text)

    logger.info("Fetch completed successfully")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
