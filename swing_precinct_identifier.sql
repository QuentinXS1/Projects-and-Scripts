-- ============================================================
-- Swing Precinct Identifier
-- Author: Quentin Sprauve
-- Description: Identifies precincts that flipped party between
--              election cycles, ranked by margin shift.
--              Useful for targeting, canvassing prioritization,
--              and post-election analysis.
-- Compatible: PostgreSQL / Amazon Redshift
-- ============================================================

WITH precinct_results AS (
    -- Raw vote totals by precinct, party, and election year
    SELECT
        r.precinct_id,
        p.precinct_name,
        p.district_id,
        d.district_name,
        r.election_year,
        r.election_type,
        r.party,
        SUM(r.votes) AS votes
    FROM election_results r
    JOIN precincts p   ON r.precinct_id  = p.precinct_id
    JOIN districts d   ON p.district_id  = d.district_id
    WHERE r.election_type = 'GENERAL'
      AND r.party IN ('DEM', 'REP')           -- two-party comparison only
      AND r.election_year IN (2020, 2024)
    GROUP BY 1, 2, 3, 4, 5, 6, 7
),

two_party_totals AS (
    -- Total two-party vote per precinct per cycle
    SELECT
        precinct_id,
        election_year,
        SUM(votes) AS two_party_total
    FROM precinct_results
    GROUP BY 1, 2
),

party_vote_share AS (
    -- DEM and REP vote share side by side
    SELECT
        pr.precinct_id,
        pr.precinct_name,
        pr.district_id,
        pr.district_name,
        pr.election_year,
        MAX(CASE WHEN pr.party = 'DEM' THEN pr.votes END) AS dem_votes,
        MAX(CASE WHEN pr.party = 'REP' THEN pr.votes END) AS rep_votes,
        tpt.two_party_total,
        ROUND(
            MAX(CASE WHEN pr.party = 'DEM' THEN pr.votes END)::NUMERIC
            / NULLIF(tpt.two_party_total, 0) * 100, 2
        )                                                  AS dem_pct,
        ROUND(
            MAX(CASE WHEN pr.party = 'REP' THEN pr.votes END)::NUMERIC
            / NULLIF(tpt.two_party_total, 0) * 100, 2
        )                                                  AS rep_pct,
        -- Positive = DEM margin, negative = REP margin
        ROUND(
            (MAX(CASE WHEN pr.party = 'DEM' THEN pr.votes END)::NUMERIC
           - MAX(CASE WHEN pr.party = 'REP' THEN pr.votes END)::NUMERIC)
            / NULLIF(tpt.two_party_total, 0) * 100, 2
        )                                                  AS dem_margin
    FROM precinct_results pr
    JOIN two_party_totals tpt
        ON  pr.precinct_id  = tpt.precinct_id
        AND pr.election_year = tpt.election_year
    GROUP BY 1, 2, 3, 4, 5, tpt.two_party_total
),

cycle_comparison AS (
    -- Pivot: 2020 vs 2024 side by side for each precinct
    SELECT
        a.precinct_id,
        a.precinct_name,
        a.district_id,
        a.district_name,
        a.dem_margin        AS margin_2020,
        b.dem_margin        AS margin_2024,
        b.dem_margin - a.dem_margin AS margin_shift,   -- positive = shift toward DEM
        a.two_party_total   AS total_votes_2020,
        b.two_party_total   AS total_votes_2024,
        -- Winning party each cycle
        CASE WHEN a.dem_margin >= 0 THEN 'DEM' ELSE 'REP' END AS winner_2020,
        CASE WHEN b.dem_margin >= 0 THEN 'DEM' ELSE 'REP' END AS winner_2024
    FROM party_vote_share a
    JOIN party_vote_share b
        ON  a.precinct_id   = b.precinct_id
        AND a.election_year = 2020
        AND b.election_year = 2024
),

swing_classification AS (
    SELECT
        *,
        CASE
            WHEN winner_2020 = 'REP' AND winner_2024 = 'DEM' THEN 'FLIPPED DEM'
            WHEN winner_2020 = 'DEM' AND winner_2024 = 'REP' THEN 'FLIPPED REP'
            WHEN winner_2020 = 'DEM' AND winner_2024 = 'DEM'
                 AND margin_shift >=  5 THEN 'MORE DEM'
            WHEN winner_2020 = 'REP' AND winner_2024 = 'REP'
                 AND margin_shift <= -5 THEN 'MORE REP'
            ELSE 'STABLE'
        END AS swing_category
    FROM cycle_comparison
)

-- Final output: sorted by absolute margin shift, flips first
SELECT
    precinct_id,
    precinct_name,
    district_name,
    winner_2020,
    winner_2024,
    swing_category,
    margin_2020,
    margin_2024,
    margin_shift,
    total_votes_2020,
    total_votes_2024,
    ABS(margin_shift) AS abs_shift
FROM swing_classification
WHERE swing_category <> 'STABLE'   -- remove this line to see all precincts
ORDER BY
    CASE swing_category
        WHEN 'FLIPPED DEM' THEN 1
        WHEN 'FLIPPED REP' THEN 2
        WHEN 'MORE DEM'    THEN 3
        WHEN 'MORE REP'    THEN 4
    END,
    abs_shift DESC;
