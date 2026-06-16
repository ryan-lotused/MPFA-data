import argparse
import gzip
import json
import logging
from pathlib import Path
from typing import Any

import requests
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright


DEFAULT_TIMEOUT_MS = 30_000
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/149.0.0.0 Safari/537.36"
)
COOKIE_SELECTORS = [
    "button:has-text('Accept')",
    "[role='button']:has-text('Accept')",
    "text=Accept",
]
COMMON_HEADERS = {
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "en,zh-TW;q=0.9,zh;q=0.8,en-GB;q=0.7,en-US;q=0.6,ja;q=0.5,zh-CN;q=0.4,ru;q=0.3",
    "Connection": "keep-alive",
    "Content-Type": "application/json",
    "DNT": "1",
    "Origin": "https://www.mpfa.org.hk",
    "X-Requested-With": "XMLHttpRequest",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "sec-ch-ua": '"Google Chrome";v="149", "Chromium";v="149", "Not)A;Brand";v="24"',
    "sec-ch-ua-arch": '"x86"',
    "sec-ch-ua-bitness": '"64"',
    "sec-ch-ua-full-version-list": '"Google Chrome";v="149.0.7827.104", "Chromium";v="149.0.7827.104", "Not)A;Brand";v="24.0.0.0"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-model": '""',
    "sec-ch-ua-platform": '"Windows"',
    "sec-ch-ua-platform-version": '"19.0.0"',
}


def add_common_args(
    parser: argparse.ArgumentParser,
    *,
    default_cookie_path: Path,
) -> argparse.ArgumentParser:
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional path to write the raw API response body.",
    )
    parser.add_argument(
        "--cookies-output",
        type=Path,
        default=default_cookie_path,
        help="Optional path to write the captured browser cookies as JSON.",
    )
    parser.add_argument(
        "--show-browser",
        action="store_true",
        help="Launch Chromium in headed mode for debugging.",
    )
    parser.add_argument(
        "--timeout-ms",
        type=int,
        default=DEFAULT_TIMEOUT_MS,
        help=f"Navigation timeout in milliseconds. Default: {DEFAULT_TIMEOUT_MS}.",
    )
    parser.add_argument(
        "--log-level",
        default="info",
        choices=["debug", "info", "warning", "error"],
        help="Logging verbosity. Default: info.",
    )
    parser.add_argument(
        "--user-agent",
        default=DEFAULT_USER_AGENT,
        help="User-Agent string to use for both Playwright and requests.",
    )
    parser.add_argument(
        "--payload",
        type=Path,
        help="Optional path to a JSON file whose contents will be sent as the POST body.",
    )
    return parser


def configure_logging(level_name: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level_name.upper()),
        format="%(asctime)s %(levelname)s %(message)s",
    )


async def accept_cookie_banner(page, logger: logging.Logger) -> None:
    for selector in COOKIE_SELECTORS:
        locator = page.locator(selector).first
        try:
            logger.info("Checking cookie banner selector: %s", selector)
            await locator.wait_for(state="visible", timeout=5_000)
            logger.info("Cookie banner found via selector: %s", selector)
            await locator.click()
            logger.info("Cookie banner accepted")
            return
        except PlaywrightTimeoutError:
            logger.info("Cookie banner not visible for selector: %s", selector)
            continue
        except Exception:
            logger.exception("Cookie banner interaction failed for selector: %s", selector)
            continue

    logger.info("No cookie banner was accepted")


def build_session(cookies: list[dict[str, Any]], user_agent: str, referer_url: str) -> requests.Session:
    session = requests.Session()
    headers = dict(COMMON_HEADERS)
    headers["Referer"] = referer_url
    headers["User-Agent"] = user_agent
    session.headers.update(headers)

    for cookie in cookies:
        session.cookies.set(
            name=cookie["name"],
            value=cookie["value"],
            domain=cookie.get("domain"),
            path=cookie.get("path", "/"),
        )

    return session


async def collect_cookies(
    *,
    list_url: str,
    heading_text: str,
    headless: bool,
    timeout_ms: int,
    user_agent: str,
    cookies_output: Path | None,
    logger: logging.Logger,
) -> list[dict[str, Any]]:
    async with async_playwright() as playwright:
        logger.info("Launching Chromium (headless=%s)", headless)
        browser = await playwright.chromium.launch(headless=headless)
        context = await browser.new_context(
            user_agent=user_agent,
            locale="en-GB",
        )
        page = await context.new_page()

        try:
            logger.info("Navigating to listing page: %s", list_url)
            await page.goto(list_url, wait_until="domcontentloaded", timeout=timeout_ms)
            logger.info("Page reached DOMContentLoaded")
            try:
                logger.info("Waiting for listing heading")
                await page.locator(f"h2:has-text('{heading_text}')").wait_for(
                    state="visible",
                    timeout=10_000,
                )
                logger.info("Listing heading is visible")
            except PlaywrightTimeoutError:
                logger.info("Heading wait timed out, falling back to page load event")
                await page.wait_for_load_state("load", timeout=10_000)
                logger.info("Page load event completed")

            await accept_cookie_banner(page, logger)
            logger.info("Waiting briefly after cookie handling")
            await page.wait_for_timeout(1_000)

            cookies = await context.cookies()
            logger.info("Collected %s cookies from browser context", len(cookies))
            if cookies_output:
                write_json(cookies_output, cookies)
                logger.info("Saved cookies to %s", cookies_output)
            return cookies
        finally:
            logger.info("Closing browser")
            await browser.close()


def post_api(
    *,
    api_url: str,
    referer_url: str,
    payload: dict[str, Any],
    cookies: list[dict[str, Any]],
    user_agent: str,
    logger: logging.Logger,
) -> tuple[str, int]:
    session = build_session(cookies, user_agent, referer_url)
    logger.info("Posting to API endpoint with browser cookies: %s", api_url)
    logger.info("POST payload: %s", payload)
    response = session.post(api_url, json=payload, timeout=30)
    logger.info("API response status: %s", response.status_code)
    response.raise_for_status()
    return response.text, response.status_code


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_text(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")


def write_gzip_text(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        handle.write(payload)


def write_gzip_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)


def load_payload(path: Path | None, default_payload: dict[str, Any]) -> dict[str, Any]:
    if path is None:
        return dict(default_payload)
    return json.loads(path.read_text(encoding="utf-8"))


def decode_response_layers(raw_text: str) -> tuple[str, dict[str, Any], list[dict[str, Any]]]:
    outer_string = json.loads(raw_text)
    payload = json.loads(outer_string)
    rows = json.loads(payload["data"])
    return outer_string, payload, rows


def parse_revision_date(value: str) -> str:
    if "T" in value:
        return value.split("T", 1)[0]
    if "-" in value and len(value) >= 10:
        return value[:10]
    day, month, year = value.split("/")
    return f"{year}-{month}-{day}"


async def fetch_full_dataset(
    *,
    list_url: str,
    api_url: str,
    heading_text: str,
    payload: dict[str, Any],
    headless: bool,
    timeout_ms: int,
    user_agent: str,
    cookies_output: Path | None,
    logger: logging.Logger,
) -> tuple[str, dict[str, Any], list[dict[str, Any]], int]:
    cookies = await collect_cookies(
        list_url=list_url,
        heading_text=heading_text,
        headless=headless,
        timeout_ms=timeout_ms,
        user_agent=user_agent,
        cookies_output=cookies_output,
        logger=logger,
    )
    raw_text, status_code = post_api(
        api_url=api_url,
        referer_url=list_url,
        payload=payload,
        cookies=cookies,
        user_agent=user_agent,
        logger=logger,
    )

    _, decoded_payload, decoded_rows = decode_response_layers(raw_text)
    total_rows = int(decoded_payload["total"])
    logger.info(
        "Initial response returned %s rows out of %s total",
        len(decoded_rows),
        total_rows,
    )

    if payload.get("pageSize") != total_rows:
        full_payload = dict(payload)
        full_payload["pageSize"] = total_rows
        full_payload["pageNumber"] = 0
        logger.info("Refetching with pageSize=%s to retrieve the full dataset", total_rows)
        raw_text, status_code = post_api(
            api_url=api_url,
            referer_url=list_url,
            payload=full_payload,
            cookies=cookies,
            user_agent=user_agent,
            logger=logger,
        )
        _, decoded_payload, decoded_rows = decode_response_layers(raw_text)
        logger.info(
            "Full response returned %s rows out of %s total",
            len(decoded_rows),
            decoded_payload.get("total"),
        )

    return raw_text, decoded_payload, decoded_rows, status_code


def save_endpoint_outputs(
    *,
    raw_text: str,
    decoded_payload: dict[str, Any],
    decoded_rows: list[dict[str, Any]],
    dataset_dir: Path,
) -> tuple[Path, Path]:
    revision_date = parse_revision_date(decoded_payload["revision_date"])
    raw_output_path = dataset_dir / f"{revision_date}.json.gz"
    latest_output_path = dataset_dir / "latest.json.gz"

    cleaned_payload = dict(decoded_payload)
    cleaned_payload["total"] = int(cleaned_payload["total"])
    cleaned_payload["revision_date"] = revision_date
    cleaned_payload["data"] = decoded_rows

    write_gzip_text(raw_output_path, raw_text)
    write_gzip_json(latest_output_path, cleaned_payload)
    return raw_output_path, latest_output_path
