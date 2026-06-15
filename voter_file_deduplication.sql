-- ============================================================
-- Voter File Deduplication Across Counties
-- Author: Quentin Sprauve
-- Description: Identifies voters registered in multiple counties
--              using fuzzy name + DOB matching. Flags the likely
--              duplicate registrations for review or suppression.
--              Handles common data entry variations (nicknames,
--              hyphenated names, transposed DOBs).
-- Compatible: PostgreSQL / Amazon Redshift
-- ============================================================

-- NOTE: Requires pg_trgm extension for trigram similarity on PostgreSQL.
-- On Redshift, replace similarity() with EDIT_DISTANCE or a SOUNDEX approach.
-- CREATE EXTENSION IF NOT EXISTS pg_trgm;

WITH voter_base AS (
    -- Clean and standardize the voter universe before matching
    SELECT
        voter_id,
        county_fips,
        UPPER(TRIM(last_name))                          AS last_name_clean,
        UPPER(TRIM(first_name))                         AS first_name_clean,
        UPPER(LEFT(TRIM(first_name), 1))                AS first_initial,
        date_of_birth,
        registration_date,
        registration_status,
        -- Normalize DOB to catch transposition errors (MM/DD vs DD/MM)
        CASE
            WHEN EXTRACT(DAY FROM date_of_birth) <= 12
            THEN MAKE_DATE(
                    EXTRACT(YEAR  FROM date_of_birth)::INT,
                    EXTRACT(DAY   FROM date_of_birth)::INT,
                    EXTRACT(MONTH FROM date_of_birth)::INT
                )
        END                                             AS dob_transposed
    FROM voters
    WHERE registration_status IN ('ACTIVE', 'INACTIVE')
),

exact_matches AS (
    -- Step 1: Exact match on last name + DOB across different counties
    SELECT
        a.voter_id                  AS voter_id_a,
        b.voter_id                  AS voter_id_b,
        a.county_fips               AS county_a,
        b.county_fips               AS county_b,
        a.last_name_clean           AS last_name,
        a.first_name_clean          AS first_name_a,
        b.first_name_clean          AS first_name_b,
        a.date_of_birth             AS dob,
        a.registration_date         AS reg_date_a,
        b.registration_date         AS reg_date_b,
        a.registration_status       AS status_a,
        b.registration_status       AS status_b,
        'EXACT_LAST_DOB'            AS match_type
    FROM voter_base a
    JOIN voter_base b
        ON  a.last_name_clean   = b.last_name_clean
        AND a.date_of_birth     = b.date_of_birth
        AND a.county_fips       <> b.county_fips       -- different counties only
        AND a.voter_id          < b.voter_id            -- avoid self-joins & duplicates
),

transposed_dob_matches AS (
    -- Step 2: Same match but against the transposed DOB (catches MM/DD vs DD/MM errors)
    SELECT
        a.voter_id                  AS voter_id_a,
        b.voter_id                  AS voter_id_b,
        a.county_fips               AS county_a,
        b.county_fips               AS county_b,
        a.last_name_clean           AS last_name,
        a.first_name_clean          AS first_name_a,
        b.first_name_clean          AS first_name_b,
        a.date_of_birth             AS dob,
        a.registration_date         AS reg_date_a,
        b.registration_date         AS reg_date_b,
        a.registration_status       AS status_a,
        b.registration_status       AS status_b,
        'TRANSPOSED_DOB'            AS match_type
    FROM voter_base a
    JOIN voter_base b
        ON  a.last_name_clean   = b.last_name_clean
        AND a.date_of_birth     = b.dob_transposed
        AND a.county_fips       <> b.county_fips
        AND a.voter_id          < b.voter_id
    WHERE b.dob_transposed IS NOT NULL
),

fuzzy_name_matches AS (
    -- Step 3: Fuzzy first-name match (same last + DOB, but first name differs slightly)
    -- Catches: Bob/Robert, Liz/Elizabeth, hyphenated names, typos
    SELECT
        a.voter_id                  AS voter_id_a,
        b.voter_id                  AS voter_id_b,
        a.county_fips               AS county_a,
        b.county_fips               AS county_b,
        a.last_name_clean           AS last_name,
        a.first_name_clean          AS first_name_a,
        b.first_name_clean          AS first_name_b,
        a.date_of_birth             AS dob,
        a.registration_date         AS reg_date_a,
        b.registration_date         AS reg_date_b,
        a.registration_status       AS status_a,
        b.registration_status       AS status_b,
        'FUZZY_FIRST_NAME'          AS match_type
    FROM voter_base a
    JOIN voter_base b
        ON  a.last_name_clean   = b.last_name_clean
        AND a.date_of_birth     = b.date_of_birth
        AND a.county_fips       <> b.county_fips
        AND a.voter_id          < b.voter_id
        -- Trigram similarity > 0.5 catches nicknames and minor typos
        -- Comment out if pg_trgm is unavailable; use SOUNDEX alternative below
        AND similarity(a.first_name_clean, b.first_name_clean) > 0.5
        AND a.first_name_clean <> b.first_name_clean   -- exclude exact (already caught above)
    -- Redshift alternative: AND SOUNDEX(a.first_name_clean) = SOUNDEX(b.first_name_clean)
),

all_matches AS (
    SELECT * FROM exact_matches
    UNION ALL
    SELECT * FROM transposed_dob_matches
    UNION ALL
    SELECT * FROM fuzzy_name_matches
),

deduplicated_matches AS (
    -- Remove pairs found by multiple methods; keep most specific match type
    SELECT DISTINCT ON (voter_id_a, voter_id_b)
        voter_id_a,
        voter_id_b,
        county_a,
        county_b,
        last_name,
        first_name_a,
        first_name_b,
        dob,
        reg_date_a,
        reg_date_b,
        status_a,
        status_b,
        match_type,
        -- Flag which record to suppress (keep most recent active registration)
        CASE
            WHEN status_a = 'ACTIVE' AND status_b <> 'ACTIVE' THEN voter_id_b
            WHEN status_b = 'ACTIVE' AND status_a <> 'ACTIVE' THEN voter_id_a
            WHEN reg_date_a >= reg_date_b                      THEN voter_id_b
            ELSE voter_id_a
        END AS suggest_suppress_voter_id
    FROM all_matches
    ORDER BY voter_id_a, voter_id_b,
        CASE match_type
            WHEN 'EXACT_LAST_DOB'   THEN 1
            WHEN 'TRANSPOSED_DOB'   THEN 2
            WHEN 'FUZZY_FIRST_NAME' THEN 3
        END
)

-- Final output: suspected duplicates ranked by confidence
SELECT
    match_type,
    voter_id_a,
    voter_id_b,
    county_a,
    county_b,
    last_name,
    first_name_a,
    first_name_b,
    dob,
    reg_date_a,
    reg_date_b,
    status_a,
    status_b,
    suggest_suppress_voter_id
FROM deduplicated_matches
ORDER BY
    CASE match_type
        WHEN 'EXACT_LAST_DOB'   THEN 1
        WHEN 'TRANSPOSED_DOB'   THEN 2
        WHEN 'FUZZY_FIRST_NAME' THEN 3
    END,
    last_name,
    dob;
