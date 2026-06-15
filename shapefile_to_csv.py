"""
shapefile_to_csv.py
===================
Converts a shapefile (.shp) to a clean CSV, with optional reprojection
to a standard coordinate reference system (CRS).

Handles common issues in political/redistricting shapefiles:
  - Reprojects to WGS84 (EPSG:4326) or any target CRS
  - Drops or retains geometry as WKT for downstream use
  - Normalizes column names (lowercase, no spaces)
  - Exports centroid lat/lon for each feature

Author: Quentin Sprauve
Dependencies: geopandas, pandas, shapely
Usage:
    python shapefile_to_csv.py --input districts.shp --output districts.csv
    python shapefile_to_csv.py --input precincts.shp --output precincts.csv --crs EPSG:4326 --keep-geometry
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Lowercase column names and replace spaces/special chars with underscores."""
    df.columns = (
        df.columns.str.strip()
        .str.lower()
        .str.replace(r"[\s\-\/]+", "_", regex=True)
        .str.replace(r"[^\w]", "", regex=True)
    )
    return df


def add_centroids(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Add centroid longitude and latitude columns (in WGS84)."""
    gdf_wgs = gdf.to_crs(epsg=4326)
    gdf["centroid_lon"] = gdf_wgs.geometry.centroid.x.round(6)
    gdf["centroid_lat"] = gdf_wgs.geometry.centroid.y.round(6)
    return gdf


def add_area_sq_miles(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Compute area in square miles using an equal-area projection."""
    gdf_ea = gdf.to_crs(epsg=5070)   # Conus Albers Equal Area
    gdf["area_sq_miles"] = (gdf_ea.geometry.area / 2_589_988.11).round(4)
    return gdf


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------

def shapefile_to_csv(
    input_path: str,
    output_path: str,
    target_crs: str = "EPSG:4326",
    keep_geometry: bool = False,
) -> None:
    path = Path(input_path)
    if not path.exists():
        log.error("Input file not found: %s", input_path)
        sys.exit(1)

    log.info("Reading shapefile: %s", input_path)
    gdf = gpd.read_file(input_path)
    log.info(
        "Loaded %d features | CRS: %s | Geometry type: %s",
        len(gdf),
        gdf.crs,
        gdf.geom_type.value_counts().to_dict(),
    )

    # Reproject
    if str(gdf.crs).upper() != target_crs.upper():
        log.info("Reprojecting from %s → %s", gdf.crs, target_crs)
        gdf = gdf.to_crs(target_crs)

    # Enrich with centroid and area
    gdf = add_centroids(gdf)
    gdf = add_area_sq_miles(gdf)

    # Normalize column names
    gdf = normalize_columns(gdf)

    # Optionally keep geometry as WKT
    if keep_geometry:
        gdf["geometry_wkt"] = gdf.geometry.apply(lambda g: g.wkt if g else None)
        log.info("Geometry retained as WKT column.")

    # Drop geometry column for CSV export
    df = pd.DataFrame(gdf.drop(columns=["geometry"]))

    df.to_csv(output_path, index=False)
    log.info("Exported %d rows to %s", len(df), output_path)

    # Quick summary
    print("\n--- Export Summary ---")
    print(f"  Rows      : {len(df):,}")
    print(f"  Columns   : {list(df.columns)}")
    print(f"  CRS used  : {target_crs}")
    print(f"  Output    : {output_path}\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Convert a shapefile to a clean CSV with optional reprojection."
    )
    p.add_argument("--input",         required=True,  help="Path to input .shp file")
    p.add_argument("--output",        required=True,  help="Path to output .csv file")
    p.add_argument("--crs",           default="EPSG:4326", help="Target CRS (default: EPSG:4326)")
    p.add_argument("--keep-geometry", action="store_true", help="Export geometry as WKT column")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    shapefile_to_csv(
        input_path=args.input,
        output_path=args.output,
        target_crs=args.crs,
        keep_geometry=args.keep_geometry,
    )
