"""
tableau_export_formatter.py
============================
Reshapes raw query results or CSVs into the format Tableau expects.

Handles the most common friction points when feeding data to Tableau:
  - Wide → long (unpivot) for multi-year or multi-metric columns
  - Long → wide (pivot) when Tableau needs one row per entity
  - Date standardization (Tableau is strict about ISO 8601)
  - Null / empty string handling (Tableau treats them differently)
  - Column name sanitization (no spaces, special chars)
  - Splitting geographic identifiers (state, county from FIPS)

Author: Quentin Sprauve
Dependencies: pandas
Usage:
    # Unpivot year columns to long format:
    python tableau_export_formatter.py --input results.csv --mode unpivot \
        --id-cols district,party --value-cols 2018,2020,2022,2024 \
        --var-name election_year --value-name votes --output tableau_ready.csv

    # Pivot to wide format:
    python tableau_export_formatter.py --input results.csv --mode pivot \
        --index district --columns party --values votes --output wide.csv

    # Date-fix only:
    python tableau_export_formatter.py --input results.csv --mode dates \
        --date-cols registration_date,election_date --output fixed.csv
"""

import argparse
import logging
import re
import sys
from pathlib import Path

import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

DATE_FORMATS = ["%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y", "%Y%m%d", "%m/%d/%y"]


# ---------------------------------------------------------------------------
# Column sanitization
# ---------------------------------------------------------------------------

def sanitize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Tableau requires clean column names:
      - No leading/trailing spaces
      - No special characters except underscores
      - No numeric-only names (prefix with 'col_')
    """
    new_cols = []
    for col in df.columns:
        c = str(col).strip()
        c = re.sub(r"[\s\-\/\.]+", "_", c)
        c = re.sub(r"[^\w]", "", c)
        if re.match(r"^\d", c):
            c = "col_" + c
        new_cols.append(c.lower())
    df.columns = new_cols
    return df


# ---------------------------------------------------------------------------
# Date normalization
# ---------------------------------------------------------------------------

def normalize_dates(df: pd.DataFrame, date_cols: list[str]) -> pd.DataFrame:
    """Parse mixed-format dates and output ISO 8601 (YYYY-MM-DD)."""
    for col in date_cols:
        if col not in df.columns:
            log.warning("Date column '%s' not found — skipped.", col)
            continue
        parsed = pd.Series(pd.NaT, index=df.index)
        for fmt in DATE_FORMATS:
            mask = parsed.isna() & df[col].notna()
            if not mask.any():
                break
            parsed[mask] = pd.to_datetime(df.loc[mask, col], format=fmt, errors="coerce")
        unparsed = parsed.isna() & df[col].notna()
        if unparsed.any():
            log.warning("'%s': %d values could not be parsed as dates.", col, unparsed.sum())
        df[col] = parsed.dt.strftime("%Y-%m-%d")  # Tableau's preferred format
    return df


# ---------------------------------------------------------------------------
# Null handling
# ---------------------------------------------------------------------------

def fix_nulls(df: pd.DataFrame) -> pd.DataFrame:
    """
    Tableau distinguishes between null and empty string.
    Replace empty strings with actual NaN so Tableau shows them as null.
    """
    df = df.replace(r"^\s*$", pd.NA, regex=True)
    return df


# ---------------------------------------------------------------------------
# Reshape modes
# ---------------------------------------------------------------------------

def mode_unpivot(
    df: pd.DataFrame,
    id_cols: list[str],
    value_cols: list[str],
    var_name: str,
    value_name: str,
) -> pd.DataFrame:
    """
    Wide → long. Example use case: columns [2018, 2020, 2022, 2024]
    become rows under an 'election_year' column.
    """
    missing = [c for c in id_cols + value_cols if c not in df.columns]
    if missing:
        log.error("Columns not found: %s", missing)
        sys.exit(1)

    melted = df.melt(
        id_vars=id_cols,
        value_vars=value_cols,
        var_name=var_name,
        value_name=value_name,
    )
    log.info("Unpivoted: %d rows → %d rows", len(df), len(melted))
    return melted


def mode_pivot(
    df: pd.DataFrame,
    index_cols: list[str],
    columns_col: str,
    values_col: str,
    agg_func: str = "sum",
) -> pd.DataFrame:
    """
    Long → wide. Example: rows with party='DEM'/'REP'
    become columns dem_votes / rep_votes.
    """
    for col in index_cols + [columns_col, values_col]:
        if col not in df.columns:
            log.error("Column not found: '%s'", col)
            sys.exit(1)

    pivoted = df.pivot_table(
        index=index_cols,
        columns=columns_col,
        values=values_col,
        aggfunc=agg_func,
    ).reset_index()
    pivoted.columns.name = None
    log.info("Pivoted: %d rows → %d rows, %d columns", len(df), len(pivoted), len(pivoted.columns))
    return pivoted


def mode_dates_only(df: pd.DataFrame, date_cols: list[str]) -> pd.DataFrame:
    return normalize_dates(df, date_cols)


def mode_fips_split(df: pd.DataFrame, fips_col: str) -> pd.DataFrame:
    """
    Split a 5-digit county FIPS into state_fips (2) and county_fips (3).
    Useful when Tableau needs separate geographic fields.
    """
    if fips_col not in df.columns:
        log.error("FIPS column '%s' not found.", fips_col)
        sys.exit(1)
    df[fips_col] = df[fips_col].astype(str).str.zfill(5)
    df["state_fips"]  = df[fips_col].str[:2]
    df["county_fips"] = df[fips_col].str[2:]
    log.info("Split '%s' into state_fips and county_fips.", fips_col)
    return df


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Reshape and clean CSV files for Tableau ingestion."
    )
    p.add_argument("--input",      required=True,  help="Input CSV path")
    p.add_argument("--output",     required=True,  help="Output CSV path")
    p.add_argument(
        "--mode", required=True,
        choices=["unpivot", "pivot", "dates", "fips-split"],
        help="Transformation mode",
    )
    # Unpivot args
    p.add_argument("--id-cols",    default="",     help="Comma-separated ID columns (for unpivot)")
    p.add_argument("--value-cols", default="",     help="Comma-separated columns to unpivot")
    p.add_argument("--var-name",   default="variable", help="Name for the new variable column (default: variable)")
    p.add_argument("--value-name", default="value",    help="Name for the new value column (default: value)")
    # Pivot args
    p.add_argument("--index",      default="",     help="Comma-separated index columns (for pivot)")
    p.add_argument("--columns",    default="",     help="Column to pivot on (for pivot)")
    p.add_argument("--values",     default="",     help="Values column (for pivot)")
    p.add_argument("--agg",        default="sum",  help="Aggregation function (default: sum)")
    # Date args
    p.add_argument("--date-cols",  default="",     help="Comma-separated date columns to normalize")
    # FIPS args
    p.add_argument("--fips-col",   default="fips", help="FIPS column to split (default: fips)")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    if not Path(args.input).exists():
        log.error("Input file not found: %s", args.input)
        sys.exit(1)

    log.info("Loading %s …", args.input)
    df = pd.read_csv(args.input, dtype=str, low_memory=False)
    log.info("Loaded %d rows × %d columns", *df.shape)

    # Always run these
    df = fix_nulls(df)

    if args.mode == "unpivot":
        id_cols    = [c.strip() for c in args.id_cols.split(",") if c.strip()]
        value_cols = [c.strip() for c in args.value_cols.split(",") if c.strip()]
        df = mode_unpivot(df, id_cols, value_cols, args.var_name, args.value_name)

    elif args.mode == "pivot":
        index_cols = [c.strip() for c in args.index.split(",") if c.strip()]
        df = mode_pivot(df, index_cols, args.columns, args.values, args.agg)

    elif args.mode == "dates":
        date_cols = [c.strip() for c in args.date_cols.split(",") if c.strip()]
        df = mode_dates_only(df, date_cols)

    elif args.mode == "fips-split":
        df = mode_fips_split(df, args.fips_col)

    df = sanitize_columns(df)

    df.to_csv(args.output, index=False)
    log.info("Saved %d rows × %d columns to %s", *df.shape, args.output)


if __name__ == "__main__":
    main()
