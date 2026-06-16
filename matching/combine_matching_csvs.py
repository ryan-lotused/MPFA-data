from __future__ import annotations

import re
from pathlib import Path

import pandas as pd


BASE_DIR = Path(__file__).resolve().parent
INPUT_DIR = BASE_DIR / "input"
OUTPUT_DIR = BASE_DIR / "output"


def normalize_text(value: object) -> str:
    text = "" if pd.isna(value) else str(value)
    text = text.strip().lower()
    text = text.replace("\u2013", "-").replace("\u2014", "-")
    text = text.replace("&", " and ")
    text = re.sub(r"\(.*?de-risking.*?\)", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\(.*?automatic de-risking.*?\)", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*-\s*class\s+[a-z0-9]+\s*$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text)
    return text.strip(" -")


def normalize_zh_text(value: object) -> str:
    text = "" if pd.isna(value) else str(value)
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"[-－]\s*單位[A-Z0-9]+$", "", text)
    text = re.sub(r"[-－]\s*[A-Z0-9]類單位$", "", text)
    return text.strip()


def add_match_keys(frame: pd.DataFrame, scheme_col: str, fund_en_col: str, fund_zh_col: str | None) -> pd.DataFrame:
    frame = frame.copy()
    frame["scheme_key"] = frame[scheme_col].map(normalize_text)
    frame["fund_en_key"] = frame[fund_en_col].map(normalize_text)
    frame["fund_zh_key"] = frame[fund_zh_col].map(normalize_zh_text) if fund_zh_col else ""
    frame["match_key"] = frame["scheme_key"] + "||" + frame["fund_en_key"]
    frame["match_key_zh"] = frame["scheme_key"] + "||" + frame["fund_zh_key"]
    return frame


def add_scheme_zh_key(frame: pd.DataFrame, scheme_zh_col: str | None) -> pd.DataFrame:
    frame = frame.copy()
    frame["scheme_zh_key"] = frame[scheme_zh_col].map(normalize_zh_text) if scheme_zh_col else ""
    frame["match_key_zhzh"] = frame["scheme_zh_key"] + "||" + frame["fund_zh_key"]
    return frame


def dedupe_for_merge(frame: pd.DataFrame) -> pd.DataFrame:
    sort_cols = [col for col in ["source_priority", "price_hkd", "snapshot_date", "launch_date"] if col in frame.columns]
    if sort_cols:
        frame = frame.sort_values(sort_cols, ascending=[True] * len(sort_cols), na_position="last")
    return frame.drop_duplicates(subset=["match_key"], keep="first")


def build_lookup(frame: pd.DataFrame, prefix: str) -> pd.DataFrame:
    key_specs = [
        ("match_key", "en_exact", 1),
        ("match_key_zh", "scheme_en_plus_fund_zh", 2),
        ("match_key_zhzh", "scheme_zh_plus_fund_zh", 3),
    ]
    lookup_parts: list[pd.DataFrame] = []
    for key_column, method, priority in key_specs:
        if key_column not in frame.columns:
            continue
        part = frame.add_prefix(prefix)
        part["lookup_key"] = frame[key_column]
        part[f"{prefix}match_method"] = method
        part[f"{prefix}match_priority"] = priority
        part = part[part["lookup_key"].ne("")]
        lookup_parts.append(part)

    lookup = pd.concat(lookup_parts, ignore_index=True)
    sort_cols = [f"{prefix}match_priority"]
    extra_sort = [col for col in ["source_priority", "price_hkd", "snapshot_date", "launch_date"] if col in lookup.columns]
    lookup = lookup.sort_values(sort_cols + extra_sort, na_position="last")
    return lookup.drop_duplicates(subset=["lookup_key"], keep="first")


def staged_merge(left: pd.DataFrame, right_lookup: pd.DataFrame, prefix: str) -> pd.DataFrame:
    result = left.copy()
    result[f"{prefix}match_method"] = ""
    result[f"{prefix}matched_on"] = ""
    result[f"{prefix}selected_lookup_key"] = ""

    lookup = right_lookup.drop_duplicates(subset=["lookup_key"], keep="first").set_index("lookup_key")
    for key_column, label in [
        ("match_key", "scheme_en + fund_en"),
        ("match_key_zh", "scheme_en + fund_zh"),
        ("match_key_zhzh", "scheme_zh + fund_zh"),
    ]:
        pending = result[f"{prefix}selected_lookup_key"].eq("")
        if not pending.any() or key_column not in result.columns:
            continue
        matched = pending & result[key_column].isin(lookup.index)
        result.loc[matched, f"{prefix}selected_lookup_key"] = result.loc[matched, key_column]
        result.loc[matched, f"{prefix}matched_on"] = label

    matched_keys = result[f"{prefix}selected_lookup_key"]
    value_columns = list(lookup.columns)
    for column in value_columns:
        mapped = matched_keys.map(lookup[column])
        result[column] = mapped.where(mapped.notna(), result.get(column))

    method_column = f"{prefix}match_method"
    if method_column in lookup.columns:
        result[method_column] = matched_keys.map(lookup[method_column]).fillna("")
    result = result.drop(columns=[f"{prefix}selected_lookup_key"])

    return result


def build_column_summary() -> pd.DataFrame:
    source_columns = {
        "fund_info": set(pd.read_csv(INPUT_DIR / "fund_info.csv", nrows=0).columns),
        "merged_data": set(pd.read_csv(INPUT_DIR / "merged_data.csv", nrows=0).columns),
        "prices": set(pd.read_csv(INPUT_DIR / "2026-04_prices.csv", nrows=0).columns),
    }

    all_columns = sorted(set().union(*source_columns.values()))
    rows: list[dict[str, object]] = []
    for column in all_columns:
        present_in = [name for name, cols in source_columns.items() if column in cols]
        rows.append(
            {
                "column_name": column,
                "present_in": ", ".join(present_in),
                "source_count": len(present_in),
                "is_unique_to_one_source": len(present_in) == 1,
            }
        )
    return pd.DataFrame(rows)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    fund_info = pd.read_csv(INPUT_DIR / "fund_info.csv", dtype=str).fillna("")
    merged = pd.read_csv(INPUT_DIR / "merged_data.csv", dtype=str).fillna("")
    prices = pd.read_csv(INPUT_DIR / "2026-04_prices.csv", dtype=str).fillna("")

    fund_info = add_match_keys(fund_info, "scheme_en", "fund_name_en", "fund_name_zh")
    fund_info = add_scheme_zh_key(fund_info, "scheme_zh")
    merged = add_match_keys(merged, "scheme", "constituent_fund", "constituent_fund_tc")
    merged = add_scheme_zh_key(merged, "scheme_tc")
    prices = add_match_keys(prices, "scheme_en", "fund_en", "fund_zh")
    prices = add_scheme_zh_key(prices, "scheme_zh")

    merged["source_priority"] = 1
    prices["source_priority"] = 1
    merged_merge = dedupe_for_merge(merged)
    prices_merge = dedupe_for_merge(prices)

    combined = staged_merge(fund_info, build_lookup(merged_merge, "master_"), "master_")
    combined = staged_merge(combined, build_lookup(prices_merge, "price_"), "price_")

    essential_columns = [
        "fund_id",
        "trustee_id",
        "trustee_en",
        "trustee_zh",
        "scheme_id",
        "scheme_en",
        "scheme_zh",
        "fund_type_id",
        "fund_type_en",
        "fund_type_zh",
        "fund_name_en",
        "fund_name_zh",
        "class",
        "launch_date",
        "master_fund_code",
        "master_fund_size_hkd_m",
        "master_risk_class",
        "master_latest_fund_expense_ratio",
        "master_calendar_year_return_2025",
        "master_calendar_year_return_2024",
        "master_calendar_year_return_2023",
        "master_calendar_year_return_2022",
        "master_calendar_year_return_2021",
        "master_match_method",
        "master_matched_on",
        "price_snapshot_date",
        "price_month_label",
        "price_price_hkd",
        "price_bid_price_hkd",
        "price_offer_price_hkd",
        "price_notes_en",
        "price_notes_zh",
        "price_source_file",
        "price_match_method",
        "price_matched_on",
    ]

    essential = combined[essential_columns].rename(
        columns={
            "master_fund_code": "fund_code",
            "master_fund_size_hkd_m": "fund_size_hkd_m",
            "master_risk_class": "risk_class",
            "master_latest_fund_expense_ratio": "latest_fund_expense_ratio",
            "master_calendar_year_return_2025": "calendar_year_return_2025",
            "master_calendar_year_return_2024": "calendar_year_return_2024",
            "master_calendar_year_return_2023": "calendar_year_return_2023",
            "master_calendar_year_return_2022": "calendar_year_return_2022",
            "master_calendar_year_return_2021": "calendar_year_return_2021",
            "master_match_method": "master_match_method",
            "master_matched_on": "master_matched_on",
            "price_snapshot_date": "snapshot_date",
            "price_month_label": "month_label",
            "price_price_hkd": "price_hkd",
            "price_bid_price_hkd": "bid_price_hkd",
            "price_offer_price_hkd": "offer_price_hkd",
            "price_notes_en": "notes_en",
            "price_notes_zh": "notes_zh",
            "price_source_file": "source_file",
            "price_match_method": "price_match_method",
            "price_matched_on": "price_matched_on",
        }
    )

    essential_unique = essential.sort_values(
        ["scheme_en", "fund_name_en", "class", "fund_id"],
        na_position="last",
    ).drop_duplicates(
        subset=["scheme_en", "fund_name_en", "class"],
        keep="first",
    )

    unmatched_master = essential[essential["fund_code"].eq("")].copy()
    unmatched_prices = essential[essential["price_hkd"].eq("")].copy()

    combined.to_csv(OUTPUT_DIR / "combined_all_columns.csv", index=False, encoding="utf-8-sig")
    essential.to_csv(OUTPUT_DIR / "combined_essential_columns.csv", index=False, encoding="utf-8-sig")
    essential_unique.to_csv(OUTPUT_DIR / "combined_essential_unique_rows.csv", index=False, encoding="utf-8-sig")
    unmatched_master.to_csv(OUTPUT_DIR / "unmatched_master_rows.csv", index=False, encoding="utf-8-sig")
    unmatched_prices.to_csv(OUTPUT_DIR / "unmatched_price_rows.csv", index=False, encoding="utf-8-sig")
    build_column_summary().to_csv(OUTPUT_DIR / "column_summary.csv", index=False, encoding="utf-8-sig")

    summary_lines = [
        f"fund_info rows: {len(fund_info)}",
        f"combined rows: {len(combined)}",
        f"essential unique rows: {len(essential_unique)}",
        f"missing master enrichment: {len(unmatched_master)}",
        f"missing price data: {len(unmatched_prices)}",
        f"master match methods: {essential['master_match_method'].value_counts(dropna=False).to_dict()}",
        f"price match methods: {essential['price_match_method'].value_counts(dropna=False).to_dict()}",
    ]
    (OUTPUT_DIR / "summary.txt").write_text("\n".join(summary_lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
