-- Task 1: Index Optimization
--
-- Creates a 120K-row orders table with deterministic content (no random()
-- so reseeds give reproducible plans). The table has no user indexes —
-- only the implicit primary key. We then force 250 deterministic 'pending'
-- rows for customer_id=12345 so the slow target query has predictable
-- selectivity.
--
-- Run inside a fresh task_schema (the env drops it on every reset).

SET search_path TO task_schema, public;

CREATE TABLE IF NOT EXISTS orders (
    id          BIGSERIAL PRIMARY KEY,
    customer_id INTEGER     NOT NULL,
    order_date  TIMESTAMPTZ NOT NULL,
    status      TEXT        NOT NULL,
    amount      NUMERIC(10, 2) NOT NULL,
    region      TEXT        NOT NULL
);

INSERT INTO orders (customer_id, order_date, status, amount, region)
SELECT
    ((i * 2654435761) % 50000) + 1                                       AS customer_id,
    NOW() - ((i % 8760) * INTERVAL '1 hour')                             AS order_date,
    (ARRAY['pending','shipped','delivered','cancelled'])[1 + (i % 4)]    AS status,
    (((i * 13) % 100000) / 100.0)::NUMERIC(10,2)                         AS amount,
    (ARRAY['us-east','us-west','eu','apac'])[1 + (i % 4)]                AS region
FROM generate_series(1, 120000) AS gs(i);

-- Force 250 deterministic 'pending' rows for customer_id=12345 so the
-- target query is non-trivial but predictable.
INSERT INTO orders (customer_id, order_date, status, amount, region)
SELECT
    12345,
    NOW() - (i * INTERVAL '1 hour'),
    'pending',
    50.00,
    'us-east'
FROM generate_series(1, 250) AS gs(i);

ANALYZE orders;
