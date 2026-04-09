-- Task 4: Backup & Recovery
--
-- A production database has suffered simulated data loss. Backup copies of
-- each affected table live inside task_schema (suffix ``backup_``). The agent
-- must restore the live tables from those backups and recreate a dropped
-- audit_log table.
--
-- The Python setup step that runs *after* this seed also:
--   * queries the backup_* tables to stash expected row counts on
--     ``env.state.task_data`` so the grader can compare live vs backup
--     without hand-computing cascade effects.

SET search_path TO task_schema, public;

-- ---------------------------------------------------------------------------
-- Live tables
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS customers (
    id                BIGSERIAL PRIMARY KEY,
    name              TEXT          NOT NULL,
    email             TEXT          NOT NULL,
    created_at        TIMESTAMPTZ   NOT NULL,
    subscription_tier TEXT          NOT NULL,
    balance           NUMERIC(10,2) NOT NULL
);

INSERT INTO customers (name, email, created_at, subscription_tier, balance)
SELECT
    'Customer ' || i                                                  AS name,
    'customer' || i || '@example.com'                                 AS email,
    (TIMESTAMPTZ '2024-01-01 00:00:00+00') + (i * INTERVAL '2 hours') AS created_at,
    (ARRAY['free','basic','pro','enterprise'])[1 + (i % 4)]           AS subscription_tier,
    (((i * 37) % 100000) / 100.0)::NUMERIC(10,2)                      AS balance
FROM generate_series(1, 500) AS gs(i);

CREATE TABLE IF NOT EXISTS orders (
    id          BIGSERIAL PRIMARY KEY,
    customer_id BIGINT        NOT NULL REFERENCES customers(id),
    order_date  TIMESTAMPTZ   NOT NULL,
    total       NUMERIC(10,2) NOT NULL,
    status      TEXT          NOT NULL
);

INSERT INTO orders (customer_id, order_date, total, status)
SELECT
    ((i * 2654435761) % 500) + 1                                         AS customer_id,
    (TIMESTAMPTZ '2024-01-01 00:00:00+00') + (i * INTERVAL '30 minutes') AS order_date,
    (((i * 17) % 50000) / 100.0)::NUMERIC(10,2)                          AS total,
    (ARRAY['pending','shipped','delivered','cancelled'])[1 + (i % 4)]    AS status
FROM generate_series(1, 2000) AS gs(i);

CREATE TABLE IF NOT EXISTS audit_log (
    id          BIGSERIAL PRIMARY KEY,
    event_type  TEXT        NOT NULL,
    table_name  TEXT        NOT NULL,
    record_id   BIGINT      NOT NULL,
    old_value   JSONB,
    new_value   JSONB,
    created_at  TIMESTAMPTZ NOT NULL
);

INSERT INTO audit_log (event_type, table_name, record_id, old_value, new_value, created_at)
SELECT
    (ARRAY['INSERT','UPDATE','DELETE'])[1 + (i % 3)]                 AS event_type,
    (ARRAY['customers','orders'])[1 + (i % 2)]                       AS table_name,
    ((i * 13) % 1000) + 1                                            AS record_id,
    jsonb_build_object('v', i)                                       AS old_value,
    jsonb_build_object('v', i + 1)                                   AS new_value,
    (TIMESTAMPTZ '2024-01-01 00:00:00+00') + (i * INTERVAL '1 hour') AS created_at
FROM generate_series(1, 1000) AS gs(i);

-- ---------------------------------------------------------------------------
-- Backup copies (stored inside task_schema so reset() cleans them up between
-- episodes — a top-level ``backup`` schema would leak across resets).
-- ---------------------------------------------------------------------------
CREATE TABLE backup_customers AS SELECT * FROM customers;
CREATE TABLE backup_orders    AS SELECT * FROM orders;
CREATE TABLE backup_audit_log AS SELECT * FROM audit_log;

-- ---------------------------------------------------------------------------
-- Simulate data loss
-- ---------------------------------------------------------------------------
-- Delete orders tied to customers we're about to delete, so the customer
-- delete below doesn't hit the FK RESTRICT. The Python setup will record the
-- post-corruption counts empirically so the grader doesn't depend on exact
-- math here.
DELETE FROM orders    WHERE customer_id > 400;        -- orders for soon-to-delete customers
DELETE FROM customers WHERE id > 400;                 -- 100 customers gone
DELETE FROM orders    WHERE id % 3 = 0;               -- ~1/3 of remaining orders gone
UPDATE customers SET balance = 0.00 WHERE id % 5 = 0; -- corrupt ~80 balances
DROP TABLE audit_log;                                 -- table accidentally dropped

ANALYZE customers;
ANALYZE orders;
ANALYZE backup_customers;
ANALYZE backup_orders;
ANALYZE backup_audit_log;
