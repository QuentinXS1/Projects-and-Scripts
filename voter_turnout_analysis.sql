-- ============================================================
-- Voter Turnout Analysis by District
-- Author: Quentin Sprauve
-- Description: Calculates turnout rates by legislative district,
--              compares to prior cycles, and flags low-turnout
--              precincts for targeted outreach.
-- Compatible: PostgreSQL / Amazon Redshift
-- ============================================================

WITH voter_universe AS (
    -- Base universe: all active registered voters per precinct
    SELECT
        v.precinct_id,
        v.district_id,
        d.district_name,
        d.district_type,          -- e.g. 'STATE_HOUSE', 'US_CONGRESS'
        COUNT(v.voter_id)         AS registered_voters
    FROM voters v
    JOIN districts d ON v.district_id = d.district_id
    WHERE v.registration_status = 'ACTIVE'
    GROUP BY 1, 2, 3, 4
),

election_results AS (
    -- Actual votes cast, joined by election cycle
    SELECT
        b.precinct_id,
        b.election_year,
        b.election_type,          -- e.g. 'PRIMARY', 'GENERAL'
        COUNT(b.ballot_id)        AS ballots_cast
    FROM ballots b
    WHERE b.election_year IN (2020, 2022, 2024)
    GROUP BY 1, 2, 3
),

turnout_by_precinct AS (
    SELECT
        vu.precinct_id,
        vu.district_id,
        vu.district_name,
        vu.district_type,
        er.election_year,
        er.election_type,
        vu.registered_voters,
        er.ballots_cast,
        ROUND(
            er.ballots_cast::NUMERIC / NULLIF(vu.registered_voters, 0) * 100,
            2
        )                         AS turnout_pct
    FROM voter_universe vu
    JOIN election_results er ON vu.precinct_id = er.precinct_id
),

district_summary AS (
    -- Roll up to district level with cycle-over-cycle comparison
    SELECT
        district_id,
        district_name,
        district_type,
        election_year,
        election_type,
        SUM(registered_voters)    AS total_registered,
        SUM(ballots_cast)         AS total_ballots,
        ROUND(
            SUM(ballots_cast)::NUMERIC / NULLIF(SUM(registered_voters), 0) * 100,
            2
        )                         AS district_turnout_pct,
        -- Compare to same election type, 2 cycles prior
        LAG(
            ROUND(
                SUM(ballots_cast)::NUMERIC / NULLIF(SUM(registered_voters), 0) * 100,
                2
            ),
            1
        ) OVER (
            PARTITION BY district_id, election_type
            ORDER BY election_year
        )                         AS prior_cycle_turnout_pct
    FROM turnout_by_precinct
    GROUP BY 1, 2, 3, 4, 5
),

low_turnout_precincts AS (
    -- Flag precincts that fell >10 pts below their district average in 2024
    SELECT
        tbp.precinct_id,
        tbp.district_name,
        tbp.election_year,
        tbp.election_type,
        tbp.turnout_pct           AS precinct_turnout_pct,
        ds.district_turnout_pct,
        tbp.turnout_pct - ds.district_turnout_pct AS pct_vs_district,
        CASE
            WHEN tbp.turnout_pct < ds.district_turnout_pct - 10 THEN 'FLAG: Low Turnout'
            ELSE 'OK'
        END                       AS outreach_flag
    FROM turnout_by_precinct tbp
    JOIN district_summary ds
        ON  tbp.district_id   = ds.district_id
        AND tbp.election_year  = ds.election_year
        AND tbp.election_type  = ds.election_type
    WHERE tbp.election_year = 2024
)

-- Final output: district summary with YoY change + low-turnout flags
SELECT
    ds.district_name,
    ds.district_type,
    ds.election_year,
    ds.election_type,
    ds.total_registered,
    ds.total_ballots,
    ds.district_turnout_pct,
    ds.prior_cycle_turnout_pct,
    ds.district_turnout_pct - ds.prior_cycle_turnout_pct AS turnout_change_pts,
    COUNT(ltp.precinct_id)        AS flagged_precincts
FROM district_summary ds
LEFT JOIN low_turnout_precincts ltp
    ON  ds.district_name  = ltp.district_name
    AND ds.election_year   = ltp.election_year
    AND ds.election_type   = ltp.election_type
    AND ltp.outreach_flag  = 'FLAG: Low Turnout'
WHERE ds.election_year = 2024
GROUP BY 1, 2, 3, 4, 5, 6, 7, 8, 9
ORDER BY turnout_change_pts ASC;   -- Surface biggest drops first
