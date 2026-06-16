# MPFA Monthly Unit Prices

Scripts in this repo download the MPFA monthly MPF constituent fund `.xls` files and normalize them into CSVs.

## Files

- `scripts/download_mpfa_unit_prices.py`: scrapes the MPFA listing page, downloads each workbook, and writes a manifest.
- `scripts/etl_mpfa_unit_prices.py`: converts the bilingual workbook rows into normalized CSV outputs, including newer password-protected `.xls` files.
- `scripts/verify_outputs.py`: checks raw-vs-processed month coverage and validates bid/offer averaging.

## Usage

Download the workbooks:

```bash
python scripts/download_mpfa_unit_prices.py --skip-existing
```

Probe for older files by filename pattern only:

```bash
python scripts/download_mpfa_unit_prices.py --probe-history --history-only --probe-only
```

Transform the downloads into CSV:

```bash
python scripts/etl_mpfa_unit_prices.py
```

Verify the exported outputs:

```bash
python scripts/verify_outputs.py
```

Default outputs:

- `data/raw/*.xls`
- `data/raw/download_manifest.csv`
- `data/processed/YYYY-MM_prices.csv`
- `data/processed/YYYY-MM_notes.csv`
- `data/processed/all_prices.csv`
- `data/processed/all_notes.csv`
