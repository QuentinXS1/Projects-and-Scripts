"""
newsletter_engagement_analyzer.py
===================================
Analyzes newsletter engagement from a Mailchimp, Klaviyo, or
generic email platform export.

Computes:
  - Open rate, click rate, unsubscribe rate per campaign
  - Trend over time (rolling averages)
  - Segment comparison (e.g. list, tag, audience)
  - Top and bottom performing campaigns
  - Subscriber health summary (active vs. disengaged)

Expected input: CSV export with columns including at minimum:
    campaign_id, campaign_name, send_date, recipients,
    opens, clicks, unsubscribes

Author: Quentin Sprauve
Dependencies: pandas, matplotlib (optional for charts)
Usage:
    python newsletter_engagement_analyzer.py --input campaigns.csv
    python newsletter_engagement_analyzer.py --input campaigns.csv --segment audience --chart
"""

import argparse
import logging
import sys
from pathlib import Path
from typing import Optional

import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# Industry benchmarks (general email marketing averages)
BENCHMARKS = {
    "open_rate":        0.215,   # 21.5%
    "click_rate":       0.025,   # 2.5%
    "unsubscribe_rate": 0.002,   # 0.2%
    "click_to_open":    0.11,    # 11%
}

# Minimum column requirements
REQUIRED_COLS = ["campaign_id", "campaign_name", "send_date", "recipients", "opens", "clicks"]


# ---------------------------------------------------------------------------
# Loading & validation
# ---------------------------------------------------------------------------

def load_and_validate(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, dtype=str, low_memory=False)
    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        log.error("Missing required columns: %s\nFound: %s", missing, list(df.columns))
        sys.exit(1)

    # Parse numerics
    for col in ["recipients", "opens", "clicks"]:
        df[col] = pd.to_numeric(df[col].str.replace(",", ""), errors="coerce")
    if "unsubscribes" in df.columns:
        df["unsubscribes"] = pd.to_numeric(df["unsubscribes"].str.replace(",", ""), errors="coerce").fillna(0)
    else:
        df["unsubscribes"] = 0

    # Parse dates
    df["send_date"] = pd.to_datetime(df["send_date"], infer_datetime_format=True, errors="coerce")
    bad_dates = df["send_date"].isna().sum()
    if bad_dates:
        log.warning("%d rows have unparseable send_date — excluded.", bad_dates)
        df = df.dropna(subset=["send_date"])

    df.sort_values("send_date", inplace=True)
    df.reset_index(drop=True, inplace=True)
    log.info("Loaded %d campaigns (%s → %s)",
             len(df), df["send_date"].min().date(), df["send_date"].max().date())
    return df


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def compute_rates(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["open_rate"]        = (df["opens"]        / df["recipients"].replace(0, pd.NA)).round(4)
    df["click_rate"]       = (df["clicks"]       / df["recipients"].replace(0, pd.NA)).round(4)
    df["unsubscribe_rate"] = (df["unsubscribes"] / df["recipients"].replace(0, pd.NA)).round(4)
    df["click_to_open"]    = (df["clicks"]       / df["opens"].replace(0, pd.NA)).round(4)

    # Flag vs benchmark
    for metric, benchmark in BENCHMARKS.items():
        if metric in df.columns:
            df[f"{metric}_vs_benchmark"] = (df[metric] - benchmark).round(4)

    return df


def rolling_trend(df: pd.DataFrame, window: int = 4) -> pd.DataFrame:
    """Compute rolling average of key rates over N campaigns."""
    for col in ["open_rate", "click_rate", "unsubscribe_rate"]:
        if col in df.columns:
            df[f"{col}_rolling{window}"] = (
                df[col].rolling(window, min_periods=1).mean().round(4)
            )
    return df


def segment_summary(df: pd.DataFrame, segment_col: str) -> pd.DataFrame:
    """Aggregate metrics by a segment column (e.g. audience, tag, type)."""
    if segment_col not in df.columns:
        log.warning("Segment column '%s' not found — skipping segment analysis.", segment_col)
        return pd.DataFrame()

    summary = (
        df.groupby(segment_col)
        .agg(
            campaigns=("campaign_id", "count"),
            total_recipients=("recipients", "sum"),
            total_opens=("opens", "sum"),
            total_clicks=("clicks", "sum"),
            total_unsubscribes=("unsubscribes", "sum"),
            avg_open_rate=("open_rate", "mean"),
            avg_click_rate=("click_rate", "mean"),
            avg_unsubscribe_rate=("unsubscribe_rate", "mean"),
        )
        .round(4)
        .reset_index()
    )
    summary.sort_values("avg_open_rate", ascending=False, inplace=True)
    return summary


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def print_overall_summary(df: pd.DataFrame) -> None:
    total_recipients = df["recipients"].sum()
    total_opens      = df["opens"].sum()
    total_clicks     = df["clicks"].sum()
    total_unsubs     = df["unsubscribes"].sum()

    overall_open  = total_opens  / total_recipients if total_recipients else 0
    overall_click = total_clicks / total_recipients if total_recipients else 0
    overall_unsub = total_unsubs / total_recipients if total_recipients else 0

    print("\n" + "=" * 60)
    print("NEWSLETTER ENGAGEMENT SUMMARY")
    print("=" * 60)
    print(f"  Campaigns analyzed  : {len(df)}")
    print(f"  Date range          : {df['send_date'].min().date()} → {df['send_date'].max().date()}")
    print(f"  Total recipients    : {total_recipients:,.0f}")
    print()
    print(f"  {'Metric':<22} {'Yours':>8}  {'Benchmark':>10}  {'Delta':>8}")
    print(f"  {'-'*22} {'-'*8}  {'-'*10}  {'-'*8}")
    metrics = [
        ("Open rate",        overall_open,  BENCHMARKS["open_rate"]),
        ("Click rate",       overall_click, BENCHMARKS["click_rate"]),
        ("Unsubscribe rate", overall_unsub, BENCHMARKS["unsubscribe_rate"]),
    ]
    for label, val, bench in metrics:
        delta = val - bench
        arrow = "▲" if delta >= 0 else "▼"
        print(f"  {label:<22} {val:>7.1%}  {bench:>10.1%}  {arrow}{abs(delta):>6.1%}")
    print()


def print_top_bottom(df: pd.DataFrame, n: int = 5) -> None:
    print("  TOP CAMPAIGNS (by open rate):")
    top = df.nlargest(n, "open_rate")[["campaign_name", "send_date", "recipients", "open_rate", "click_rate"]]
    top["send_date"] = top["send_date"].dt.strftime("%Y-%m-%d")
    top["open_rate"]  = top["open_rate"].map("{:.1%}".format)
    top["click_rate"] = top["click_rate"].map("{:.1%}".format)
    print(top.to_string(index=False))
    print()
    print("  BOTTOM CAMPAIGNS (by open rate):")
    bot = df.nsmallest(n, "open_rate")[["campaign_name", "send_date", "recipients", "open_rate", "click_rate"]]
    bot["send_date"] = bot["send_date"].dt.strftime("%Y-%m-%d")
    bot["open_rate"]  = bot["open_rate"].map("{:.1%}".format)
    bot["click_rate"] = bot["click_rate"].map("{:.1%}".format)
    print(bot.to_string(index=False))
    print("=" * 60 + "\n")


def maybe_chart(df: pd.DataFrame) -> None:
    try:
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates

        fig, axes = plt.subplots(3, 1, figsize=(12, 9), sharex=True)
        fig.suptitle("Newsletter Engagement Over Time", fontsize=14)

        metrics = [
            ("open_rate",        "Open Rate",        "steelblue"),
            ("click_rate",       "Click Rate",        "seagreen"),
            ("unsubscribe_rate", "Unsubscribe Rate",  "firebrick"),
        ]
        for ax, (col, label, color) in zip(axes, metrics):
            ax.plot(df["send_date"], df[col], alpha=0.4, color=color, linewidth=1)
            if f"{col}_rolling4" in df.columns:
                ax.plot(df["send_date"], df[f"{col}_rolling4"], color=color, linewidth=2, label="4-campaign avg")
            ax.axhline(BENCHMARKS[col], color="gray", linestyle="--", linewidth=1, label="Benchmark")
            ax.set_ylabel(label)
            ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda y, _: f"{y:.1%}"))
            ax.legend(fontsize=8)
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))

        plt.tight_layout()
        out = "engagement_chart.png"
        plt.savefig(out, dpi=150, bbox_inches="tight")
        log.info("Chart saved to %s", out)
    except ImportError:
        log.warning("matplotlib not installed — skipping chart. pip install matplotlib to enable.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Analyze newsletter engagement from a campaign export CSV."
    )
    p.add_argument("--input",    required=True,        help="Campaign CSV export path")
    p.add_argument("--segment",  default=None,         help="Column to segment by (e.g. audience, tag)")
    p.add_argument("--output",   default=None,         help="Optional: save enriched data to CSV")
    p.add_argument("--chart",    action="store_true",  help="Generate a trend chart (requires matplotlib)")
    p.add_argument("--top",      type=int, default=5,  help="Number of top/bottom campaigns to show (default: 5)")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    if not Path(args.input).exists():
        log.error("File not found: %s", args.input)
        sys.exit(1)

    df = load_and_validate(args.input)
    df = compute_rates(df)
    df = rolling_trend(df)

    print_overall_summary(df)
    print_top_bottom(df, n=args.top)

    if args.segment:
        seg = segment_summary(df, args.segment)
        if not seg.empty:
            print(f"  SEGMENT BREAKDOWN ({args.segment.upper()}):")
            print(seg.to_string(index=False))
            print()

    if args.chart:
        maybe_chart(df)

    if args.output:
        df["send_date"] = df["send_date"].dt.strftime("%Y-%m-%d")
        df.to_csv(args.output, index=False)
        log.info("Enriched data saved to %s", args.output)


if __name__ == "__main__":
    main()
