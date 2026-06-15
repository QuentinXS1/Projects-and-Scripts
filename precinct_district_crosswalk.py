"""
precinct_district_crosswalk.py
================================
Builds a precinct-to-district crosswalk for precincts that split
across district boundaries — a common problem in redistricting.

For each precinct, computes:
  - Which districts it intersects
  - The percent of the precinct's area in each district
  - A "dominant district" (the one with the most area)
  - A "split" flag for precincts touching more than one district

Input : Two shapefiles — precincts and districts (must share a CRS or be reprojectable)
Output: CSV crosswalk table

Author: Quentin Sprauve
Dependencies: geopandas, pandas, shapely
Usage:
    python precinct_district_crosswalk.py \
        --precincts precincts.shp \
        --districts districts.shp \
        --precinct-id GEOID20 \
        --district-id DISTRICT \
        --output crosswalk.csv
"""

import argparse
import logging
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# Small buffer to handle floating-point boundary mismatches (in CRS units)
SNAP_TOLERANCE = 1e-6


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------

def build_crosswalk(
    gdf_precincts: gpd.GeoDataFrame,
    gdf_districts: gpd.GeoDataFrame,
    precinct_id_col: str,
    district_id_col: str,
) -> pd.DataFrame:
    """
    Intersect precincts with districts and compute area-based allocation.

    Returns a long-format DataFrame:
        precinct_id | district_id | intersection_area_sqmi | pct_of_precinct | dominant_district | is_split
    """
    # Align CRS
    if gdf_precincts.crs != gdf_districts.crs:
        log.info("Reprojecting districts to match precincts CRS (%s)", gdf_precincts.crs)
        gdf_districts = gdf_districts.to_crs(gdf_precincts.crs)

    # Use an equal-area projection for accurate area calculations
    log.info("Projecting to Conus Albers Equal Area (EPSG:5070) for area calculations …")
    precincts_ea = gdf_precincts[[precinct_id_col, "geometry"]].to_crs(epsg=5070).copy()
    districts_ea = gdf_districts[[district_id_col, "geometry"]].to_crs(epsg=5070).copy()

    precincts_ea["precinct_area_sqm"] = precincts_ea.geometry.area

    # Spatial intersection
    log.info("Running spatial intersection (%d precincts × %d districts) …",
             len(precincts_ea), len(districts_ea))
    intersected = gpd.overlay(precincts_ea, districts_ea, how="intersection", keep_geom_type=False)

    if intersected.empty:
        log.error("Intersection returned no results — check that the layers overlap.")
        sys.exit(1)

    intersected["intersection_area_sqm"] = intersected.geometry.area

    # Drop slivers (< 1 sq meter — floating point artifacts)
    intersected = intersected[intersected["intersection_area_sqm"] > 1].copy()

    # Compute percent of each precinct's total area in each district
    intersected = intersected.merge(
        precincts_ea[[precinct_id_col, "precinct_area_sqm"]],
        on=precinct_id_col,
        how="left",
    )
    intersected["pct_of_precinct"] = (
        intersected["intersection_area_sqm"] / intersected["precinct_area_sqm"]
    ).round(6)

    # Convert area to square miles
    SQM_TO_SQMI = 3.861e-7
    intersected["intersection_area_sqmi"] = (
        intersected["intersection_area_sqm"] * SQM_TO_SQMI
    ).round(4)

    # Drop geometry — output is tabular
    result = pd.DataFrame(intersected[[
        precinct_id_col,
        district_id_col,
        "intersection_area_sqmi",
        "pct_of_precinct",
    ]])

    # Dominant district per precinct (highest pct_of_precinct)
    dominant = (
        result.sort_values("pct_of_precinct", ascending=False)
        .drop_duplicates(subset=[precinct_id_col])
        [[precinct_id_col, district_id_col]]
        .rename(columns={district_id_col: "dominant_district"})
    )
    result = result.merge(dominant, on=precinct_id_col, how="left")

    # Split flag
    district_count = (
        result.groupby(precinct_id_col)[district_id_col]
        .nunique()
        .rename("district_count")
        .reset_index()
    )
    result = result.merge(district_count, on=precinct_id_col, how="left")
    result["is_split"] = result["district_count"] > 1
    result.drop(columns=["district_count"], inplace=True)

    result.sort_values([precinct_id_col, "pct_of_precinct"], ascending=[True, False], inplace=True)
    result.reset_index(drop=True, inplace=True)

    return result


def print_summary(df: pd.DataFrame, precinct_id_col: str, district_id_col: str) -> None:
    total_precincts = df[precinct_id_col].nunique()
    split_precincts = df[df["is_split"]][precinct_id_col].nunique()
    whole_precincts = total_precincts - split_precincts

    print("\n" + "=" * 55)
    print("CROSSWALK SUMMARY")
    print("=" * 55)
    print(f"  Total precincts          : {total_precincts:,}")
    print(f"  Whole precincts (1 dist) : {whole_precincts:,}")
    print(f"  Split precincts (2+ dist): {split_precincts:,}  ({split_precincts/total_precincts:.1%})")
    print(f"  Districts covered        : {df[district_id_col].nunique():,}")
    print(f"  Total crosswalk rows     : {len(df):,}")
    print("=" * 55 + "\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Build a precinct-to-district crosswalk with split-precinct detection."
    )
    p.add_argument("--precincts",    required=True,           help="Precinct shapefile path")
    p.add_argument("--districts",    required=True,           help="District shapefile path")
    p.add_argument("--precinct-id",  default="GEOID20",       help="Precinct ID column (default: GEOID20)")
    p.add_argument("--district-id",  default="DISTRICT",      help="District ID column (default: DISTRICT)")
    p.add_argument("--output",       default="crosswalk.csv", help="Output CSV path (default: crosswalk.csv)")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    for fpath in [args.precincts, args.districts]:
        if not Path(fpath).exists():
            log.error("File not found: %s", fpath)
            sys.exit(1)

    log.info("Loading precincts: %s", args.precincts)
    gdf_precincts = gpd.read_file(args.precincts)
    log.info("Loading districts: %s", args.districts)
    gdf_districts = gpd.read_file(args.districts)

    crosswalk = build_crosswalk(
        gdf_precincts=gdf_precincts,
        gdf_districts=gdf_districts,
        precinct_id_col=args.precinct_id,
        district_id_col=args.district_id,
    )

    print_summary(crosswalk, precinct_id_col=args.precinct_id, district_id_col=args.district_id)

    crosswalk.to_csv(args.output, index=False)
    log.info("Crosswalk saved to %s", args.output)


if __name__ == "__main__":
    main()
