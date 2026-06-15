-- ============================================================
-- Voter Registration Cohort Analysis
-- Author: Quentin Sprauve
-- Description: Tracks registration trends by cohort (registration
--              month/year), measures cohort retention through
--              subsequent elections, and surfaces months with
--              registration spikes or drops.
-- Compatible: PostgreSQL / Amazon Redshift
-- ============================================================

WITH registration_cohorts AS (
    -- Assign each voter to a cohort by registration month
    SELECT
        v.voter_id,
        v.county_fips,
        v.district_id,
        DATE_TRUNC('month', v.registration_date)::DATE AS cohort_month,
        v.registration_status,
        v.party_affiliation
    FROM voters v
    WHERE v.registration_date IS NOT NULL
      AND v.registration_date >= '2016-01-01'
),

cohort_size AS (
    -- How many voters registered in each cohort month
    SELECT
        cohort_month,
        party_affiliation,
        COUNT(voter_id)                                 AS registrations,
        COUNT(CASE WHEN registration_status = 'ACTIVE'   THEN 1 END) AS still_active,
        COUNT(CASE WHEN registration_status = 'INACTIVE' THEN 1 END) AS inactive,
        COUNT(CASE WHEN registration_status = 'CANCELLED'THEN 1 END) AS cancelled
    FROM registration_cohorts
    GROUP BY 1, 2
),

monthly_totals AS (
    -- Aggregate across parties for overall trend
    SELECT
        cohort_month,
        SUM(registrations)  AS total_registrations,
        SUM(still_active)   AS total_active,
        SUM(inactive)       AS total_inactive,
        SUM(cancelled)      AS total_cancelled,
        ROUND(SUM(still_active)::NUMERIC / NULLIF(SUM(registrations), 0) * 100, 2) AS retention_pct
    FROM cohort_size
    GROUP BY 1
),

rolling_avg AS (
    -- 3-month rolling average of new registrations
    SELECT
        cohort_month,
        total_registrations,
        retention_pct,
        ROUND(
            AVG(total_registrations) OVER (
                ORDER BY cohort_month
                ROWS BETWEEN 2 PRECEDING AND CURRENT ROW
            ), 1
        )                                               AS rolling_3mo_avg,
        -- Month-over-month change
        total_registrations
            - LAG(total_registrations) OVER (ORDER BY cohort_month) AS mom_change,
        ROUND(
            (total_registrations::NUMERIC
             - LAG(total_registrations) OVER (ORDER BY cohort_month))
            / NULLIF(LAG(total_registrations) OVER (ORDER BY cohort_month), 0) * 100,
            2
        )                                               AS mom_change_pct
    FROM monthly_totals
),

election_turnout AS (
    -- Which cohorts actually voted in each election?
    SELECT
        DATE_TRUNC('month', v.registration_date)::DATE  AS cohort_month,
        b.election_year,
        b.election_type,
        COUNT(DISTINCT b.voter_id)                      AS cohort_voters_who_voted
    FROM ballots b
    JOIN voters v ON b.voter_id = v.voter_id
    WHERE b.election_year IN (2018, 2020, 2022, 2024)
    GROUP BY 1, 2, 3
),

cohort_participation AS (
    -- Join cohort sizes with turnout by election
    SELECT
        cs.cohort_month,
        et.election_year,
        et.election_type,
        SUM(cs.registrations)             AS cohort_size,
        et.cohort_voters_who_voted,
        ROUND(
            et.cohort_voters_who_voted::NUMERIC
            / NULLIF(SUM(cs.registrations), 0) * 100,
            2
        )                                 AS cohort_turnout_pct
    FROM cohort_size cs
    JOIN election_turnout et ON cs.cohort_month = et.cohort_month
    GROUP BY 1, 2, 3, et.cohort_voters_who_voted
),

spike_detection AS (
    -- Flag months with registration volume > 1.5x rolling average (spikes)
    SELECT
        cohort_month,
        total_registrations,
        rolling_3mo_avg,
        retention_pct,
        mom_change,
        mom_change_pct,
        CASE
            WHEN total_registrations > rolling_3mo_avg * 1.5 THEN 'SPIKE'
            WHEN total_registrations < rolling_3mo_avg * 0.5 THEN 'DROP'
            ELSE 'NORMAL'
        END                               AS volume_flag
    FROM rolling_avg
)

-- Final output 1: Monthly trend with spike flags
SELECT
    sd.cohort_month,
    sd.total_registrations,
    sd.rolling_3mo_avg,
    sd.mom_change,
    sd.mom_change_pct,
    sd.retention_pct,
    sd.volume_flag,
    -- Participation rates in each major election for this cohort
    MAX(CASE WHEN cp.election_year = 2020 AND cp.election_type = 'GENERAL'
             THEN cp.cohort_turnout_pct END) AS turnout_2020_general,
    MAX(CASE WHEN cp.election_year = 2022 AND cp.election_type = 'GENERAL'
             THEN cp.cohort_turnout_pct END) AS turnout_2022_general,
    MAX(CASE WHEN cp.election_year = 2024 AND cp.election_type = 'GENERAL'
             THEN cp.cohort_turnout_pct END) AS turnout_2024_general
FROM spike_detection sd
LEFT JOIN cohort_participation cp ON sd.cohort_month = cp.cohort_month
GROUP BY 1, 2, 3, 4, 5, 6, 7
ORDER BY sd.cohort_month;
