"""
precinct_data_cleaner.py
========================
Cleans and standardizes raw precinct-level voter export files.

Common issues handled:
  - Inconsistent county/district name casing and whitespace
  - Mixed FIPS code formats (leading zeros stripped by Excel)
  - Duplicate voter records across file batches
  - Missing or malformed ZIP codes
  - Non-standard date formats in registration fields

Author: Quentin Sprauve
Usage:
    python precinct_data_cleaner.py --input raw_voters.csv --output clean_voters.csv
"""

import argparse
import logging
import re
import sys

import pandas as pd

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
EXPECTED_COLUMNS = [
    "voter_id",
    "last_name",
    "first_name",
    "registration_date",
    "county_fips",
    "precinct_id",
    "district_name",
    "zip_code",
    "registration_status",
]

VALID_STATUSES = {"ACTIVE", "INACTIVE", "CANCELLED", "PENDING"}

DATE_FORMATS = ["%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y", "%Y%m%d"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def normalize_fips(series: pd.Series, fips_length: int = 5) -> pd.Series:
    """Zero-pad FIPS codes stripped of leading zeros by Excel."""
    return (
        series.astype(str)
        .str.strip()
        .str.zfill(fips_length)
    )


def normalize_zip(series: pd.Series) -> pd.Series:
    """Standardize ZIP codes to 5-digit strings; flag invalid entries."""
    cleaned = series.astype(str).str.strip().str[:5].str.zfill(5)
    invalid_mask = ~cleaned.str.match(r"^\d{5}$")
    if invalid_mask.any():
        log.warning(
            "%d rows have invalid ZIP codes — set to NaN.", invalid_mask.sum()
        )
        cleaned[invalid_mask] = pd.NA
    return cleaned


def parse_dates(series: pd.Series) -> pd.Series:
    """Try multiple date formats; return NaT for anything unparseable."""
    parsed = pd.Series(pd.NaT, index=series.index)
    remaining = series.copy()

    for fmt in DATE_FORMATS:
        mask = parsed.isna() & remaining.notna()
        if not mask.any():
            break
        attempt = pd.to_datetime(remaining[mask], format=fmt, errors="coerce")
        parsed[mask] = attempt

    unparsed = parsed.isna() & series.notna()
    if unparsed.any():
        log.warning(
            "%d registration_date values could not be parsed.", unparsed.sum()
        )
    return parsed


def standardize_text(series: pd.Series) -> pd.Series:
    """Strip whitespace, collapse internal spaces, title-case."""
    return (
        series.astype(str)
        .str.strip()
        .str.replace(r"\s+", " ", regex=True)
        .str.title()
    )


# ---------------------------------------------------------------------------
# Core cleaning pipeline
# ---------------------------------------------------------------------------

def clean_voter_file(df: pd.DataFrame) -> pd.DataFrame:
    log.info("Input shape: %s rows × %s columns", *df.shape)

    # 1. Column validation
    missing = [c for c in EXPECTED_COLUMNS if c not in df.columns]
    if missing:
        log.error("Missing expected columns: %s", missing)
        sys.exit(1)
    df = df[EXPECTED_COLUMNS].copy()

    # 2. Drop exact duplicates
    before = len(df)
    df.drop_duplicates(inplace=True)
    log.info("Dropped %d exact duplicate rows.", before - len(df))

    # 3. Deduplicate on voter_id (keep most recent registration date)
    #    — parse dates first so we can sort
    df["registration_date"] = parse_dates(df["registration_date"])
    before = len(df)
    df.sort_values("registration_date", ascending=False, inplace=True)
    df.drop_duplicates(subset=["voter_id"], keep="first", inplace=True)
    log.info(
        "Dropped %d rows with duplicate voter_id (kept most recent).",
        before - len(df),
    )

    # 4. Normalize FIPS codes
    df["county_fips"] = normalize_fips(df["county_fips"], fips_length=5)

    # 5. Normalize ZIP codes
    df["zip_code"] = normalize_zip(df["zip_code"])

    # 6. Standardize text fields
    for col in ("last_name", "first_name", "district_name"):
        df[col] = standardize_text(df[col])

    # 7. Uppercase and validate registration_status
    df["registration_status"] = (
        df["registration_status"].astype(str).str.strip().str.upper()
    )
    invalid_status = ~df["registration_status"].isin(VALID_STATUSES)
    if invalid_status.any():
        log.warning(
            "%d rows have unrecognized registration_status — set to NaN.\n"
            "  Values: %s",
            invalid_status.sum(),
            df.loc[invalid_status, "registration_status"].unique().tolist(),
        )
        df.loc[invalid_status, "registration_status"] = pd.NA

    # 8. Strip whitespace from precinct_id
    df["precinct_id"] = df["precinct_id"].astype(str).str.strip()

    # 9. Sort for readability
    df.sort_values(["district_name", "precinct_id", "last_name"], inplace=True)
    df.reset_index(drop=True, inplace=True)

    log.info("Output shape: %s rows × %s columns", *df.shape)
    return df


# ---------------------------------------------------------------------------
# Summary report
# ---------------------------------------------------------------------------

def print_summary(df: pd.DataFrame) -> None:
    print("\n" + "=" * 50)
    print("CLEAN FILE SUMMARY")
    print("=" * 50)
    print(f"  Total voters      : {len(df):,}")
    print(f"  Districts         : {df['district_name'].nunique()}")
    print(f"  Precincts         : {df['precinct_id'].nunique()}")
    print(f"  Counties (FIPS)   : {df['county_fips'].nunique()}")
    print()
    print("  Registration status breakdown:")
    status_counts = df["registration_status"].value_counts(dropna=False)
    for status, count in status_counts.items():
        print(f"    {str(status):<12} {count:>8,}")
    print()
    print("  Missing values:")
    nulls = df.isnull().sum()
    nulls = nulls[nulls > 0]
    if nulls.empty:
        print("    None")
    else:
        for col, n in nulls.items():
            print(f"    {col:<25} {n:>6,}")
    print("=" * 50 + "\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Clean precinct-level voter export files.")
    p.add_argument("--input",  required=True, help="Path to raw CSV input file")
    p.add_argument("--output", required=True, help="Path to write cleaned CSV")
    p.add_argument(
        "--delimiter", default=",", help="CSV delimiter (default: ',')"
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()

    log.info("Loading %s …", args.input)
    df_raw = pd.read_csv(args.input, sep=args.delimiter, dtype=str, low_memory=False)

    df_clean = clean_voter_file(df_raw)
    print_summary(df_clean)

    df_clean.to_csv(args.output, index=False)
    log.info("Cleaned file written to %s", args.output)


if __name__ == "__main__":
    main()
