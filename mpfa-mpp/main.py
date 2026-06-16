import requests
import pandas as pd
import re
import shutil
from datetime import datetime
from pathlib import Path
import fund_code

# Base directory for all project-relative file paths.
BASE_DIR = Path(__file__).resolve().parent

# Constants
DOWNLOAD_URLS = [
    ("https://mfp.mpfa.org.hk/mobile/eng/mpp_download_excel.jsp", "en"),
    ("https://mfp.mpfa.org.hk/mobile/tch/mpp_download_excel.jsp", "tc"),
    ("https://mfp.mpfa.org.hk/mobile/sch/mpp_download_excel.jsp", "sc")
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 16; LM-Q710(FGN)) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.7680.165 Mobile Safari/537.36"
}

INPUT_DIR = BASE_DIR / "input"
STAGING_INPUT_DIR = INPUT_DIR / "_latest"
OUTPUT_DIR = BASE_DIR / "output"
FILE_NAMES = {
    "en": "Fund_Information_Table_result_en.xlsx",
    "tc": "Fund_Information_Table_result_tc.xlsx",
    "sc": "Fund_Information_Table_result_sc.xlsx",
}


def get_file_paths(base_dir):
    """Build language-keyed file paths for a given input directory."""
    return {lang: base_dir / filename for lang, filename in FILE_NAMES.items()}


def get_date_directory(filepath):
    """Extract YYYY-MM date from cell M8 of an Excel file."""
    df = pd.read_excel(filepath, header=None)
    cell_m8 = df.iloc[7, 12]  # Row 8 (0-indexed 7), Column M (0-indexed 12)
    date_str = str(cell_m8)
    
    # Pattern for English: "Latest information as of 28 Feb 2026"
    match = re.search(r'(\d{1,2})\s+(\w+)\s+(\d{4})', date_str)
    if match:
        day, month_abbr, year = match.groups()
        # Convert abbreviated month to full month name
        month_map = {
            'Jan': 'January', 'Feb': 'February', 'Mar': 'March', 'Apr': 'April',
            'May': 'May', 'Jun': 'June', 'Jul': 'July', 'Aug': 'August',
            'Sep': 'September', 'Oct': 'October', 'Nov': 'November', 'Dec': 'December'
        }
        month_full = month_map.get(month_abbr, month_abbr)
        month_num = pd.to_datetime(f"1 {month_full} {year}", format='%d %B %Y').month
        return f"{year}-{month_num:02d}"
    
    # Pattern for Chinese: "截至2026年02月28日"
    match = re.search(r'(\d{4})年(\d{2})月', date_str)
    if match:
        return f"{match.group(1)}-{match.group(2)}"
    
    # Fallback: use current date
    return datetime.now().strftime('%Y-%m')


def download_files():
    """Download Excel files from the given URLs."""
    STAGING_INPUT_DIR.mkdir(parents=True, exist_ok=True)
    file_paths = get_file_paths(STAGING_INPUT_DIR)
    
    for url, lang in DOWNLOAD_URLS:
        try:
            response = requests.get(url, headers=HEADERS)
            response.raise_for_status()
            
            filename = file_paths[lang].name
            filepath = file_paths[lang]
            
            with open(filepath, "wb") as f:
                f.write(response.content)
            
            print(f"Downloaded: {filename}")
        except requests.exceptions.RequestException as e:
            print(f"Failed to download {url}: {e}")
    
    print("Download complete.")
    return file_paths


def normalize_headers(df):
    """Normalize DataFrame headers to snake_case without trailing underscores."""
    df.columns = (
        df.columns.str.strip()
        .str.lower()
        .str.replace(' ', '_', regex=True)
        .str.replace(r'[^\w_]', '', regex=True)
        .str.replace(r'_+', '_', regex=True)
        .str.rstrip('_')
    )
    return df


def read_files(file_paths):
    """Read and normalize Excel files."""
    data_en = pd.read_excel(file_paths["en"], header=13)
    data_tc = pd.read_excel(file_paths["tc"], header=13)
    data_sc = pd.read_excel(file_paths["sc"], header=13)
    
    data_en = normalize_headers(data_en)
    data_tc = normalize_headers(data_tc)
    data_sc = normalize_headers(data_sc)
    
    # Get date from cell M8 of English file
    date_dir = get_date_directory(file_paths["en"])
    
    return data_en, data_tc, data_sc, date_dir


def archive_input_files(file_paths, date_dir):
    """Store the downloaded source Excel files under input/YYYY-MM."""
    dated_input_dir = INPUT_DIR / date_dir
    dated_input_dir.mkdir(parents=True, exist_ok=True)

    for lang, source_path in file_paths.items():
        destination_path = dated_input_dir / FILE_NAMES[lang]
        shutil.copy2(source_path, destination_path)

    return dated_input_dir


def extract_chinese_data(data_tc, data_sc):
    """Extract and rename the first four columns for Traditional and Simplified Chinese data."""
    data_tc_extracted = data_tc.iloc[:, :4].copy()
    data_tc_extracted.columns = ['scheme_tc', 'constituent_fund_tc', 'mpf_trustee_tc', 'fund_type_tc']
    
    data_sc_extracted = data_sc.iloc[:, :4].copy()
    data_sc_extracted.columns = ['scheme_sc', 'constituent_fund_sc', 'mpf_trustee_sc', 'fund_type_sc']
    
    return data_tc_extracted, data_sc_extracted


def merge_data(data_en, data_tc_extracted, data_sc_extracted):
    """Merge English data with extracted Chinese data."""
    merged_data = pd.concat([data_en, data_tc_extracted, data_sc_extracted], axis=1)
    
    # Replace AIAT with AIA
    merged_data['mpf_trustee'] = merged_data['mpf_trustee'].replace('AIAT', 'AIA')
    
    # Rename latest_fer to latest_fund_expense_ratio
    if 'latest_fer' in merged_data.columns:
        merged_data.rename(columns={'latest_fer': 'latest_fund_expense_ratio'}, inplace=True)
    
    # Convert launch_date to YYYY-MM-DD format
    if 'launch_date' in merged_data.columns:
        merged_data['launch_date'] = pd.to_datetime(merged_data['launch_date'], format='%d-%m-%Y').dt.strftime('%Y-%m-%d')
    
    # Replace "n.a." with None in numeric fields
    numeric_columns = ['risk_class', 'latest_fund_expense_ratio', 'calendar_year_return_2025', 
                       'calendar_year_return_2024', 'calendar_year_return_2023', 
                       'calendar_year_return_2022', 'calendar_year_return_2021']
    for col in numeric_columns:
        if col in merged_data.columns:
            merged_data[col] = merged_data[col].replace('n.a.', None)
    
    return merged_data


def generate_fund_codes(merged_data):
    """Generate fund_code column."""
    merged_data['fund_code'] = fund_code.generate_codes([
        {"trustee": trustee, "fund_name": fund_name, "scheme": scheme}
        for trustee, fund_name, scheme in zip(
            merged_data['mpf_trustee'],
            merged_data['constituent_fund'],
            merged_data['scheme']
        )
    ])
    return merged_data


def write_data(data_en, data_tc, data_sc, data_tc_extracted, data_sc_extracted, merged_data, date_dir):
    """Write data to the month-based output directory."""
    OUTPUT_DIR.mkdir(exist_ok=True)
    dated_output_dir = OUTPUT_DIR / date_dir
    dated_output_dir.mkdir(parents=True, exist_ok=True)
    final_output_path = dated_output_dir / f"data_{date_dir}.csv"
    
    data_en.to_csv(dated_output_dir / "data_en.csv", index=False)
    data_tc.to_csv(dated_output_dir / "data_tc.csv", index=False, encoding='utf-8-sig')
    data_sc.to_csv(dated_output_dir / "data_sc.csv", index=False, encoding='utf-8-sig')
    data_tc_extracted.to_csv(dated_output_dir / "data_tc_extracted.csv", index=False, encoding='utf-8-sig')
    data_sc_extracted.to_csv(dated_output_dir / "data_sc_extracted.csv", index=False, encoding='utf-8-sig')
    merged_data.to_csv(dated_output_dir / "merged_data.csv", index=False, encoding='utf-8-sig')
    merged_data.to_csv(final_output_path, index=False, encoding='utf-8-sig')

    print(f"\nData written to output/{date_dir}/ directory.")


def main():
    """Main function to execute the entire workflow."""
    file_paths = download_files()
    data_en, data_tc, data_sc, date_dir = read_files(file_paths)
    archive_input_files(file_paths, date_dir)
    print(f"Date directory extracted from cell M8: {date_dir}")
    data_tc_extracted, data_sc_extracted = extract_chinese_data(data_tc, data_sc)
    merged_data = merge_data(data_en, data_tc_extracted, data_sc_extracted)
    merged_data = generate_fund_codes(merged_data)
    write_data(data_en, data_tc, data_sc, data_tc_extracted, data_sc_extracted, merged_data, date_dir)
    
    # Print the first few rows of each dataframe to verify
    print("\nEnglish Data:")
    print(data_en.head())


if __name__ == "__main__":
    main()
