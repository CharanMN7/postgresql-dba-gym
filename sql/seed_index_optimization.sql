-- seed_index_optimization.sql
-- Creates an orders table with 100,000 rows and no secondary indexes
-- to provide a baseline for index optimization training.

DROP TABLE IF EXISTS orders CASCADE;

CREATE TABLE orders (
    id SERIAL PRIMARY KEY,
    customer_id INTEGER NOT NULL,
    order_date TIMESTAMP NOT NULL,
    status VARCHAR(20) NOT NULL,
    amount DECIMAL(10,2) NOT NULL,
    region VARCHAR(50) NOT NULL,
    product_category VARCHAR(50) NOT NULL,
    shipping_method VARCHAR(30) NOT NULL
);

INSERT INTO orders (
    customer_id,
    order_date,
    status,
    amount,
    region,
    product_category,
    shipping_method
)
SELECT
    (1 + floor(random() * 5000))::INTEGER AS customer_id,
    now() - (
        interval '730 days'
        * (1 - power(random(), 2.2))
    ) AS order_date,
    CASE
        WHEN r_status < 0.60 THEN 'completed'
        WHEN r_status < 0.75 THEN 'pending'
        WHEN r_status < 0.85 THEN 'shipped'
        WHEN r_status < 0.93 THEN 'cancelled'
        ELSE 'returned'
    END AS status,
    LEAST(
        2499.99,
        GREATEST(
            5.99,
            round((exp(ln(5.99) + random() * (ln(2499.99) - ln(5.99))))::numeric, 2)
        )
    )::DECIMAL(10,2) AS amount,
    (ARRAY[
        'North America',
        'Europe',
        'Asia Pacific',
        'Latin America',
        'Middle East',
        'Africa',
        'Oceania',
        'South Asia'
    ])[1 + floor(random() * 8)::INT] AS region,
    (ARRAY[
        'Electronics',
        'Clothing',
        'Home & Garden',
        'Books',
        'Sports',
        'Food & Beverage',
        'Beauty & Personal Care',
        'Toys & Games'
    ])[1 + floor(random() * 8)::INT] AS product_category,
    (ARRAY[
        'Standard',
        'Express',
        'Overnight',
        'Economy'
    ])[1 + floor(random() * 4)::INT] AS shipping_method
FROM (
    SELECT
        random() AS r_status
    FROM generate_series(1, 100000)
) s;

ANALYZE orders;

/*
Target query for optimization training:
SELECT *
FROM orders
WHERE customer_id = 1234
  AND status = 'completed'
  AND order_date >= now() - interval '90 days'
ORDER BY order_date DESC
LIMIT 100;

Optimal index:
CREATE INDEX idx_orders_customer_status_date
    ON orders(customer_id, status, order_date DESC);

Expected behavior:
Sequential scan -> index scan (or bitmap index path), target speedup 10x+.
*/
