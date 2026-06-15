# Quentin Sprauve – Data Analyst Portfolio

SQL, Python, and GIS scripts from my work in political data, redistricting, and voter analytics.

## About Me

I'm a data analyst with experience at **HaystaqDNA** and **Redistricting Data Hub**, where I supported political campaigns and nonprofit clients with data pipelines, geographic analysis, and custom reporting. I specialize in SQL, Python (Pandas / GeoPandas), GIS, and turning complex datasets into clear, actionable outputs for non-technical stakeholders.

---

## SQL Scripts

| Script | Description |
|--------|-------------|
| [`voter_turnout_analysis.sql`](sql-scripts/voter_turnout_analysis.sql) | Calculates turnout rates by legislative district across election cycles using CTEs and window functions. Flags precincts that fell >10 pts below their district average for outreach targeting. |
| [`swing_precinct_identifier.sql`](sql-scripts/swing_precinct_identifier.sql) | Identifies precincts that flipped party between 2020 and 2024, ranked by margin shift. Classifies each precinct as Flipped DEM, Flipped REP, More DEM, More REP, or Stable. |
| [`voter_registration_cohort_analysis.sql`](sql-scripts/voter_registration_cohort_analysis.sql) | Tracks new voter registrations by cohort month, computes rolling averages, flags volume spikes, and measures how each cohort turned out in subsequent elections. |
| [`voter_file_deduplication.sql`](sql-scripts/voter_file_deduplication.sql) | Detects voters registered in multiple counties using exact, transposed-DOB, and fuzzy first-name matching. Suggests which record to suppress based on registration status and recency. |

---

## Python Scripts

### Redistricting & GIS

| Script | Description |
|--------|-------------|
| [`shapefile_to_csv.py`](python-scripts/shapefile_to_csv.py) | Converts shapefiles to CSV with optional CRS reprojection. Adds centroid lat/lon and area in square miles. Normalizes column names for downstream use. |
| [`population_equality_checker.py`](python-scripts/population_equality_checker.py) | Validates district population balance after redistricting. Calculates deviation from the ideal population, flags districts outside a configurable threshold (default ±5%), and prints a legal-standard compliance report. |
| [`precinct_district_crosswalk.py`](python-scripts/precinct_district_crosswalk.py) | Builds a precinct-to-district crosswalk using spatial intersection. Computes the percent of each precinct's area in each district, identifies the dominant district, and flags split precincts. |

### Data Analysis & Integration

| Script | Description |
|--------|-------------|
| [`precinct_data_cleaner.py`](python-scripts/precinct_data_cleaner.py) | Cleans and standardizes raw precinct-level voter export files. Handles FIPS zero-padding, mixed date formats, duplicate voter IDs, invalid ZIP codes, and non-standard registration statuses. |
| [`census_acs_joiner.py`](python-scripts/census_acs_joiner.py) | Pulls demographic data (population, race/ethnicity, income, education) from the Census ACS API and joins it to a district or precinct file by FIPS code. Computes derived fields like voting-age population and % college-educated. |
| [`tableau_export_formatter.py`](python-scripts/tableau_export_formatter.py) | Reshapes raw query results for Tableau: wide↔long pivoting, ISO 8601 date normalization, null handling, column sanitization, and FIPS splitting. CLI-based with four modes. |
| [`newsletter_engagement_analyzer.py`](python-scripts/newsletter_engagement_analyzer.py) | Analyzes campaign-level newsletter data from Mailchimp/Klaviyo exports. Computes open, click, and unsubscribe rates; benchmarks against industry averages; surfaces top and bottom performers; and generates optional trend charts. |

---

## Skills & Tools

**Data & Databases** — SQL (PostgreSQL, Amazon Redshift), Snowflake, Google BigQuery, Azure, Databricks, Excel, Google Sheets

**Python** — Pandas, GeoPandas, Shapely, Matplotlib, Plotly, Jupyter Notebook

**GIS & Mapping** — ArcGIS, QGIS, Maptitude, shapefiles, redistricting, Census geographies

**BI & Visualization** — Tableau, Power BI, Looker, Plotly

**Political & Voter Data** — L2 Datamapping, NGP VAN, voter file processing, precinct-level analysis

**Web** — HTML, WordPress, JavaScript, Node.js, Next.js, MongoDB

**Compliance** — GDPR, CCPA, HIPAA

---

## Contact

- **LinkedIn:** [linkedin.com/in/quentin-sprauve-5b819893](https://www.linkedin.com/in/quentin-sprauve-5b819893/)
- **Email:** sprauveq@gmail.com
