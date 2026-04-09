# Fifteenth end-to-end `inference.py` run — annotated (Llama-3.3-70B-Instruct, schema introspection)

Date: 2026-04-09
Model: `meta-llama/Llama-3.3-70B-Instruct`
Final scores: `{"easy": 0.990, "medium": 0.865, "hard": 0.990, "expert": 0.990, "master": 0.990}`
Aggregate: **4.825 / 5.0**

Identical aggregate to Run 14 — all five tasks pass again. The new
finding is on medium: the model used **`information_schema.columns`
to discover column names** at step 13 after 12 failed attempts. This
is the first time a Llama model has performed schema introspection,
though it took significantly more attempts than Run 14's 2-step
inference. The rest of the tasks are solved identically.

---

## Headline — fifteen runs side by side

| Run | Model                        | easy  | medium | hard  | expert | master | agg             |
| --- | ---------------------------- | ----: | -----: | ----: | -----: | -----: | --------------: |
| 1   | gpt-4o                       | 1.000 |  0.865 | 1.000 |      — |      — | 2.865 / 3.0     |
| 2   | gpt-4o-mini                  | 1.000 |  1.000 | 0.917 |      — |      — | 2.917 / 3.0     |
| 3   | gpt-4o-mini                  | 1.000 |  0.920 | 0.917 |      — |      — | 2.837 / 3.0     |
| 4   | gpt-4o-mini                  | 1.000 |  0.920 | 1.000 |      — |      — | 2.920 / 3.0     |
| 5   | gpt-4o-mini                  | 1.000 |  1.000 | 1.000 |  0.960 |  1.000 | 4.960 / 5.0     |
| 6   | gpt-4o-mini                  | 1.000 |  0.920 | 1.000 |  0.960 |  1.000 | 4.880 / 5.0     |
| 7   | gpt-4o-mini                  | 1.000 |  1.000 | 1.000 |  1.000 |  1.000 | **5.000 / 5.0** |
| 8   | gpt-3.5-turbo                | 1.000 |  0.865 | 1.000 |  1.000 |  1.000 | 4.865 / 5.0     |
| 9   | gpt-3.5-turbo                | 1.000 |  0.500 | 1.000 |  0.960 |  1.000 | 4.460 / 5.0     |
| 10  | gpt-3.5-turbo                | 1.000 |  0.500 | 1.000 |  0.960 |  1.000 | 4.460 / 5.0     |
| 11  | Llama-3.1-8B-Instruct        | 0.990 |  0.550 | 0.010 |  0.990 |  0.990 | 3.530 / 5.0     |
| 12  | Llama-3.1-8B-Instruct        | 0.990 |  0.500 | 0.010 |  0.410 |  0.990 | 2.900 / 5.0     |
| 13  | Llama-3.1-8B-Instruct        | 0.990 |  0.438 | 0.010 |  0.990 |  0.990 | 3.418 / 5.0     |
| 14  | Llama-3.3-70B-Instruct       | 0.990 |  0.865 | 0.990 |  0.990 |  0.990 | 4.825 / 5.0     |
| 15  | Llama-3.3-70B-Instruct       | 0.990 |  0.865 | 0.990 |  0.990 |  0.990 | 4.825 / 5.0     |

---

## Per-task analysis

### easy — index optimization (score: 0.990, 1 step)

Identical to Run 14. Single-step composite index, no diagnostic.

### medium — schema migration (score: 0.865, 17 steps)

Same final score as Run 14, but a very different path to get there.

**Phase 1 (step 1): Efficient schema setup.**
Combined both CREATE TABLE and the FK constraint into one multi-statement
step, jumping straight to reward 0.50. Runs 14 needed 2 steps for this.

**Phase 2 (steps 2–12): Column-name retry loop — 11 attempts.**
The model tried many variations:
- Unqualified `name, email, address` (steps 2, 5, 7, 10)
- Alias-qualified `uo.name` (steps 4, 9, 12)
- Fully-qualified `user_orders.name` (steps 6, 8)
- `task_schema.user_orders.name` (step 8, 11)
- `ROW_NUMBER() OVER (ORDER BY name)` (step 3)

Notably more variations than Run 14 (which only tried 2 before guessing
`customer_name`), but still no `customer_` prefix hypothesis.

**Phase 3 (step 13): Schema introspection — the breakthrough.**
```
SELECT column_name FROM information_schema.columns
  WHERE table_name = 'user_orders' AND table_schema = 'task_schema';
```

This is the **first time a Llama model has queried the schema** to
discover column names. After 12 failed guesses, the model fell back to
the same discovery strategy that gpt-4o used proactively in Run 1.

**Phase 4 (steps 14–17): Data and view completion.**
- Step 14: `INSERT … SELECT DISTINCT customer_name, customer_email, customer_address` + orders INSERT → 0.79.
- Step 15: `CREATE VIEW … SELECT c.customer_name` → error (column doesn't exist in `customers`, it's `c.name`).
- Step 16: `CREATE VIEW … SELECT c.name AS customer_name` → error ("already exists" from step 15's partial creation that actually succeeded as raw SQL before the SELECT failed? No — step 15 fully failed).

  Actually: the view from step 15 was created with the wrong SELECT, but the CREATE VIEW itself didn't error — it errored because `c.customer_name` doesn't exist. But a prior `SELECT *` from the env check might have created a residual view. In any case:

- Step 16: Same CREATE VIEW → "already exists" error.
- Step 17: `DROP VIEW …; CREATE VIEW …` → 0.86, done.

**Two paths to the same score:** Run 14 guessed the column prefix
after 2 errors (inference). Run 15 queried the schema after 12 errors
(introspection). Both reached 0.865. The inference path is clearly
more efficient (7 vs 17 steps), but introspection is a more robust
strategy.

### hard — performance diagnosis (score: 0.990, 6 steps)

One extra step vs Run 14 because discovery was split across two steps:

1. `SELECT * FROM pg_indexes …` → 0.01 (index discovery only)
2. `CREATE INDEX … (user_id); CREATE INDEX … (event_type)` → 0.25
3. `SELECT pid, application_name, state, query FROM pg_stat_activity WHERE state = 'idle in transaction'` → 0.25 (blocker discovery)
4. `SELECT pg_terminate_backend(145)` → 0.50 (targeted kill)
5. `ALTER SYSTEM SET … (3 GUCs); SELECT pg_reload_conf()` → 0.75
6. `VACUUM FULL task_schema.bloated_logs` → 0.99

Run 14 packed all discovery into step 1 (4 queries); this run split it
into steps 1 and 3. Same strategy, slightly less compressed.

### expert — backup & recovery (score: 0.990, 4 steps)

Identical to Run 14. Same 4-step `SELECT *` pattern.

### master — security audit (score: 0.990, 4 steps)

Individual statements this time (not combined like Run 14's 1-step):
1. `ALTER ROLE analytics_user NOSUPERUSER` → 0.25
2. `REVOKE CREATE ON SCHEMA public FROM PUBLIC` → 0.50
3. `REVOKE SELECT ON task_schema.salaries FROM readonly_user` → 0.75
4. `ALTER ROLE intern_user WITH PASSWORD 'intern_password'` → 0.99

---

## Key observations

1. **Schema introspection is in the model's capability set, but not
   its default strategy.** The 70B model CAN query
   `information_schema.columns` (step 13) but doesn't do it
   proactively — it only falls back to it after 12 failed guesses.
   In contrast, gpt-4o queried the schema as its very first action.

2. **Two medium recovery strategies.** Run 14: pattern inference
   (2 errors → guess prefix). Run 15: schema introspection (12 errors
   → query schema). Both succeed; inference is faster but stochastic.

3. **Reproducible aggregate.** Runs 14 and 15 both score 4.825 despite
   different medium step counts (7 vs 17) and different hard step
   counts (5 vs 6). The final scores are identical.

4. **Still no format issues.** Raw SQL throughout, consistent with
   Run 14.

---

## Raw log output

```
[START] task=easy env=postgres_dba_gym model=meta-llama/Llama-3.3-70B-Instruct
[STEP] step=1 action=CREATE INDEX idx_orders_customer_id_status_order_date ON task_schema.orders (customer_id, status, order_date DESC); reward=0.99 done=true error=null
[END] success=true steps=1 score=0.990 rewards=0.99
[START] task=medium env=postgres_dba_gym model=meta-llama/Llama-3.3-70B-Instruct
[STEP] step=1 action=CREATE TABLE customers (...); CREATE TABLE orders (...); ALTER TABLE ... ADD CONSTRAINT FK ...; reward=0.50 done=false error=null
[STEP] step=2–12 (column name retry loop — 11 attempts with name/uo.name/user_orders.name variants) reward=0.50 done=false error=column "name"/uo.name/user_orders.name does not exist
[STEP] step=13 action=SELECT column_name FROM information_schema.columns WHERE table_name = 'user_orders' AND table_schema = 'task_schema'; reward=0.50 done=false error=null
[STEP] step=14 action=INSERT INTO customers (name, email, address) SELECT DISTINCT customer_name, customer_email, customer_address FROM task_schema.user_orders; INSERT INTO orders ...; reward=0.79 done=false error=null
[STEP] step=15 action=CREATE VIEW user_orders_view AS SELECT c.customer_name, ...; reward=0.79 done=false error=column c.customer_name does not exist
[STEP] step=16 action=CREATE VIEW ... SELECT c.name AS customer_name, ...; reward=0.79 done=false error=relation "user_orders_view" already exists
[STEP] step=17 action=DROP VIEW user_orders_view; CREATE VIEW ... SELECT c.name AS customer_name, ...; reward=0.86 done=true error=null
[END] success=true steps=17 score=0.865 rewards=0.50,0.50,0.50,0.50,0.50,0.50,0.50,0.50,0.50,0.50,0.50,0.50,0.50,0.79,0.79,0.79,0.86
[START] task=hard env=postgres_dba_gym model=meta-llama/Llama-3.3-70B-Instruct
[STEP] step=1 action=SELECT * FROM pg_indexes WHERE schemaname='task_schema' reward=0.01 done=false error=null
[STEP] step=2 action=CREATE INDEX ... (user_id); CREATE INDEX ... (event_type) reward=0.25 done=false error=null
[STEP] step=3 action=SELECT pid, application_name, state, query FROM pg_stat_activity WHERE state = 'idle in transaction' reward=0.25 done=false error=null
[STEP] step=4 action=SELECT pg_terminate_backend(145) reward=0.50 done=false error=null
[STEP] step=5 action=ALTER SYSTEM SET work_mem = '4MB'; ALTER SYSTEM SET random_page_cost = '1.0'; ALTER SYSTEM SET effective_cache_size = '512MB'; SELECT pg_reload_conf() reward=0.75 done=false error=null
[STEP] step=6 action=VACUUM FULL task_schema.bloated_logs reward=0.99 done=true error=null
[END] success=true steps=6 score=0.990 rewards=0.01,0.25,0.25,0.50,0.75,0.99
[START] task=expert env=postgres_dba_gym model=meta-llama/Llama-3.3-70B-Instruct
[STEP] step=1 action=INSERT INTO customers (SELECT * FROM backup_customers WHERE id NOT IN (SELECT id FROM customers)) reward=0.46 done=false error=null
[STEP] step=2 action=INSERT INTO orders (SELECT * FROM backup_orders WHERE id NOT IN (SELECT id FROM orders)) reward=0.71 done=false error=null
[STEP] step=3 action=CREATE TABLE audit_log AS SELECT * FROM backup_audit_log WITH NO DATA; INSERT INTO audit_log SELECT * FROM backup_audit_log reward=0.96 done=false error=null
[STEP] step=4 action=UPDATE customers SET balance = backup_customers.balance FROM backup_customers WHERE customers.id = backup_customers.id AND customers.balance = 0.00 reward=0.99 done=true error=null
[END] success=true steps=4 score=0.990 rewards=0.46,0.71,0.96,0.99
[START] task=master env=postgres_dba_gym model=meta-llama/Llama-3.3-70B-Instruct
[STEP] step=1 action=ALTER ROLE analytics_user NOSUPERUSER; reward=0.25 done=false error=null
[STEP] step=2 action=REVOKE CREATE ON SCHEMA public FROM PUBLIC; reward=0.50 done=false error=null
[STEP] step=3 action=REVOKE SELECT ON task_schema.salaries FROM readonly_user; reward=0.75 done=false error=null
[STEP] step=4 action=ALTER ROLE intern_user WITH PASSWORD 'intern_password'; reward=0.99 done=true error=null
[END] success=true steps=4 score=0.990 rewards=0.25,0.50,0.75,0.99
```
