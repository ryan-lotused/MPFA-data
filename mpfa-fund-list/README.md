# MPFA Fund List

Shared browser, cookie, request, and save helpers live in [utils.py](D:\Workspace\BlockAM\repo\MPFA-data\mpfa-fund-list\utils.py). Both endpoint scripts use the same Playwright-plus-requests flow:

- load the public MPFA listing page
- accept the cookie banner when present
- capture cookies from the browser session
- call the matching AJAX endpoint with a browser-like `POST` for the first page
- read `total` and `revision_date`
- rerun once with `pageSize=total` using `requests` only
- save the raw response as `data/<dataset>/YYYY-MM-DD_raw.json.gz` and `data/<dataset>/latest_raw.json.gz`
- save cleaned decoded snapshots as `data/<dataset>/YYYY-MM-DD.json.gz` and `data/<dataset>/latest.json.gz`

## Run Everything

Script: [main.py](D:\Workspace\BlockAM\repo\MPFA-data\mpfa-fund-list\main.py)

```powershell
python .\main.py
```

Run only a subset if needed:

```powershell
python .\main.py --tasks constituent_funds approved_itcis
```

## GitHub Actions

Workflow: [.github/workflows/mpfa-fund-list-data.yml](D:\Workspace\BlockAM\repo\MPFA-data\.github\workflows\mpfa-fund-list-data.yml)

`main.py` is designed to run in GitHub Actions. The workflow:

- uses the repository checkout on `main` as the source of prior snapshots before each run
- installs Python dependencies and Playwright Chromium
- runs all MPFA fund-list tasks
- compares the latest constituent-funds snapshot with the previous dated snapshot
- posts a Google Chat report for every run using the `GOOGLE_CHAT_WEBHOOK_URL` secret
- commits refreshed `mpfa-fund-list/data/` artifacts back to `main` when they change
- pushes the updated repository state back to `main`

Generated runtime files under `mpfa-fund-list/data/`, `mpfa-fund-list/output/`, and `mpfa-fund-list/__pycache__/` are ignored on the main branch.

## Constituent Funds

Script: [fetch_constituent_funds.py](D:\Workspace\BlockAM\repo\MPFA-data\mpfa-fund-list\fetch_constituent_funds.py)

```powershell
python .\fetch_constituent_funds.py
```

Output directory: `data/constituent_funds/`

`YYYY-MM-DD_raw.json.gz` and `latest_raw.json.gz` store the raw API response. `YYYY-MM-DD.json.gz` and `latest.json.gz` store the cleaned snapshot with parsed names and extracted `FUND_ID`.

## Pooled Investment Funds

Script: [fetch_pooled_investment_funds.py](D:\Workspace\BlockAM\repo\MPFA-data\mpfa-fund-list\fetch_pooled_investment_funds.py)

```powershell
python .\fetch_pooled_investment_funds.py
```

Output directory: `data/pooled_investment_funds/`

`YYYY-MM-DD_raw.json.gz` and `latest_raw.json.gz` store the raw API response. `YYYY-MM-DD.json.gz` and `latest.json.gz` store the decoded dataset.

## Approved ITCIs

Script: [fetch_approved_itcis.py](D:\Workspace\BlockAM\repo\MPFA-data\mpfa-fund-list\fetch_approved_itcis.py)

```powershell
python .\fetch_approved_itcis.py
```

Output directory: `data/approved_itcis/`

`YYYY-MM-DD_raw.json.gz` and `latest_raw.json.gz` store the raw API response. `YYYY-MM-DD.json.gz` and `latest.json.gz` store the decoded dataset.

## Scheme Merger Records

Script: [fetch_scheme_merger_records.py](D:\Workspace\BlockAM\repo\MPFA-data\mpfa-fund-list\fetch_scheme_merger_records.py)

```powershell
python .\fetch_scheme_merger_records.py
```

Output directory: `data/scheme_merger_records/`

`YYYY-MM-DD_raw.json.gz` and `latest_raw.json.gz` store the raw API response. `YYYY-MM-DD.json.gz` and `latest.json.gz` store the decoded dataset.

## Options

Use `--show-browser` if you want to watch the Playwright session in a visible Chromium window.

Use `--user-agent "..."` if you want to override the default user agent string.

Use `--payload .\payload.json` if you want to override the default POST body.

## Daily Constituent Fund Report

Script: [report_constituent_fund_changes.py](D:\Workspace\BlockAM\repo\MPFA-data\mpfa-fund-list\report_constituent_fund_changes.py)

The daily GitHub Actions run compares `data/constituent_funds/latest.json.gz` against the most recent earlier dated snapshot in `data/constituent_funds/`.

If the fund set changes, the report identifies added and removed `FUND_ID` values with fund and scheme names. Every run posts a summary to Google Chat through the `GOOGLE_CHAT_WEBHOOK_URL` GitHub Actions secret.

For local testing, you can print the report without posting it:

```powershell
python .\report_constituent_fund_changes.py --dry-run
```
