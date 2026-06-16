# MPFA Fund List

Shared browser, cookie, request, and save helpers live in [utils.py](D:\Workspace\BlockAM\repo\MPFA-data\mpfa-fund-list\utils.py). Both endpoint scripts use the same Playwright-plus-requests flow:

- load the public MPFA listing page
- accept the cookie banner when present
- capture cookies from the browser session
- call the matching AJAX endpoint with a browser-like `POST` for the first page
- read `total` and `revision_date`
- rerun once with `pageSize=total` using `requests` only
- save the raw response as `data/<dataset>/YYYY-MM-DD.json.gz`
- save a cleaned decoded snapshot as `data/<dataset>/latest.json.gz`

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

- installs Python dependencies and Playwright Chromium
- runs all MPFA fund-list tasks
- keeps generated `mpfa-fund-list/data/` out of the main branch
- publishes the generated data to the `data` branch instead

Generated runtime files under `mpfa-fund-list/data/`, `mpfa-fund-list/output/`, and `mpfa-fund-list/__pycache__/` are ignored on the main branch.

## Constituent Funds

Script: [fetch_constituent_funds.py](D:\Workspace\BlockAM\repo\MPFA-data\mpfa-fund-list\fetch_constituent_funds.py)

```powershell
python .\fetch_constituent_funds.py
```

Output directory: `data/constituent_funds/`

## Pooled Investment Funds

Script: [fetch_pooled_investment_funds.py](D:\Workspace\BlockAM\repo\MPFA-data\mpfa-fund-list\fetch_pooled_investment_funds.py)

```powershell
python .\fetch_pooled_investment_funds.py
```

Output directory: `data/pooled_investment_funds/`

## Approved ITCIs

Script: [fetch_approved_itcis.py](D:\Workspace\BlockAM\repo\MPFA-data\mpfa-fund-list\fetch_approved_itcis.py)

```powershell
python .\fetch_approved_itcis.py
```

Output directory: `data/approved_itcis/`

## Scheme Merger Records

Script: [fetch_scheme_merger_records.py](D:\Workspace\BlockAM\repo\MPFA-data\mpfa-fund-list\fetch_scheme_merger_records.py)

```powershell
python .\fetch_scheme_merger_records.py
```

Output directory: `data/scheme_merger_records/`

## Options

Use `--show-browser` if you want to watch the Playwright session in a visible Chromium window.

Use `--user-agent "..."` if you want to override the default user agent string.

Use `--payload .\payload.json` if you want to override the default POST body.
