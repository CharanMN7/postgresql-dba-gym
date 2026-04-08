-- Task 3: Performance Diagnosis
--
-- Seeds two pathological tables:
--
--   1. ``events``       — 80K rows, no indexes. The agent must add
--                         indexes covering both ``user_id`` and
--                         ``event_type``.
--   2. ``bloated_logs`` — 100K rows inserted, then 80% deleted, with
--                         NO autovacuum cleanup. Agent must reclaim
--                         the bloat.
--
-- The Python ``setup`` step that runs *after* this seed also:
--   * applies bad GUCs via ALTER SYSTEM (work_mem=64kB, random_page_cost=8,
--     effective_cache_size=32MB) and reloads the config
--   * spawns an idle-in-transaction blocker thread holding a row lock on
--     ``bloated_logs`` with application_name='dba_gym_blocker'
--
-- Together that gives the agent four independent symptoms to diagnose.

SET search_path TO task_schema, public;

-- ---------------------------------------------------------------------------
-- Issue 1: missing indexes
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS events (
    id          BIGSERIAL PRIMARY KEY,
    user_id     INTEGER     NOT NULL,
    event_type  TEXT        NOT NULL,
    payload     TEXT        NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL
);

INSERT INTO events (user_id, event_type, payload, created_at)
SELECT
    ((i * 2654435761) % 10000) + 1                                    AS user_id,
    (ARRAY['click','view','purchase','signup','logout'])[1 + (i % 5)] AS event_type,
    'payload-' || (i % 1000)                                          AS payload,
    (TIMESTAMPTZ '2024-01-01 00:00:00+00') + (i * INTERVAL '1 minute') AS created_at
FROM generate_series(1, 80000) AS gs(i);

ANALYZE events;

-- Pre-warm a few sequential scans so the agent's first EXPLAIN ANALYZE
-- shows realistic plan costs rather than cold-cache surprises.
SELECT count(*) FROM events WHERE user_id = 42;
SELECT count(*) FROM events WHERE event_type = 'purchase';
SELECT count(*) FROM events WHERE user_id = 1234 AND event_type = 'click';

-- ---------------------------------------------------------------------------
-- Issue 2: bloat
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bloated_logs (
    id         BIGSERIAL PRIMARY KEY,
    msg        TEXT        NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);

INSERT INTO bloated_logs (msg, created_at)
SELECT
    repeat('log entry ', 20),
    (TIMESTAMPTZ '2024-01-01 00:00:00+00') + (i * INTERVAL '1 second')
FROM generate_series(1, 100000) AS gs(i);

-- Delete 80% of rows but DO NOT VACUUM — this is the bloat the agent
-- must clean up.
DELETE FROM bloated_logs WHERE id % 5 <> 0;

ANALYZE bloated_logs;
