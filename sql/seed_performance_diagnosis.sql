-- seed_performance_diagnosis.sql
-- Creates a PostgreSQL 16 training environment with exactly 4 simultaneous problems:
-- (1) missing indexes, (2) table bloat, (3) bad config values, (4) idle transaction lock scenario.

DROP TABLE IF EXISTS transactions CASCADE;
DROP TABLE IF EXISTS logs CASCADE;
DROP TABLE IF EXISTS lock_test CASCADE;

-- =========================================================
-- Problem 1: Missing indexes on a hot table
-- =========================================================
CREATE TABLE transactions (
    id SERIAL PRIMARY KEY,
    account_id INTEGER NOT NULL,
    transaction_date TIMESTAMP NOT NULL,
    merchant VARCHAR(100) NOT NULL,
    category VARCHAR(50) NOT NULL,
    amount DECIMAL(10,2) NOT NULL,
    status VARCHAR(20) NOT NULL,
    region VARCHAR(50) NOT NULL
);

INSERT INTO transactions (
    account_id,
    transaction_date,
    merchant,
    category,
    amount,
    status,
    region
)
SELECT
    (1 + floor(random() * 10000))::INT AS account_id,
    now() - (interval '730 days' * (1 - power(random(), 2.1))) AS transaction_date,
    (ARRAY[
        'Amazon', 'Walmart', 'Target', 'Costco', 'eBay',
        'Apple', 'Netflix', 'Uber', 'Airbnb', 'Starbucks'
    ])[1 + floor(random() * 10)::INT] AS merchant,
    (ARRAY[
        'Retail', 'Groceries', 'Electronics', 'Travel', 'Dining',
        'Utilities', 'Entertainment', 'Health'
    ])[1 + floor(random() * 8)::INT] AS category,
    LEAST(
        4999.99,
        GREATEST(
            1.00,
            round((exp(ln(1.00) + random() * (ln(4999.99) - ln(1.00))))::numeric, 2)
        )
    )::DECIMAL(10,2) AS amount,
    CASE
        WHEN r_status < 0.70 THEN 'posted'
        WHEN r_status < 0.85 THEN 'pending'
        WHEN r_status < 0.95 THEN 'reversed'
        ELSE 'failed'
    END AS status,
    (ARRAY[
        'North America', 'Europe', 'Asia Pacific', 'Latin America',
        'Middle East', 'Africa', 'Oceania', 'South Asia'
    ])[1 + floor(random() * 8)::INT] AS region
FROM (
    SELECT random() AS r_status
    FROM generate_series(1, 200000)
) s;

-- Force activity and stats collection patterns before analysis
SELECT count(*) FROM transactions WHERE account_id = 100;
SELECT count(*) FROM transactions WHERE transaction_date > '2025-01-01';
SELECT count(*) FROM transactions WHERE merchant = 'Amazon';
ANALYZE transactions;

-- =========================================================
-- Problem 2: Table bloat via heavy deletes
-- =========================================================
CREATE TABLE logs (
    id SERIAL PRIMARY KEY,
    created_at TIMESTAMP NOT NULL,
    log_level VARCHAR(10) NOT NULL,
    service VARCHAR(50) NOT NULL,
    message TEXT NOT NULL
);

INSERT INTO logs (
    created_at,
    log_level,
    service,
    message
)
SELECT
    now() - (interval '180 days' * random()) AS created_at,
    (ARRAY['DEBUG', 'INFO', 'WARN', 'ERROR'])[1 + floor(random() * 4)::INT] AS log_level,
    (ARRAY['api', 'worker', 'auth', 'billing', 'search', 'notifier'])[1 + floor(random() * 6)::INT] AS service,
    format('Log event %s - %s', gs, md5((gs::text || random()::text)))
FROM generate_series(1, 100000) AS gs;

DELETE FROM logs WHERE id <= 80000;
ANALYZE logs;

-- =========================================================
-- Problem 3: Deliberately bad postgresql.conf runtime settings
-- =========================================================
ALTER SYSTEM SET shared_buffers = '32MB';        -- way too low (example target ~2GB on 8GB host)
ALTER SYSTEM SET work_mem = '1MB';               -- too low for complex sorts/joins
ALTER SYSTEM SET random_page_cost = '4.0';       -- too high for SSD (target ~1.1-1.5)
ALTER SYSTEM SET effective_cache_size = '128MB'; -- too low (target ~75% of RAM)
SELECT pg_reload_conf();

-- =========================================================
-- Problem 4: Idle transaction lock training setup
-- =========================================================
CREATE TABLE lock_test (
    id SERIAL PRIMARY KEY,
    resource_name VARCHAR(100) NOT NULL,
    status VARCHAR(20) NOT NULL,
    updated_at TIMESTAMP NOT NULL DEFAULT now()
);

INSERT INTO lock_test (resource_name, status)
VALUES
    ('resource_alpha', 'available'),
    ('resource_beta', 'available'),
    ('resource_gamma', 'available');

ANALYZE lock_test;

ANALYZE transactions;
ANALYZE logs;

/*
Idle transaction simulation instructions (external session required):
1) Open a separate psycopg2 session (not this script connection).
2) Run:
      BEGIN;
      UPDATE lock_test SET status = 'locked', updated_at = now() WHERE id = 1;
   Then keep the transaction open without COMMIT/ROLLBACK.
3) This creates a row lock and an "idle in transaction" backend.
4) The agent should find it in pg_stat_activity and terminate with pg_terminate_backend(pid).

Verification query example:
SELECT pid, usename, state, wait_event_type, wait_event, query
FROM pg_stat_activity
WHERE state = 'idle in transaction'
  AND query ILIKE '%lock_test%';
*/

-- ISSUE 1 - Missing indexes:
-- Check pg_stat_user_tables where relname='transactions' for high seq_scan activity.
-- VERIFICATION:
--   SELECT count(*) FROM pg_indexes
--   WHERE tablename='transactions' AND indexname <> 'transactions_pkey';
--   -- expected 0 before fixes, >0 after creating useful indexes
--
-- ISSUE 2 - Table bloat:
-- Check:
--   SELECT n_live_tup, n_dead_tup FROM pg_stat_user_tables WHERE relname='logs';
-- VERIFICATION:
--   n_dead_tup should drop near 0 after VACUUM (FULL for size reclaim),
--   and table size should decrease after VACUUM FULL.
--
-- ISSUE 3 - Bad config:
-- Check:
--   SELECT current_setting('shared_buffers'),
--          current_setting('work_mem'),
--          current_setting('random_page_cost'),
--          current_setting('effective_cache_size');
-- VERIFICATION:
--   shared_buffers >= '256MB',
--   work_mem >= '16MB',
--   random_page_cost <= '1.5'
--
-- ISSUE 4 - Idle transaction:
-- Check:
--   SELECT pid, state, query
--   FROM pg_stat_activity
--   WHERE state='idle in transaction' AND query ILIKE '%lock_test%';
-- VERIFICATION:
--   no rows should remain for lock_test after terminating backend.
