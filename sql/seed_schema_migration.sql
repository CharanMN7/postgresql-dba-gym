-- Task 2: Schema Migration
--
-- A denormalized user_orders table with 2000 rows / 200 distinct customers.
-- The agent's job is to normalize this into customers + orders tables with
-- proper constraints, then provide a backward-compatible view.

SET search_path TO task_schema, public;

CREATE TABLE IF NOT EXISTS user_orders (
    row_id           BIGSERIAL PRIMARY KEY,
    customer_name    TEXT        NOT NULL,
    customer_email   TEXT        NOT NULL,
    customer_address TEXT        NOT NULL,
    order_date       TIMESTAMPTZ NOT NULL,
    amount           NUMERIC(10, 2) NOT NULL,
    status           TEXT        NOT NULL
);

INSERT INTO user_orders
    (customer_name, customer_email, customer_address, order_date, amount, status)
SELECT
    'Customer ' || ((i / 10) + 1)                                AS customer_name,
    'customer' || ((i / 10) + 1) || '@example.com'               AS customer_email,
    ((i / 10) + 1) || ' Main St, Springfield'                    AS customer_address,
    (TIMESTAMPTZ '2024-01-01 00:00:00+00') + (i * INTERVAL '1 hour') AS order_date,
    (((i * 13) % 100000) / 100.0)::NUMERIC(10,2)                 AS amount,
    (ARRAY['pending','shipped','delivered'])[1 + (i % 3)]        AS status
FROM generate_series(0, 1999) AS gs(i);

ANALYZE user_orders;
