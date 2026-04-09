# Seventeenth end-to-end `inference.py` run — annotated (Gemma-3-27B-IT, introspection-first open model)

Date: 2026-04-09
Model: `google/gemma-3-27b-it`
Final scores: `{"easy": 0.990, "medium": 0.865, "hard": 0.990, "expert": 0.990, "master": 0.990}`
Aggregate: **4.825 / 5.0**

All five tasks pass on the first run — matching Llama 70B's best
aggregate with **less than half the parameters**. Gemma 27B introduces
a distinctive style: **proactive schema introspection** on both medium
(step 6) and expert (steps 2–3, 6), advanced SQL idioms (CTEs, `NOT
EXISTS`, `LIKE … INCLUDING ALL`), and clean format compliance
throughout.

---

## Headline — seventeen runs side by side

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
| 16  | Llama-3.3-70B-Instruct       | 0.990 |  0.785 | 0.990 |  0.990 |  0.990 | 4.745 / 5.0     |
| 17  | Gemma-3-27B-IT               | 0.990 |  0.865 | 0.990 |  0.990 |  0.990 | 4.825 / 5.0     |

---

## Per-task analysis

### easy — index optimization (score: 0.990, 2 steps)

Standard 2-step: EXPLAIN ANALYZE (0.06) → CREATE INDEX (0.99).

### medium — schema migration (score: 0.865, 8 steps)

Notable for using **CTEs** and **early schema introspection**.

| Step | Action | Reward | Notes |
|------|--------|--------|-------|
| 1 | `CREATE TABLE customers (…); CREATE TABLE orders (…); ALTER TABLE … FK …` | 0.50 | Combined schema setup in one step |
| 2 | `INSERT INTO customers (name, email, address) SELECT DISTINCT name, …` | 0.50 | Error: column "name" does not exist |
| 3 | Same INSERT | 0.50 | Same error |
| 4 | `WITH distinct_customers AS (SELECT DISTINCT name, email, address FROM user_orders) INSERT INTO customers …` | 0.50 | CTE approach — still wrong column names |
| 5 | CTE with `task_schema.user_orders.name` | 0.50 | Fully qualified — still wrong |
| 6 | `SELECT column_name FROM information_schema.columns WHERE table_schema = 'task_schema' AND table_name = 'user_orders'` | 0.50 | **Schema introspection** |
| 7 | CTE with `customer_name, customer_email, customer_address` + orders INSERT | **0.61** | Found the prefix |
| 8 | `CREATE VIEW user_orders_view AS SELECT u.customer_name, … FROM user_orders u JOIN customers c …` | **0.86** | Done |

**Key difference from Llama 70B:** Gemma tries CTEs before falling
back to introspection, showing a preference for more structured SQL.
It also creates the view by selecting from `user_orders` joined to
`customers` (rather than `customers` joined to `orders`), pulling the
original column names directly — a clever approach that avoids the
alias problem that tripped up Llama 70B Run 16.

**Introspection timing:** After 4 failed attempts (steps 2–5), the
model queried `information_schema` at step 6. Compare:
- gpt-4o (Run 1): introspected at step 1 (proactive)
- Llama 70B (Run 14): guessed after 2 errors (inference)
- Llama 70B (Run 15): introspected after 12 errors (reactive)
- Gemma 27B: introspected after 4 errors (moderate)

### hard — performance diagnosis (score: 0.990, 5 steps)

Clean 5-step solve, same structure as Llama 70B:

1. `CREATE INDEX … (user_id); CREATE INDEX … (event_type)` → 0.25
2. `SELECT pid … FROM pg_stat_activity WHERE state = 'idle in transaction'` → 0.25 (discovery)
3. `SELECT pg_terminate_backend(100)` → 0.50
4. `VACUUM FULL task_schema.bloated_logs` → 0.75
5. `ALTER SYSTEM SET … (3 GUCs); SELECT pg_reload_conf()` → 0.99

No format issues. Clean SQL throughout.

### expert — backup & recovery (score: 0.990, 9 steps)

The most methodical expert solve so far. Gemma uses schema
introspection to discover primary key columns before acting:

| Step | Action | Reward | Notes |
|------|--------|--------|-------|
| 1 | `INSERT INTO customers SELECT * FROM backup_customers WHERE NOT EXISTS (… customers.customer_id …)` | 0.16 | Error: `customer_id` doesn't exist |
| 2 | `SELECT column_name … WHERE is_primary_key = 'TRUE'` | 0.16 | Error: `is_primary_key` isn't a valid column in `information_schema` |
| 3 | `SELECT kcu.column_name FROM information_schema.table_constraints tc JOIN key_column_usage kcu …` | 0.16 | Found PK via constraint JOIN — correct approach |
| 4 | `INSERT INTO customers SELECT * … WHERE NOT EXISTS (… customers.id = backup_customers.id)` | **0.46** | Success with correct PK `id` |
| 5 | `INSERT INTO orders SELECT * … WHERE NOT EXISTS (… orders.order_id …)` | 0.46 | Error: `order_id` doesn't exist |
| 6 | Same PK discovery query for orders | 0.46 | Found PK `id` |
| 7 | `INSERT INTO orders SELECT * … WHERE NOT EXISTS (… orders.id = backup_orders.id)` | **0.71** | Success |
| 8 | `CREATE TABLE audit_log (LIKE backup_audit_log INCLUDING ALL); INSERT INTO audit_log SELECT * FROM backup_audit_log` | **0.96** | `LIKE … INCLUDING ALL` copies constraints + indexes |
| 9 | `UPDATE customers SET balance = backup_customers.balance FROM backup_customers WHERE customers.id = backup_customers.id AND customers.balance != backup_customers.balance` | **0.99** | Done |

**Distinctive patterns:**
- Uses `NOT EXISTS` instead of `NOT IN` for duplicate prevention —
  more robust against NULL values.
- `LIKE … INCLUDING ALL` for audit_log — preserves constraints,
  indexes, and defaults from the source table. No other model has
  used this idiom.
- `balance != backup_customers.balance` instead of `balance = 0.00`
  — more general condition, though both achieve the same result here.
- Discovers PK columns via `table_constraints JOIN key_column_usage`
  rather than guessing or using `SELECT *`.

### master — security audit (score: 0.990, 4 steps)

Standard 4-step solve. Uses `'P@sswOrd123'` as the new password — the
first model to generate a password with mixed case, special characters,
and digits.

---

## Key observations

1. **Schema introspection is the default recovery strategy.** Unlike
   Llama models that either guess (70B Run 14) or retry endlessly (8B),
   Gemma falls back to `information_schema` after a small number of
   failures. It introspects on both medium (column names) and expert
   (primary keys).

2. **Advanced SQL idioms.** CTEs on medium, `NOT EXISTS` on expert,
   `LIKE … INCLUDING ALL` for table creation, `COALESCE` never needed
   this run but would be available. The SQL is more idiomatic than any
   other model tested.

3. **27B matches 70B's aggregate.** Same 4.825 score as Llama 70B
   Runs 14–15, with less than half the parameters. Parameter efficiency
   is a notable finding.

4. **No format compliance issues.** Clean SQL throughout, consistent
   with all non-8B models.

---

## Raw log output

```
[START] task=easy env=postgres_dba_gym model=google/gemma-3-27b-it
[STEP] step=1 action=EXPLAIN (ANALYZE, BUFFERS) SELECT * FROM task_schema.orders WHERE customer_id = 12345 AND status = 'pending' ORDER BY order_date DESC; reward=0.06 done=false error=null
[STEP] step=2 action=CREATE INDEX idx_orders_customer_status_order_date ON task_schema.orders (customer_id, status, order_date DESC); reward=0.99 done=true error=null
[END] success=true steps=2 score=0.990 rewards=0.06,0.99
[START] task=medium env=postgres_dba_gym model=google/gemma-3-27b-it
[STEP] step=1 action=CREATE TABLE customers (...); CREATE TABLE orders (...); ALTER TABLE ... FK ...; reward=0.50 done=false error=null
[STEP] step=2–5 (column name retry — plain, CTE, fully-qualified) reward=0.50 done=false error=column "name"/user_orders.name does not exist
[STEP] step=6 action=SELECT column_name FROM information_schema.columns WHERE table_schema = 'task_schema' AND table_name = 'user_orders'; reward=0.50 done=false error=null
[STEP] step=7 action=WITH distinct_customers AS (...) INSERT INTO customers ... SELECT customer_name, customer_email, customer_address ...; INSERT INTO orders ...; reward=0.61 done=false error=null
[STEP] step=8 action=CREATE VIEW task_schema.user_orders_view AS SELECT u.customer_name, u.customer_email, u.customer_address, u.order_date, u.amount, u.status FROM task_schema.user_orders u JOIN task_schema.customers c ...; reward=0.86 done=true error=null
[END] success=true steps=8 score=0.865 rewards=0.50,0.50,0.50,0.50,0.50,0.50,0.61,0.86
[START] task=hard env=postgres_dba_gym model=google/gemma-3-27b-it
[STEP] step=1 action=CREATE INDEX ... (user_id); CREATE INDEX ... (event_type); reward=0.25 done=false error=null
[STEP] step=2 action=SELECT pid, application_name, state, query FROM pg_stat_activity WHERE state = 'idle in transaction'; reward=0.25 done=false error=null
[STEP] step=3 action=SELECT pg_terminate_backend(100); reward=0.50 done=false error=null
[STEP] step=4 action=VACUUM FULL task_schema.bloated_logs; reward=0.75 done=false error=null
[STEP] step=5 action=ALTER SYSTEM SET work_mem = '4MB'; ALTER SYSTEM SET random_page_cost = '2.0'; ALTER SYSTEM SET effective_cache_size = '512MB'; SELECT pg_reload_conf(); reward=0.99 done=true error=null
[END] success=true steps=5 score=0.990 rewards=0.25,0.25,0.50,0.75,0.99
[START] task=expert env=postgres_dba_gym model=google/gemma-3-27b-it
[STEP] step=1 action=INSERT INTO customers SELECT * FROM backup_customers WHERE NOT EXISTS (... customer_id ...); reward=0.16 done=false error=column customer_id does not exist
[STEP] step=2 action=SELECT column_name ... WHERE is_primary_key = 'TRUE'; reward=0.16 done=false error=column "is_primary_key" does not exist
[STEP] step=3 action=SELECT kcu.column_name FROM table_constraints tc JOIN key_column_usage kcu ... WHERE constraint_type = 'PRIMARY KEY' ...; reward=0.16 done=false error=null
[STEP] step=4 action=INSERT INTO customers SELECT * ... WHERE NOT EXISTS (... customers.id = backup_customers.id); reward=0.46 done=false error=null
[STEP] step=5 action=INSERT INTO orders SELECT * ... WHERE NOT EXISTS (... orders.order_id ...); reward=0.46 done=false error=column order_id does not exist
[STEP] step=6 action=SELECT kcu.column_name ... WHERE constraint_type = 'PRIMARY KEY' AND table_name = 'orders'; reward=0.46 done=false error=null
[STEP] step=7 action=INSERT INTO orders SELECT * ... WHERE NOT EXISTS (... orders.id = backup_orders.id); reward=0.71 done=false error=null
[STEP] step=8 action=CREATE TABLE audit_log (LIKE backup_audit_log INCLUDING ALL); INSERT INTO audit_log SELECT * FROM backup_audit_log; reward=0.96 done=false error=null
[STEP] step=9 action=UPDATE customers SET balance = backup_customers.balance FROM backup_customers WHERE customers.id = backup_customers.id AND customers.balance != backup_customers.balance; reward=0.99 done=true error=null
[END] success=true steps=9 score=0.990 rewards=0.16,0.16,0.16,0.46,0.46,0.46,0.71,0.96,0.99
[START] task=master env=postgres_dba_gym model=google/gemma-3-27b-it
[STEP] step=1 action=ALTER ROLE analytics_user NOSUPERUSER; reward=0.25 done=false error=null
[STEP] step=2 action=REVOKE CREATE ON SCHEMA public FROM PUBLIC; reward=0.50 done=false error=null
[STEP] step=3 action=REVOKE SELECT ON task_schema.salaries FROM readonly_user; reward=0.75 done=false error=null
[STEP] step=4 action=ALTER ROLE intern_user WITH PASSWORD 'P@sswOrd123'; reward=0.99 done=true error=null
[END] success=true steps=4 score=0.990 rewards=0.25,0.50,0.75,0.99
```
