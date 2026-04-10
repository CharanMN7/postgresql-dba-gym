-- seed_schema_migration.sql
-- Creates a deliberately denormalized user_orders table (2NF/3NF violations)
-- with duplicated customer attributes across order rows.

DROP TABLE IF EXISTS user_orders CASCADE;

CREATE TABLE user_orders (
    id SERIAL PRIMARY KEY,
    customer_name VARCHAR(100) NOT NULL,
    customer_email VARCHAR(150) NOT NULL,
    customer_address TEXT NOT NULL,
    customer_phone VARCHAR(20),
    customer_tier VARCHAR(20) NOT NULL,
    order_date TIMESTAMP NOT NULL,
    order_amount DECIMAL(10,2) NOT NULL,
    order_status VARCHAR(20) NOT NULL,
    product_name VARCHAR(100) NOT NULL,
    product_category VARCHAR(50) NOT NULL,
    quantity INTEGER NOT NULL
);

WITH customers AS (
    SELECT
        c.customer_id,
        format('Customer_%s', lpad(c.customer_id::text, 3, '0')) AS customer_name,
        format(
            'customer_%s@example.com',
            lpad(c.customer_id::text, 3, '0')
        ) AS customer_email,
        format(
            '%s %s St, District %s, Metro City %s',
            10 + (c.customer_id % 990),
            (ARRAY['Oak', 'Maple', 'Cedar', 'Pine', 'Elm', 'Willow', 'Birch', 'Lake'])[1 + (c.customer_id % 8)],
            1 + (c.customer_id % 25),
            1 + (c.customer_id % 40)
        ) AS customer_address,
        format(
            '+1-555-%s-%s',
            lpad((100 + (c.customer_id % 900))::text, 3, '0'),
            lpad((1000 + (c.customer_id % 9000))::text, 4, '0')
        ) AS customer_phone,
        CASE
            WHEN c.customer_id <= 250 THEN 'bronze'
            WHEN c.customer_id <= 375 THEN 'silver'
            WHEN c.customer_id <= 450 THEN 'gold'
            ELSE 'platinum'
        END AS customer_tier
    FROM generate_series(1, 500) AS c(customer_id)
)
INSERT INTO user_orders (
    customer_name,
    customer_email,
    customer_address,
    customer_phone,
    customer_tier,
    order_date,
    order_amount,
    order_status,
    product_name,
    product_category,
    quantity
)
SELECT
    c.customer_name,
    c.customer_email,
    c.customer_address,
    c.customer_phone,
    c.customer_tier,
    now() - (interval '730 days' * (1 - power(random(), 2.0))) AS order_date,
    LEAST(
        2499.99,
        GREATEST(
            5.99,
            round((exp(ln(5.99) + random() * (ln(2499.99) - ln(5.99))))::numeric, 2)
        )
    )::DECIMAL(10,2) AS order_amount,
    CASE
        WHEN r_status < 0.60 THEN 'completed'
        WHEN r_status < 0.75 THEN 'pending'
        WHEN r_status < 0.85 THEN 'shipped'
        WHEN r_status < 0.93 THEN 'cancelled'
        ELSE 'returned'
    END AS order_status,
    format(
        '%s Item %s',
        (ARRAY[
            'Electronics',
            'Clothing',
            'Home & Garden',
            'Books',
            'Sports',
            'Food & Beverage',
            'Beauty & Personal Care',
            'Toys & Games'
        ])[1 + floor(random() * 8)::INT],
        lpad((1 + floor(random() * 9999))::INT::text, 4, '0')
    ) AS product_name,
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
    (1 + floor(random() * 5))::INT AS quantity
FROM generate_series(1, 5000) AS g(order_no)
JOIN customers c
    ON c.customer_id = ((g.order_no - 1) % 500) + 1
CROSS JOIN LATERAL (
    SELECT random() AS r_status
) s;

ANALYZE user_orders;

-- EXPECTED RESULT:
-- customers(
--   id SERIAL PRIMARY KEY,
--   name VARCHAR(100) NOT NULL,
--   email VARCHAR(150) UNIQUE NOT NULL,
--   address TEXT NOT NULL,
--   phone VARCHAR(20),
--   tier VARCHAR(20) NOT NULL
-- )
-- orders(
--   id SERIAL PRIMARY KEY,
--   customer_id INTEGER NOT NULL REFERENCES customers(id),
--   order_date TIMESTAMP NOT NULL,
--   order_amount DECIMAL(10,2) NOT NULL,
--   order_status VARCHAR(20) NOT NULL,
--   product_name VARCHAR(100) NOT NULL,
--   product_category VARCHAR(50) NOT NULL,
--   quantity INTEGER NOT NULL
-- )
-- view: user_orders_view that JOINs both tables to reproduce original columns and row count
-- Data integrity: customers table should have exactly 500 rows, orders table should have exactly 5000 rows
