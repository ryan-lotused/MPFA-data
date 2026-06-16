import argparse
import asyncio
import logging

import fetch_approved_itcis as approved_itcis
import fetch_constituent_funds as constituent_funds
import fetch_pooled_investment_funds as pooled_investment_funds
import fetch_scheme_merger_records as scheme_merger_records
from utils import DEFAULT_TIMEOUT_MS
from utils import DEFAULT_USER_AGENT
from utils import configure_logging
from utils import fetch_full_dataset
from utils import save_endpoint_outputs


TASKS = {
    "constituent_funds": {
        "module": constituent_funds,
        "label": "constituent funds",
    },
    "pooled_investment_funds": {
        "module": pooled_investment_funds,
        "label": "pooled investment funds",
    },
    "approved_itcis": {
        "module": approved_itcis,
        "label": "approved ITCIs",
    },
    "scheme_merger_records": {
        "module": scheme_merger_records,
        "label": "scheme merger records",
    },
}


logger = logging.getLogger("mpfa_main")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run all MPFA useful-list fetch tasks with one command."
    )
    parser.add_argument(
        "--tasks",
        nargs="+",
        choices=list(TASKS),
        default=list(TASKS),
        help="Optional subset of tasks to run. Default: all tasks.",
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
    return parser.parse_args()


async def run_task(task_name: str, args: argparse.Namespace) -> None:
    task = TASKS[task_name]
    module = task["module"]
    logger.info("Starting %s", task["label"])

    raw_text, decoded_payload, decoded_rows, status_code = await fetch_full_dataset(
        list_url=module.LIST_URL,
        api_url=module.API_URL,
        heading_text=module.HEADING_TEXT,
        payload=dict(module.DEFAULT_POST_PAYLOAD),
        headless=not args.show_browser,
        timeout_ms=args.timeout_ms,
        user_agent=args.user_agent,
        cookies_output=module.DEFAULT_COOKIE_PATH,
        logger=logger,
    )

    raw_output_path, latest_output_path = save_endpoint_outputs(
        raw_text=raw_text,
        decoded_payload=decoded_payload,
        decoded_rows=decoded_rows,
        dataset_dir=module.DATASET_DIR,
    )

    print(f"[{task_name}] HTTP {status_code}")
    print(f"[{task_name}] Saved raw response to {raw_output_path}")
    print(f"[{task_name}] Saved cleaned response to {latest_output_path}")
    logger.info("Completed %s", task["label"])


async def main() -> int:
    args = parse_args()
    configure_logging(args.log_level)

    for task_name in args.tasks:
        await run_task(task_name, args)

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
