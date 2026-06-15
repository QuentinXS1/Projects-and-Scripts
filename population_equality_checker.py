"""
population_equality_checker.py
================================
Validates population equality across legislative districts after redistricting.

Legal standard (U.S.):
  - Congressional districts: must be as equal as practicable (~0.1% deviation)
  - State legislative districts: typically held to ±5% total deviation from ideal
  - This script flags any district outside a configurable threshold

Input: CSV or shapefile with district IDs and population counts
Output: Summary report + flagged districts CSV

Author: Quentin Sprauve
Dependencies: pandas, tabulate
Usage:
    python population_equality_checker.py --input districts.csv --pop-col TOTPOP --id-col DISTRICT
    python population_equality_checker.py --input districts.csv --threshold 0.05 --output flagged.csv
"""

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd

try:
    from tabulate import tabulate
    HAS_TABULATE = True
except ImportError:
    HAS_TABULATE = False

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------

def check_population_equality(
    df: pd.DataFrame,
    id_col: str,
    pop_col: str,
    threshold: float = 0.05,
) -> pd.DataFrame:
    """
    Calculate deviation from ideal district population.

    Parameters
    ----------
    df          : DataFrame with at least [id_col, pop_col]
    id_col      : Column name for district identifier
    pop_col     : Column name for population count
    threshold   : Maximum allowable deviation as a decimal (0.05 = ±5%)

    Returns
    -------
    DataFrame with deviation metrics and a FLAGGED column
    """
    if id_col not in df.columns or pop_col not in df.columns:
        log.error("Columns '%s' or '%s' not found. Available: %s", id_col, pop_col, list(df.columns))
        sys.exit(1)

    df = df[[id_col, pop_col]].copy()
    df[pop_col] = pd.to_numeric(df[pop_col], errors="coerce")

    null_pop = df[pop_col].isna().sum()
    if null_pop:
        log.warning("%d districts have null/non-numeric population — excluded.", null_pop)
        df = df.dropna(subset=[pop_col])

    n_districts = len(df)
    total_pop   = df[pop_col].sum()
    ideal_pop   = total_pop / n_districts

    log.info("Districts     : %d", n_districts)
    log.info("Total pop     : %s", f"{total_pop:,.0f}")
    log.info("Ideal pop     : %s", f"{ideal_pop:,.2f}")
    log.info("Threshold     : ±%.1f%%", threshold * 100)

    df["ideal_population"]    = round(ideal_pop, 2)
    df["deviation"]           = df[pop_col] - ideal_pop
    df["deviation_pct"]       = (df["deviation"] / ideal_pop).round(6)
    df["abs_deviation_pct"]   = df["deviation_pct"].abs()
    df["flagged"]             = df["abs_deviation_pct"] > threshold

    df.sort_values("abs_deviation_pct", ascending=False, inplace=True)
    df.reset_index(drop=True, inplace=True)

    return df


def print_report(df: pd.DataFrame, id_col: str, pop_col: str, threshold: float) -> None:
    flagged = df[df["flagged"]]
    n_flagged = len(flagged)
    max_dev = df["abs_deviation_pct"].max()
    total_dev = (df["abs_deviation_pct"].max() + df["abs_deviation_pct"].min())

    print("\n" + "=" * 60)
    print("POPULATION EQUALITY REPORT")
    print("=" * 60)
    print(f"  Districts checked   : {len(df)}")
    print(f"  Ideal population    : {df['ideal_population'].iloc[0]:,.2f}")
    print(f"  Max deviation       : {max_dev:.2%}")
    print(f"  Total deviation     : {total_dev:.2%}")
    print(f"  Threshold           : ±{threshold:.1%}")
    print(f"  Flagged districts   : {n_flagged}")

    if n_flagged:
        print(f"\n  ⚠  {n_flagged} district(s) exceed the ±{threshold:.1%} threshold:\n")
        display_cols = [id_col, pop_col, "ideal_population", "deviation", "deviation_pct"]
        display_df = flagged[display_cols].copy()
        display_df["deviation_pct"] = display_df["deviation_pct"].map("{:.2%}".format)

        if HAS_TABULATE:
            print(tabulate(display_df, headers="keys", tablefmt="simple", showindex=False))
        else:
            print(display_df.to_string(index=False))
    else:
        print(f"\n  ✓ All districts are within the ±{threshold:.1%} threshold.")

    print("=" * 60 + "\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Check population equality across redistricted legislative districts."
    )
    p.add_argument("--input",     required=True,           help="CSV with district population data")
    p.add_argument("--pop-col",   default="TOTPOP",        help="Population column name (default: TOTPOP)")
    p.add_argument("--id-col",    default="DISTRICT",      help="District ID column name (default: DISTRICT)")
    p.add_argument("--threshold", type=float, default=0.05, help="Max deviation as decimal (default: 0.05 = 5%%)")
    p.add_argument("--output",    default=None,            help="Optional: path to save flagged districts CSV")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    path = Path(args.input)
    if not path.exists():
        log.error("File not found: %s", args.input)
        sys.exit(1)

    log.info("Loading %s …", args.input)
    df_raw = pd.read_csv(args.input, dtype=str)

    results = check_population_equality(
        df=df_raw,
        id_col=args.id_col,
        pop_col=args.pop_col,
        threshold=args.threshold,
    )

    print_report(results, id_col=args.id_col, pop_col=args.pop_col, threshold=args.threshold)

    if args.output:
        flagged = results[results["flagged"]]
        flagged.to_csv(args.output, index=False)
        log.info("Flagged districts saved to %s", args.output)


if __name__ == "__main__":
    main()
