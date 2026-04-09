# Eighteenth end-to-end `inference.py` run — annotated (Gemma-3-27B-IT, expert column-name struggles)

Date: 2026-04-09
Model: `google/gemma-3-27b-it`
Final scores: `{"easy": 0.990, "medium": 0.865, "hard": 0.990, "expert": 0.960, "master": 0.990}`
Aggregate: **4.795 / 5.0**

All five tasks pass, but expert drops from 0.990 to 0.960. The model
introspected the schema on expert (step 2) but then **ignored the
results**, repeating a `customer_id` column reference that the schema
query should have corrected. It also struggled with orders column
names despite having introspected. The medium and hard tasks are solved
identically to Run 17.

---

## Headline — eighteen runs side by side

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
| 18  | Gemma-3-27B-IT               | 0.990 |  0.865 | 0.990 |  0.960 |  0.990 | 4.795 / 5.0     |

---

## Per-task analysis

### easy — index optimization (score: 0.990, 1 step)

Single-step solve — no diagnostic, straight to the composite index.

### medium — schema migration (score: 0.865, 8 steps)

Same step count and final score as Run 17, but different intermediate
path:

- Step 1: Combined schema setup → 0.50
- Steps 2–3: `name` column errors (same as Run 17)
- Step 4: CTE using `customer_mapping` from `customers` table joined
  on `u.name` → error `u.name does not exist`. A creative but
  incorrect approach — tried to use already-populated customer data
  that doesn't exist yet.
- Step 5: `SELECT * FROM information_schema.columns WHERE … 'user_orders'`
  → schema introspection (1 step earlier than Run 17)
- Step 6: CTE referencing `customer_name` from `customers` table →
  error: `customer_name` doesn't exist in `customers` (it's `name`).
  The model confused source vs target column names after introspection.
- Step 7: `INSERT … SELECT DISTINCT customer_name, … FROM user_orders
  ON CONFLICT (email) DO NOTHING` → 0.61. Uses `ON CONFLICT` for
  idempotent inserts — first time any model has used this idiom on
  medium.
- Step 8: `CREATE VIEW … SELECT c.id AS id, c.name AS customer_name,
  c.email AS customer_email, c.address AS customer_address, …` → 0.86.

### hard — performance diagnosis (score: 0.990, 5 steps)

Identical to Run 17. Same 5-step pattern.

### expert — backup & recovery (score: 0.960, 14 steps)

The most step-intensive expert solve across all runs. The model
introspected heavily but struggled to apply the results:

| Step | Action | Reward | Notes |
|------|--------|--------|-------|
| 1 | `INSERT … WHERE NOT EXISTS (… customers.customer_id …)` | 0.16 | Error: `customer_id` doesn't exist |
| 2 | `SELECT * FROM information_schema.columns WHERE table_name='customers'` | 0.16 | **Introspection** — but then: |
| 3 | `INSERT … WHERE NOT EXISTS (… customers.customer_id …)` | 0.16 | **Repeated the same error!** Ignored schema results |
| 4 | `INSERT INTO customers (customer_id, first_name, last_name, email, balance)` | 0.16 | **Hallucinated columns**: `first_name`, `last_name` don't exist |
| 5 | `SELECT * FROM customers LIMIT 5` | 0.16 | Data sampling — finally sees actual column names |
| 6 | `INSERT INTO customers (id, name, email, created_at, subscription_tier, balance) SELECT …` | **0.46** | Correct columns at last |
| 7 | `INSERT INTO orders … WHERE orders.order_id …` | 0.46 | Error: `order_id` doesn't exist |
| 8 | `SELECT * FROM information_schema.columns WHERE table_name='orders'` | 0.46 | Introspection for orders |
| 9 | `INSERT INTO orders (order_id, customer_id, order_date, total_amount)` | 0.46 | **Hallucinated again**: `order_id`, `total_amount` |
| 10 | `SELECT * FROM orders LIMIT 5` | 0.46 | Data sampling — sees actual columns |
| 11 | `INSERT INTO orders (id, customer_id, order_date, total) SELECT …` | 0.46 | NOT NULL violation on `status` |
| 12 | `INSERT INTO orders (id, …, total, status) SELECT …, COALESCE(status, 'pending')` | **0.71** | `COALESCE` handles null status |
| 13 | `CREATE TABLE audit_log AS SELECT * FROM backup_audit_log` | **0.96** | |
| 14 | `UPDATE customers SET balance … WHERE customers.customer_id …` | 0.96 | Error: `customer_id` again — but **done=true** |

**Why 0.960 not 0.990:** The final UPDATE (step 14) used
`customers.customer_id` which errors, but the model had already
signaled `done=true`. The `done=true` ended the episode at reward
0.96 — the balance repair never executed. If the model had used
`customers.id`, it would have scored 0.99.

**Pattern: introspects but doesn't integrate.** Steps 2 and 8 query
`information_schema`, but steps 3, 4, and 9 still use wrong column
names. The model queries the schema, receives the column list, but
then generates SQL from its prior assumptions rather than the
introspection results. Data sampling (`SELECT * … LIMIT 5`) at steps
5 and 10 is what actually corrects the model — seeing the data is
more effective than seeing metadata.

**The `COALESCE` pattern (step 12)** is notable. The `backup_orders`
table has NULLs in the `status` column, which violates the NOT NULL
constraint on `orders.status`. Instead of doing `SELECT *` (which
would include the NULL), the model explicitly lists columns and
wraps `status` in `COALESCE(status, 'pending')`. This is the most
defensive data migration pattern seen across all models.

### master — security audit (score: 0.990, 4 steps)

Standard 4-step solve. Same `P@sswOrd123` password as Run 17.

---

## Key observations

1. **Introspection ≠ integration.** Gemma queries the schema but
   sometimes ignores the results, hallucinating column names like
   `first_name`, `last_name`, `total_amount` that don't exist. Data
   sampling (`SELECT * LIMIT 5`) is more effective at correcting the
   model's assumptions.

2. **`COALESCE` for NOT NULL constraints** is a genuinely useful
   pattern. No other model has handled the null-status-in-backup
   problem this cleanly.

3. **0.960 vs 0.990 on expert is a `customer_id` vs `id` mistake.**
   The model "knows" the column is `id` (it used it correctly at
   steps 4–7) but reverts to `customer_id` at step 14. This
   inconsistency within the same episode suggests the model's
   working memory doesn't fully retain corrections over 14 steps.

4. **Medium is rock-solid at 0.865.** Two runs, identical score,
   same basic path (introspect → insert → view).

---

## Raw log output

```
[START] task=easy env=postgres_dba_gym model=google/gemma-3-27b-it
[STEP] step=1 action=CREATE INDEX idx_orders_customer_status_orderdate ON task_schema.orders (customer_id, status, order_date DESC); reward=0.99 done=true error=null
[END] success=true steps=1 score=0.990 rewards=0.99
[START] task=medium env=postgres_dba_gym model=google/gemma-3-27b-it
[STEP] step=1 action=CREATE TABLE customers (...); CREATE TABLE orders (...); ALTER TABLE ... FK ...; reward=0.50 done=false error=null
[STEP] step=2–3 (column name errors) reward=0.50 error=column "name" does not exist
[STEP] step=4 action=WITH customer_mapping AS (...) INSERT INTO orders ... JOIN ... ON u.name = cm.name; reward=0.50 error=column u.name does not exist
[STEP] step=5 action=SELECT * FROM information_schema.columns WHERE ... 'user_orders'; reward=0.50 error=null
[STEP] step=6 action=WITH ... SELECT customer_name FROM customers ... reward=0.50 error=column "customer_name" does not exist (in customers table)
[STEP] step=7 action=INSERT INTO customers ... SELECT customer_name, customer_email, customer_address FROM user_orders ON CONFLICT (email) DO NOTHING; INSERT INTO orders ...; reward=0.61 error=null
[STEP] step=8 action=CREATE VIEW ... SELECT c.id AS id, c.name AS customer_name, c.email AS customer_email, ...; reward=0.86 done=true error=null
[END] success=true steps=8 score=0.865 rewards=0.50,0.50,0.50,0.50,0.50,0.50,0.61,0.86
[START] task=hard env=postgres_dba_gym model=google/gemma-3-27b-it
[STEP] step=1–5 (same 5-step solve as Run 17)
[END] success=true steps=5 score=0.990 rewards=0.25,0.25,0.50,0.75,0.99
[START] task=expert env=postgres_dba_gym model=google/gemma-3-27b-it
[STEP] step=1 action=INSERT INTO customers ... WHERE NOT EXISTS (... customer_id ...); reward=0.16 error=customer_id does not exist
[STEP] step=2 action=SELECT * FROM information_schema.columns WHERE table_name='customers'; reward=0.16 error=null
[STEP] step=3 action=INSERT INTO customers ... WHERE NOT EXISTS (... customer_id ...); reward=0.16 error=customer_id does not exist (REPEATED)
[STEP] step=4 action=INSERT INTO customers (customer_id, first_name, last_name, email, balance) ...; reward=0.16 error=column "customer_id" does not exist
[STEP] step=5 action=SELECT * FROM customers LIMIT 5; reward=0.16 error=null
[STEP] step=6 action=INSERT INTO customers (id, name, email, created_at, subscription_tier, balance) ...; reward=0.46 error=null
[STEP] step=7 action=INSERT INTO orders ... WHERE orders.order_id ...; reward=0.46 error=column order_id does not exist
[STEP] step=8 action=SELECT * FROM information_schema.columns WHERE table_name='orders'; reward=0.46 error=null
[STEP] step=9 action=INSERT INTO orders (order_id, customer_id, order_date, total_amount) ...; reward=0.46 error=column "order_id" does not exist
[STEP] step=10 action=SELECT * FROM orders LIMIT 5; reward=0.46 error=null
[STEP] step=11 action=INSERT INTO orders (id, customer_id, order_date, total) ...; reward=0.46 error=NOT NULL on status
[STEP] step=12 action=INSERT INTO orders (id, ..., total, status) SELECT ..., COALESCE(status, 'pending') ...; reward=0.71 error=null
[STEP] step=13 action=CREATE TABLE audit_log AS SELECT * FROM backup_audit_log; reward=0.96 error=null
[STEP] step=14 action=UPDATE customers SET balance ... WHERE customers.customer_id ...; reward=0.96 done=true error=customer_id does not exist
[END] success=true steps=14 score=0.960 rewards=0.16,0.16,0.16,0.16,0.16,0.46,0.46,0.46,0.46,0.46,0.46,0.71,0.96,0.96
[START] task=master env=postgres_dba_gym model=google/gemma-3-27b-it
[STEP] step=1–4 (standard 4-step solve)
[END] success=true steps=4 score=0.990 rewards=0.25,0.50,0.75,0.99
```
