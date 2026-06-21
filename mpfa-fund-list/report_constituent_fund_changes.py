import argparse
import gzip
import json
import os
import re
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

import requests


DEFAULT_WEBHOOK_ENV_VAR = "GOOGLE_CHAT_WEBHOOK_URL"
DATASET_DIR = Path("data/constituent_funds")
DATED_SNAPSHOT_PATTERN = re.compile(r"^(\d{4}-\d{2}-\d{2})\.json\.gz$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare the latest constituent fund snapshot with the previous dated snapshot and report the result to Google Chat."
    )
    parser.add_argument(
        "--dataset-dir",
        type=Path,
        default=DATASET_DIR,
        help=f"Directory containing constituent fund snapshots. Default: {DATASET_DIR}",
    )
    parser.add_argument(
        "--webhook-url",
        default=os.environ.get(DEFAULT_WEBHOOK_ENV_VAR),
        help=f"Google Chat webhook URL. Defaults to ${DEFAULT_WEBHOOK_ENV_VAR}.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the report instead of posting it to Google Chat.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=30,
        help="HTTP timeout in seconds when posting to Google Chat.",
    )
    return parser.parse_args()


def load_gzip_json(path: Path) -> dict[str, Any]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return json.load(handle)


def find_previous_snapshot_path(dataset_dir: Path, current_revision_date: str) -> Path | None:
    candidates: list[tuple[str, Path]] = []
    for path in dataset_dir.glob("*.json.gz"):
        if path.name in {"latest.json.gz", "latest_raw.json.gz"} or path.name.endswith("_raw.json.gz"):
            continue
        match = DATED_SNAPSHOT_PATTERN.match(path.name)
        if match and match.group(1) < current_revision_date:
            candidates.append((match.group(1), path))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    return candidates[-1][1]


def build_fund_index(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for row in rows:
        fund_id = row.get("FUND_ID")
        if fund_id:
            index[fund_id] = row
    return index


def get_scheme_label(row: dict[str, Any]) -> str:
    return row.get("SCHEME_NAME_TC") or row.get("SCHEME_NAME") or "(計劃名稱缺失)"


def get_fund_label(row: dict[str, Any]) -> str:
    return row.get("FUND_NAME_TC") or row.get("FUND_NAME") or "(基金名稱缺失)"


def count_funds_by_scheme(rows: list[dict[str, Any]]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for row in rows:
        counts[get_scheme_label(row)] += 1
    return counts


def format_scheme_count_lines(rows: list[dict[str, Any]]) -> list[str]:
    scheme_counts = count_funds_by_scheme(rows)
    lines = [f"各計劃基金數: {len(scheme_counts)}"]
    for scheme_name, count in sorted(scheme_counts.items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"- {scheme_name}: {count}")
    return lines


def format_fund_lines(fund_ids: list[str], fund_index: dict[str, dict[str, Any]], label: str) -> list[str]:
    if not fund_ids:
        return [f"{label}: 無"]

    lines = [f"{label}: {len(fund_ids)}"]
    for fund_id in fund_ids:
        row = fund_index.get(fund_id, {})
        lines.append(f"- {fund_id}: {get_fund_label(row)} | {get_scheme_label(row)}")
    return lines


def build_report_text(dataset_dir: Path) -> str:
    latest_path = dataset_dir / "latest.json.gz"
    if not latest_path.exists():
        raise FileNotFoundError(f"Latest constituent fund snapshot not found: {latest_path}")

    current_payload = load_gzip_json(latest_path)
    current_revision_date = current_payload["revision_date"]
    current_total = int(current_payload["total"])
    current_rows = current_payload["data"]
    current_index = build_fund_index(current_rows)

    previous_path = find_previous_snapshot_path(dataset_dir, current_revision_date)
    run_date = date.today().isoformat()

    if previous_path is None:
        lines = [
            f"強積金成分基金日報 {run_date}",
            f"最新修訂: {current_revision_date}",
            f"基金總數: {current_total}",
            "前次快照: 無",
            "結果: 首次基線，未有日對日比較。",
        ]
        lines.extend(format_scheme_count_lines(current_rows))
        return "\n".join(lines)

    previous_payload = load_gzip_json(previous_path)
    previous_revision_date = previous_payload["revision_date"]
    previous_total = int(previous_payload["total"])
    previous_rows = previous_payload["data"]
    previous_index = build_fund_index(previous_rows)

    current_ids = set(current_index)
    previous_ids = set(previous_index)
    added_ids = sorted(current_ids - previous_ids)
    removed_ids = sorted(previous_ids - current_ids)

    summary = [
        f"強積金成分基金日報 {run_date}",
        f"最新修訂: {current_revision_date}",
        f"前次修訂: {previous_revision_date}",
        f"最新基金數: {current_total}",
        f"前次基金數: {previous_total}",
        f"變動: {current_total - previous_total:+d}",
    ]

    if not added_ids and not removed_ids:
        summary.append("結果: 無基金變動。")
        summary.extend(format_scheme_count_lines(current_rows))
        return "\n".join(summary)

    if current_total != previous_total:
        summary.append("結果: 基金總數有變。")
    else:
        summary.append("結果: 基金總數不變，但基金清單有變。")

    summary.extend(format_scheme_count_lines(current_rows))
    summary.extend(format_fund_lines(added_ids, current_index, "新增"))
    summary.extend(format_fund_lines(removed_ids, previous_index, "移除"))
    return "\n".join(summary)


def post_to_google_chat(webhook_url: str, text: str, timeout_seconds: int) -> None:
    response = requests.post(webhook_url, json={"text": text}, timeout=timeout_seconds)
    response.raise_for_status()


def main() -> int:
    args = parse_args()
    report_text = build_report_text(args.dataset_dir)
    print(report_text)

    if args.dry_run:
        return 0

    if not args.webhook_url:
        raise SystemExit(
            f"Missing Google Chat webhook URL. Provide --webhook-url or set {DEFAULT_WEBHOOK_ENV_VAR}."
        )

    post_to_google_chat(args.webhook_url, report_text, args.timeout_seconds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
