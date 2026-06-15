"""
census_acs_joiner.py
=====================
Pulls demographic data from the Census Bureau ACS API and joins it
to a district or precinct file by FIPS code.

Fetches from ACS 5-Year estimates (most reliable for small geographies).
Common use cases in political/redistricting work:
  - Total population, voting-age population (VAP), citizen VAP (CVAP)
  - Race/ethnicity breakdown by district
  - Median household income, educational attainment
  - Joining Census data to voter files or shapefiles

Author: Quentin Sprauve
Dependencies: requests, pandas
API key: Free from https://api.census.gov/data/key_signup.html
Usage:
    python census_acs_joiner.py \
        --fips-file districts.csv \
        --fips-col county_fips \
        --year 2022 \
        --geo county \
        --api-key YOUR_KEY \
        --output districts_with_demographics.csv
"""

import argparse
import logging
import os
import sys
import time
from typing import Optional

import pandas as pd
import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

CENSUS_BASE_URL = "https://api.census.gov/data/{year}/acs/acs5"

# ---------------------------------------------------------------------------
# ACS variable sets
# ---------------------------------------------------------------------------

# A curated set of variables useful for political/redistricting analysis
ACS_VARIABLES = {
    # Population
    "B01001_001E": "total_population",
    # Voting-age population (18+) — approximated from age groups
    "B01001_007E": "male_18_19",
    "B01001_008E": "male_20",
    "B01001_009E": "male_21",
    "B01001_010E": "male_22_24",
    "B01001_011E": "male_25_29",
    "B01001_012E": "male_30_34",
    "B01001_013E": "male_35_39",
    "B01001_014E": "male_40_44",
    "B01001_015E": "male_45_49",
    "B01001_016E": "male_50_54",
    "B01001_017E": "male_55_59",
    "B01001_018E": "male_60_61",
    "B01001_019E": "male_62_64",
    "B01001_020E": "male_65_66",
    "B01001_021E": "male_67_69",
    "B01001_022E": "male_70_74",
    "B01001_023E": "male_75_79",
    "B01001_024E": "male_80_84",
    "B01001_025E": "male_85_plus",
    # Race / ethnicity
    "B03002_001E": "total_hisp_race",
    "B03002_003E": "white_alone_non_hisp",
    "B03002_004E": "black_alone_non_hisp",
    "B03002_005E": "aian_alone_non_hisp",
    "B03002_006E": "asian_alone_non_hisp",
    "B03002_012E": "hispanic_or_latino",
    # Education (25+)
    "B15003_001E": "edu_total_25plus",
    "B15003_022E": "edu_bachelors",
    "B15003_023E": "edu_masters",
    "B15003_025E": "edu_doctorate",
    # Income
    "B19013_001E": "median_household_income",
    # Housing
    "B25001_001E": "total_housing_units",
    "B25003_002E": "owner_occupied",
    "B25003_003E": "renter_occupied",
}

MALE_VAP_COLS = [v for k, v in ACS_VARIABLES.items() if k.startswith("B01001_0") and "male_" in v]


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------

def fetch_acs(
    variables: list[str],
    geography: str,
    state_fips: Optional[str],
    year: int,
    api_key: str,
    retries: int = 3,
) -> pd.DataFrame:
    """Fetch ACS data for a geography level and return a DataFrame."""
    var_string = "NAME," + ",".join(variables)

    if geography == "county":
        geo_params = {"for": "county:*"}
        if state_fips:
            geo_params["in"] = f"state:{state_fips}"
    elif geography == "tract":
        if not state_fips:
            log.error("--state-fips required when --geo=tract")
            sys.exit(1)
        geo_params = {"for": "tract:*", "in": f"state:{state_fips}"}
    elif geography == "state":
        geo_params = {"for": "state:*"}
    else:
        log.error("Unsupported geography: %s. Choose from: county, tract, state.", geography)
        sys.exit(1)

    params = {"get": var_string, "key": api_key, **geo_params}
    url = CENSUS_BASE_URL.format(year=year)

    for attempt in range(1, retries + 1):
        try:
            log.info("Fetching %d ACS variables for %s (attempt %d) …", len(variables), geography, attempt)
            resp = requests.get(url, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            headers = data[0]
            rows = data[1:]
            df = pd.DataFrame(rows, columns=headers)
            log.info("Retrieved %d rows.", len(df))
            return df
        except requests.HTTPError as e:
            log.warning("HTTP error: %s", e)
            if attempt < retries:
                time.sleep(2 ** attempt)
        except Exception as e:
            log.error("Unexpected error: %s", e)
            sys.exit(1)

    log.error("All %d attempts failed.", retries)
    sys.exit(1)


# ---------------------------------------------------------------------------
# Processing
# ---------------------------------------------------------------------------

def process_acs_data(df: pd.DataFrame, geography: str) -> pd.DataFrame:
    """Rename columns, build FIPS codes, compute derived fields."""
    df = df.copy()

    # Rename ACS codes to readable names
    rename_map = {k: v for k, v in ACS_VARIABLES.items() if k in df.columns}
    df.rename(columns=rename_map, inplace=True)

    # Build full FIPS code
    if geography == "county":
        df["fips"] = df["state"].str.zfill(2) + df["county"].str.zfill(3)
    elif geography == "tract":
        df["fips"] = df["state"].str.zfill(2) + df["county"].str.zfill(3) + df["tract"].str.zfill(6)
    elif geography == "state":
        df["fips"] = df["state"].str.zfill(2)

    # Convert numeric columns
    numeric_cols = list(rename_map.values()) + ["fips"]
    for col in rename_map.values():
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # Derived: voting-age population (sum of male 18+ columns, ×2 for female approximation)
    vap_cols_present = [c for c in MALE_VAP_COLS if c in df.columns]
    if vap_cols_present:
        df["voting_age_pop_approx"] = df[vap_cols_present].sum(axis=1) * 2

    # Derived: college-educated rate
    if "edu_total_25plus" in df.columns and "edu_bachelors" in df.columns:
        ba_plus = df[["edu_bachelors", "edu_masters", "edu_doctorate"]].sum(axis=1)
        df["pct_college_plus"] = (ba_plus / df["edu_total_25plus"].replace(0, pd.NA) * 100).round(2)

    # Derived: percent Black non-Hispanic
    if "total_population" in df.columns and "black_alone_non_hisp" in df.columns:
        df["pct_black_non_hisp"] = (
            df["black_alone_non_hisp"] / df["total_population"].replace(0, pd.NA) * 100
        ).round(2)

    # Derived: percent Hispanic
    if "total_population" in df.columns and "hispanic_or_latino" in df.columns:
        df["pct_hispanic"] = (
            df["hispanic_or_latino"] / df["total_population"].replace(0, pd.NA) * 100
        ).round(2)

    return df


def join_to_district_file(
    district_df: pd.DataFrame,
    acs_df: pd.DataFrame,
    fips_col: str,
) -> pd.DataFrame:
    """Left-join ACS data to the district file on FIPS code."""
    district_df[fips_col] = district_df[fips_col].astype(str).str.zfill(5)
    acs_df["fips"] = acs_df["fips"].astype(str)

    merged = district_df.merge(acs_df, left_on=fips_col, right_on="fips", how="left")
    unmatched = merged["total_population"].isna().sum()
    if unmatched:
        log.warning("%d rows in district file did not match any ACS record.", unmatched)

    log.info("Joined %d district rows with ACS data.", len(merged))
    return merged


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Pull Census ACS data and join to a district/precinct file by FIPS."
    )
    p.add_argument("--fips-file",  required=True,        help="CSV with FIPS codes to join to")
    p.add_argument("--fips-col",   default="county_fips", help="FIPS column name in your file (default: county_fips)")
    p.add_argument("--year",       type=int, default=2022, help="ACS 5-year vintage (default: 2022)")
    p.add_argument("--geo",        default="county",      help="Geography: county | tract | state (default: county)")
    p.add_argument("--state-fips", default=None,          help="2-digit state FIPS (required for tract)")
    p.add_argument("--api-key",    default=None,          help="Census API key (or set CENSUS_API_KEY env var)")
    p.add_argument("--output",     required=True,         help="Output CSV path")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    api_key = args.api_key or os.environ.get("CENSUS_API_KEY")
    if not api_key:
        log.error("Provide --api-key or set CENSUS_API_KEY environment variable.")
        sys.exit(1)

    log.info("Loading district file: %s", args.fips_file)
    district_df = pd.read_csv(args.fips_file, dtype=str)

    variables = list(ACS_VARIABLES.keys())
    acs_raw = fetch_acs(
        variables=variables,
        geography=args.geo,
        state_fips=args.state_fips,
        year=args.year,
        api_key=api_key,
    )

    acs_clean = process_acs_data(acs_raw, geography=args.geo)
    result = join_to_district_file(district_df, acs_clean, fips_col=args.fips_col)

    result.to_csv(args.output, index=False)
    log.info("Output saved to %s (%d rows, %d columns)", args.output, len(result), len(result.columns))


if __name__ == "__main__":
    main()
