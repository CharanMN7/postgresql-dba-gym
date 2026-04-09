# Seventh end-to-end `inference.py` run — annotated (gpt-4o-mini, first perfect 5/5)

Date: 2026-04-09
Model: `gpt-4o-mini`
Final scores: `{"easy": 1.0, "medium": 1.0, "hard": 1.0, "expert": 1.0, "master": 1.0}`
Aggregate: **5.000 / 5.0**

First perfect score across all five tasks. The code changes since
run 6 were purely defensive (Docker fallback in `_open_env`,
`LOCAL_IMAGE_NAME` / `API_KEY` env var aliases, catch-all exception
handling in `main()`). None affect grading or model behavior.

---

## Headline — seven runs side by side

| Task           | Run 1 (4o)        | Run 2 (mini)      | Run 3 (mini)      | Run 4 (mini)       | Run 5 (mini)        | Run 6 (mini)        | **Run 7 (mini)**       |
|----------------|------------------:|------------------:|------------------:|-------------------:|--------------------:|--------------------:|-----------------------:|
| easy           | 1.000 / 2 steps   | 1.000 / 2 steps   | 1.000 / 2 steps   | 1.000 / 1 step     | 1.000 / 2 steps     | 1.000 / 2 steps     | **1.000 / 2 steps**    |
| medium         | 0.865 / 7 steps   | 1.000 / 8 steps   | 0.920 / 6 steps   | 0.920 / 6 steps    | 1.000 / 8 steps     | 0.920 / 6 steps     | **1.000 / 8 steps**    |
| hard           | 1.000 / 10 steps  | 0.917 / 8 steps   | 0.917 / 8 steps   | 1.000 / 9 steps    | 1.000 / 8 steps     | 1.000 / 9 steps     | **1.000 / 8 steps**    |
| expert         | —                 | —                 | —                 | —                  | 0.960 / 3 steps     | 0.960 / 3 steps     | **1.000 / 4 steps**    |
| master         | —                 | —                 | —                 | —                  | 1.000 / 4 steps     | 1.000 / 4 steps     | **1.000 / 4 steps**    |
| total (orig 3) | 2.865             | 2.917             | 2.837             | 2.920              | 3.000               | 2.920               | **3.000**              |
| total (all 5)  | —                 | —                 | —                 | —                  | 4.960               | 4.880               | **5.000**              |

The 0.04 improvement over run 5 comes entirely from expert (1.0 vs
0.96). Everything else is identical to the best prior result for
each task.

---

## Code changes since run 6

Defensive hardening of `inference.py` for the Phase 2 evaluator:

1. **Docker fallback.** `_open_env()` wraps `from_docker_image()` in
   `try/except` and falls back to `ENV_URL` when Docker is
   unavailable — the root cause of the Phase 2 failure on submission
   #3.

2. **Env var aliases.** `LOCAL_IMAGE_NAME` accepted alongside
   `IMAGE_NAME`; `API_KEY` accepted alongside `HF_TOKEN`. Both
   mentioned in the hackathon sample script.

3. **Exception safety.** `main()` catches all exceptions and prints
   `[ERROR]` instead of crashing with an unhandled traceback.
   Top-level `asyncio.run()` is also wrapped. The missing-token check
   now prints + returns 1 instead of raising `ValueError`.

None of these changes affect grading, model behavior, or the
environment server.

---

## Per-task analysis

### easy — Index Optimization (1.000, 2 steps)

Identical to runs 5–6. The model runs EXPLAIN ANALYZE, sees the seq
scan, creates the three-column composite index on
`(customer_id, status, order_date DESC)`, and gets full credit.

### medium — Schema Migration (1.000, 8 steps)

Same path as run 5: creates customers/orders tables, hits the
column-name ambiguity error, inspects the source table, inserts with
correct column names, joins for orders, creates the view. Picks
`TIMESTAMP` for `order_date` (the winning choice).

### hard — Performance Diagnosis (1.000, 8 steps)

Textbook execution: terminate blocker → index user_id → index
event_type → VACUUM FULL → tune three GUCs. Same 8-step path as
runs 5–6.

### expert — Backup & Recovery (1.000, 4 steps)

The breakthrough vs runs 5–6 (0.96). The model:

1. `INSERT INTO customers SELECT * FROM backup_customers WHERE id NOT IN (...)` — restores missing customers (0.46)
2. `INSERT INTO orders SELECT * FROM backup_orders WHERE id NOT IN (...)` — restores missing orders (0.71)
3. `CREATE TABLE audit_log AS SELECT * FROM backup_audit_log` — recreates the dropped table (0.96)
4. `UPDATE customers SET balance = backup.balance FROM backup_customers AS backup WHERE customers.id = backup.id AND backup.balance IS NOT NULL AND customers.balance != backup.balance` — repairs corrupted balances (1.00)

The key difference: step 4 adds `AND customers.balance != backup.balance`
which correctly targets only corrupted rows. In runs 5–6 the model
either skipped this step or the threshold-triggered `done=true`
prevented it from executing. This time the balance repair pushes
the score from 0.96 to 1.0 before the threshold fires.

### master — Security Audit (1.000, 4 steps)

Identical to runs 5–6. Four surgical fixes in four steps:
NOSUPERUSER → REVOKE CREATE → REVOKE SELECT → SET PASSWORD.

---

## Raw log

```
[START] task=easy env=postgres_dba_gym model=gpt-4o-mini
[STEP] step=1 action=EXPLAIN (ANALYZE, BUFFERS) SELECT * FROM task_schema.orders WHERE customer_id = 12345 AND status = 'pending' ORDER BY order_date DESC; reward=0.08 done=false error=null
[STEP] step=2 action=CREATE INDEX idx_customer_status_orderdate ON task_schema.orders (customer_id, status, order_date DESC); reward=1.00 done=true error=null
[END] success=true steps=2 score=1.000 rewards=0.08,1.00
[START] task=medium env=postgres_dba_gym model=gpt-4o-mini
[STEP] step=1 action=CREATE TABLE task_schema.customers (id SERIAL PRIMARY KEY, name VARCHAR NOT NULL, email VARCHAR UNIQUE NOT NULL, address VARCHAR); reward=0.31 done=false error=null
[STEP] step=2 action=CREATE TABLE task_schema.orders (id SERIAL PRIMARY KEY, customer_id INT REFERENCES task_schema.customers(id), order_date TIMESTAMP, amount DECIMAL, status VARCHAR); reward=0.50 done=false error=null
[STEP] step=3 action=INSERT INTO task_schema.customers (name, email, address) SELECT DISTINCT name, email, address FROM task_schema.user_orders; reward=0.50 done=false error=column "name" does not exist...
[STEP] step=4 action=INSERT INTO task_schema.customers (name, email, address) SELECT DISTINCT user_name, user_email, user_address FROM task_schema.user_orders; reward=0.50 done=false error=column "user_name" does not exist...
[STEP] step=5 action=SELECT * FROM task_schema.user_orders LIMIT 1; reward=0.50 done=false error=null
[STEP] step=6 action=INSERT INTO task_schema.customers (name, email, address) SELECT DISTINCT customer_name, customer_email, customer_address FROM task_schema.user_orders; reward=0.50 done=false error=null
[STEP] step=7 action=INSERT INTO task_schema.orders (customer_id, order_date, amount, status) SELECT c.id, u.order_date, u.amount, u.status FROM task_schema.user_orders u JOIN task_schema.customers c ON u.customer_emai... reward=0.75 done=false error=null
[STEP] step=8 action=CREATE VIEW task_schema.user_orders_view AS SELECT c.name AS customer_name, c.email AS customer_email, c.address AS customer_address, o.order_date, o.amount, o.status FROM task_schema.customers c J... reward=1.00 done=true error=null
[END] success=true steps=8 score=1.000 rewards=0.31,0.50,0.50,0.50,0.50,0.50,0.75,1.00
[START] task=hard env=postgres_dba_gym model=gpt-4o-mini
[STEP] step=1 action=SELECT * FROM pg_stat_activity WHERE state = 'idle in transaction'; reward=0.00 done=false error=null
[STEP] step=2 action=SELECT pg_terminate_backend(301); reward=0.25 done=false error=null
[STEP] step=3 action=CREATE INDEX idx_events_user_id ON task_schema.events (user_id); reward=0.38 done=false error=null
[STEP] step=4 action=CREATE INDEX idx_events_event_type ON task_schema.events (event_type); reward=0.50 done=false error=null
[STEP] step=5 action=VACUUM FULL task_schema.bloated_logs; reward=0.75 done=false error=null
[STEP] step=6 action=ALTER SYSTEM SET work_mem = '4MB'; SELECT pg_reload_conf(); reward=0.83 done=false error=null
[STEP] step=7 action=ALTER SYSTEM SET random_page_cost = '2.0'; SELECT pg_reload_conf(); reward=0.92 done=false error=null
[STEP] step=8 action=ALTER SYSTEM SET effective_cache_size = '512MB'; SELECT pg_reload_conf(); reward=1.00 done=true error=null
[END] success=true steps=8 score=1.000 rewards=0.00,0.25,0.38,0.50,0.75,0.83,0.92,1.00
[START] task=expert env=postgres_dba_gym model=gpt-4o-mini
[STEP] step=1 action=INSERT INTO task_schema.customers SELECT * FROM task_schema.backup_customers WHERE id NOT IN (SELECT id FROM task_schema.customers); reward=0.46 done=false error=null
[STEP] step=2 action=INSERT INTO task_schema.orders SELECT * FROM task_schema.backup_orders WHERE id NOT IN (SELECT id FROM task_schema.orders); reward=0.71 done=false error=null
[STEP] step=3 action=CREATE TABLE task_schema.audit_log AS SELECT * FROM task_schema.backup_audit_log; reward=0.96 done=false error=null
[STEP] step=4 action=UPDATE task_schema.customers SET balance = backup.balance FROM task_schema.backup_customers AS backup WHERE task_schema.customers.id = backup.id AND backup.balance IS NOT NULL AND task_schema.custo... reward=1.00 done=true error=null
[END] success=true steps=4 score=1.000 rewards=0.46,0.71,0.96,1.00
[START] task=master env=postgres_dba_gym model=gpt-4o-mini
[STEP] step=1 action=ALTER ROLE analytics_user NOSUPERUSER; reward=0.25 done=false error=null
[STEP] step=2 action=REVOKE CREATE ON SCHEMA public FROM PUBLIC; reward=0.50 done=false error=null
[STEP] step=3 action=REVOKE SELECT ON task_schema.salaries FROM readonly_user; reward=0.75 done=false error=null
[STEP] step=4 action=ALTER ROLE intern_user WITH PASSWORD 'secure_password_123'; reward=1.00 done=true error=null
[END] success=true steps=4 score=1.000 rewards=0.25,0.50,0.75,1.00
```
