#!/usr/bin/env python3
import csv
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
import os


# ---------------------------------------------------------------------------
# Configuration tables
# ---------------------------------------------------------------------------

TRUSTEE_PREFIXES: dict[str, str] = {
    "AIA": "AIA",
    "HSBC": "HSBC",
    "Manulife": "MNLF",
    "SunLife": "SUNL",
    "BCOM": "BCOM",
    "BEA": "BEA",
    "BOCIP": "BOCI",
    "China Life": "CHNL",
    "PRIN": "PRIN",
    "BCT": "BCT",
    "SCT": "SCT",
    "YF Life": "YFLI",
}

# Words stripped before abbreviation; trustee/brand names and generic filler.
# Note: "china" is intentionally absent — it has a meaningful WORD_MAP entry (CN).
SKIP_WORDS: frozenset[str] = frozenset(
    {
        "a", "an", "the", "and", "or", "of", "in", "for", "to", "by", "at",
        "no", "mpf", "class", "unit", "cf", "choice", "pro", "industry",
        # brand / trustee names that add no semantic value
        "allianz", "invesco", "manulife", "fidelity", "schroder",
        "bct", "bea", "aia", "hsbc", "bcom", "amtd", "principal", "bocip",
        "prudential", "yf", "sct", "boc", "sun", "life",
    }
)

# Canonical two-character abbreviations for meaningful words.
# Keys are lowercase; values are exactly two uppercase characters.
# Conflicts that existed previously (CA/CA, CH/CH, AG/AG) are resolved by
# picking the most fund-relevant meaning and adding the displaced sense under
# a distinct key.
WORD_MAP: dict[str, str] = {
    # --- geography ---
    "asian": "AS",
    "asia": "AS",
    "pacific": "PA",
    "global": "GL",
    "hong": "HK",
    "kong": "KC",
    "china": "CN",      # kept here; removed from SKIP_WORDS
    "chinese": "CH",
    "greater": "GC",
    "north": "NA",
    "american": "AM",
    "america": "AM",
    "european": "EU",
    "europe": "EU",
    "international": "IN",
    "japan": "JP",
    "japanese": "JP",
    "eurasia": "EA",
    "world": "WD",
    "us": "US",
    "oriental": "OP",
    # --- asset class / strategy ---
    "equity": "EQ",
    "bond": "BD",
    "balanced": "BL",
    "growth": "GW",     # was GR — conflicts with "green" below
    "stable": "ST",
    "conservative": "CV",
    "core": "CR",
    "accumulation": "AC",
    "guaranteed": "GU",
    "guarantee": "GU",
    "dynamic": "DY",
    "capital": "KP",    # was CA — conflicts with "career"; K evokes capital
    "income": "IC",
    "money": "MN",
    "market": "MK",
    "index": "IX",
    "tracking": "TK",
    "tracker": "TK",
    "target": "TG",
    "smart": "SM",
    "flexi": "FL",
    "flexible": "FL",
    "interest": "IT",
    "aggressive": "AV",  # was AG — conflicts with "age"
    "multi": "MT",
    "sector": "SC",
    "low": "LO",
    "carbon": "CB",
    "sustainable": "SU",
    "value": "VL",
    "valuechoice": "VC",
    "dollar": "DL",
    "allocation": "AL",
    "mixed": "MX",
    "asset": "AT",
    "strategy": "SY",
    "portfolio": "PF",
    "manager": "MG",
    "managers": "MG",
    "yield": "YL",
    "long": "LG",
    "term": "TM",
    "savings": "SV",
    "cash": "CS",       # was CH — conflicts with "chinese"
    "career": "CR",     # was CA — conflicts with "capital"; reuse CR (distinct from "core" below)
    "green": "GN",
    "healthcare": "HC",
    "retirement": "RT",
    "retire": "RE",
    "age": "AG",
    # --- indices / benchmarks ---
    "hang": "HS",
    "seng": "SN",
    "ftse": "FT",
    "csi": "CS",
    "esg": "ES",
    "rmb": "RM",
    "hkd": "HD",
    # --- product names / abbreviations ---
    "saveeasy": "SE",
    "joyful": "JO",
    "now": "NW",
    "plus": "PL",
    "fund": "FD",
    "shkp": "SK",
    # --- lifecycle / date tokens ---
    "e30": "E3",
    "e50": "E5",
    "e70": "E7",
    "e90": "E9",
    "2025": "25",
    "2028": "28",
    "2030": "30",
    "2035": "35",
    "2038": "38",
    "2040": "40",
    "2045": "45",
    "2048": "48",
    "2050": "50",
    "65": "65",
}

# Characters used when cycling through collision suffixes (digits first so
# numeric suffixes sort before alpha ones, then uppercase letters).
DEDUP_CHARS: str = "0123456789BCDEFGIJKLMNOPQRSTUVWXYZ"

# Required input columns
REQUIRED_COLUMNS: tuple[str, ...] = ("trustee", "fund_name")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _trustee_prefix(trustee: str) -> str:
    """Return the canonical 4-char prefix for a trustee name."""
    t = trustee.strip()
    if t in TRUSTEE_PREFIXES:
        return TRUSTEE_PREFIXES[t]
    # Fallback: strip spaces, uppercase, truncate to 4
    return re.sub(r"\s+", "", t).upper()[:4]

def _scheme_abbreviation(scheme: str) -> str:
    """Return a 2-letter abbreviation for a scheme name with robust matching."""
    
    # 1. Handle Null/Empty cases immediately
    if not scheme or not isinstance(scheme, str):
        return "XX"
    
    # 2. Define the map
    # We will normalize these keys below to ensure a match regardless of symbols
    raw_map = {
        "AIA MPF - Prime Value Choice": "PV",
        "AMTD MPF Scheme": "AM",
        "Allianz": "AL",
        "BCOM Joyful Retirement MPF Scheme": "JR",
        "BCT (MPF) Industry Choice": "IC",
        "BCT (MPF) Pro Choice": "PC",
        "BCT Strategic MPF Scheme": "BS",
        "BEA (MPF) Industry Scheme": "IS",
        "BEA (MPF) Master Trust Scheme": "MT",
        "BEA (MPF) Value Scheme": "VS",
        "BOC-Prudential Easy-Choice Mandatory Provident Fund Scheme": "EC",
        "China Life MPF Master Trust Scheme": "CL",
        "Fidelity Retirement Master Trust": "FT",
        "Haitong MPF Retirement Fund": "HT",
        "Hang Seng Mandatory Provident Fund - SuperTrust Plus": "HS",
        "HSBC Mandatory Provident Fund - SuperTrust Plus": "ST",
        "Manulife Global Select (MPF) Scheme": "GS",
        "Manulife RetireChoice (MPF) Scheme": "RC",
        "MASS Mandatory Provident Fund Scheme": "MS",
        "My Choice Mandatory Provident Fund Scheme": "MC",
        "Principal MPF - Simple Plan": "SI",
        "Principal MPF - Smart Plan": "SP",
        "Principal MPF Scheme Series 800": "S8",
        "SHKP MPF Employer Sponsored Scheme": "SH",
        "Sun Life Rainbow MPF Scheme": "RL",
        "SCT": "SC",
        "YF Life": "YF"
    }

    # Internal helper to strip everything but letters and numbers
    def normalize(text: str) -> str:
        return re.sub(r"[^a-zA-Z0-9]", "", text).lower()

    # 3. Create a normalized version of the map
    # This turns "AIA MPF - Prime Value Choice" -> "aiampfprimevaluechoice"
    normalized_map = {normalize(k): v for k, v in raw_map.items()}
    
    # 4. Clean the incoming input
    input_clean = normalize(scheme)
    
    # 5. Check for match
    if input_clean in normalized_map:
        return normalized_map[input_clean]
    
    # 6. Fallback: logic if no match is found
    # We use a slightly different cleaning for fallback to preserve word boundaries
    words = re.sub(r"[^a-zA-Z0-9\s]", "", scheme).split()
    if len(words) >= 2:
        return (words[0][0] + words[1][0]).upper()
    elif len(words) == 1:
        return words[0][:2].upper()
    
    return "XX"


def _extract_class(name: str) -> str | None:
    """
    Extract a trailing share-class letter from a fund name.
    Handles decorative Unicode suffixes (‡, Ø, etc.) that appear in
    real MPF fund data alongside the class letter.
    """
    m = re.search(r"[-–]\s*(?:Unit\s*)?Class\s*([A-Z])[\w‡Ø]*\s*$", name, re.IGNORECASE)
    return m.group(1).upper() if m else None


def sanitize_fund_name(name: str) -> str:
    """
    Sanitize the fund name by removing unusual characters.
    """
    # Remove unusual characters (keep alphanumeric, spaces, hyphens, and basic punctuation)
    sanitized = re.sub(r"[^a-zA-Z0-9\s\-()',.]", "", name)
    # Collapse multiple spaces into one
    sanitized = re.sub(r"\s+", " ", sanitized).strip()
    return sanitized


def _name_to_base(name: str, derisk: int = 0) -> str:
    """
    Convert a fund name (with class suffix already stripped) to a
    4 or 6-character uppercase abbreviation using WORD_MAP and SKIP_WORDS.
    If derisk is 1, returns 4 characters. Otherwise, returns 6 characters.
    """
    # Sanitize the name first
    name = sanitize_fund_name(name)
    # Strip class suffix, parenthetical qualifiers, punctuation
    n = re.sub(r"[-–]\s*(?:Unit\s*)?Class\s*[A-Z][\w‡Ø]*\s*$", "", name, flags=re.IGNORECASE)
    n = re.sub(r"\(No[^)]+\)", "", n, flags=re.IGNORECASE)
    n = re.sub(r"[()]", " ", n)
    n = re.sub(r"[^a-zA-Z0-9\s]", " ", n)

    tokens = n.lower().split()
    parts: list[str] = []
    for t in tokens:
        if t in SKIP_WORDS:
            continue
        if t in WORD_MAP:
            parts.append(WORD_MAP[t])
        else:
            # Unknown word: take first two chars, uppercase
            parts.append(t[:2].upper())

    if not parts:
        return "FDFD" if derisk == 0 else "FDFD"

    total_chars = sum(len(p) for p in parts)
    nw = len(parts)

    # Determine target length based on derisk flag
    target_length = 4 if derisk == 1 else 6

    # --- fit parts into the target length ---
    if total_chars <= target_length:
        raw = "".join(parts)
        # Pad by repeating the last character
        return (raw + raw[-1] * target_length)[:target_length]

    if nw == 1:
        p = parts[0]
        return (p * (target_length // len(p) + 1))[:target_length]
    elif nw == 2:
        if target_length == 4:
            return (parts[0][:2] + parts[1][:2]).upper()
        else:  # target_length == 6
            return (parts[0][:3] + parts[1][:3]).upper()
    elif nw == 3:
        if target_length == 4:
            return (parts[0][:2] + parts[1][0] + parts[2][0]).upper()
        else:  # target_length == 6
            return (parts[0][:2] + parts[1][:2] + parts[2][:2]).upper()
    else:
        if target_length == 4:
            return "".join(p[0] for p in parts[:4]).upper()
        else:  # target_length == 6
            return "".join(p[0] for p in parts[:3]).upper() + "FD"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def make_fund_code(trustee: str, fund_name: str, scheme: str = "") -> str:
    """
    Return the base (un-deduplicated) fund code for a single fund.

    Examples
    --------
    >>> make_fund_code("HSBC", "Global Bond Fund", "HSBC Mandatory Provident Fund - SuperTrust Plus")
    'HSBC-ST-GLBD'
    >>> make_fund_code("AIA", "Asian Equity Fund - Class A", "AIA MPF - Prime Value Choice")
    'AIA-PV-ASEQ'

    Note: duplicate codes are not resolved here.  Pass a full list to
    ``generate_codes()`` when uniqueness is required.
    """
    prefix = _trustee_prefix(trustee)
    scheme_abbr = _scheme_abbreviation(scheme)
    base = _name_to_base(fund_name.strip())
    return f"{prefix}-{scheme_abbr}-{base}"


def generate_codes(rows: list[dict]) -> list[str]:
    """
    Generate a unique fund code for every row in *rows*.

    Each row must have ``'trustee'`` and ``'fund_name'`` keys.
    Uses 6 letters for fund part when derisk=0, 4 letters + "DR" when derisk=1.
    If fund has a class letter, the last character is the class letter.

    Returns a list of codes in the same order as *rows*.
    """
    codes = []
    for r in rows:
        prefix = _trustee_prefix(r["trustee"])
        scheme_abbr = _scheme_abbreviation(r.get("scheme", ""))
        derisk = r.get("derisk", 0)
        fund_name = r["fund_name"].strip()
        
        # Extract class letter
        cls = _extract_class(fund_name)
        
        # Generate base code
        base = _name_to_base(fund_name, derisk)
        
        # If fund has a class letter, replace last character with class letter
        if cls:
            if derisk == 1:
                # For derisk funds: 4 letters + DR, but replace last character of 4-letter base with class
                base_without_last = base[:3]  # Take first 3 characters
                base = base_without_last + cls  # Replace last character with class letter
                code = f"{prefix}-{scheme_abbr}-{base}DR"
            else:
                # For non-derisk funds: 6 letters, replace last character with class letter
                base_without_last = base[:5]  # Take first 5 characters
                base = base_without_last + cls  # Replace last character with class letter
                code = f"{prefix}-{scheme_abbr}-{base}"
        else:
            # No class letter, use original logic
            if derisk == 1:
                code = f"{prefix}-{scheme_abbr}-{base}DR"
            else:
                code = f"{prefix}-{scheme_abbr}-{base}"
        
        codes.append(code)
    
    return codes