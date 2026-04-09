# Twelfth end-to-end `inference.py` run — annotated (Llama-3.1-8B-Instruct, expert regression)

Date: 2026-04-09
Model: `meta-llama/Llama-3.1-8B-Instruct`
Final scores: `{"easy": 0.990, "medium": 0.500, "hard": 0.010, "expert": 0.410, "master": 0.990}`
Aggregate: **2.900 / 5.0**

Worst aggregate of any run to date. The hard-task format failure
(documented in Run 11) persists identically. The new finding is a
severe **expert regression**: the model tried to list columns
explicitly on the backup-restore task, hit NOT NULL constraint errors
it couldn't recover from, then prematurely declared `done=true` at a
score of 0.41.

---

## Headline — twelve runs side by side

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

---

## Per-task analysis

### easy — index optimization (score: 0.990, 2 steps)

Identical to Run 11. EXPLAIN + CREATE INDEX in two steps.

### medium — schema migration (score: 0.500, 25 steps — FAILURE)

Same column-name retry loop as Run 11, but without the partial orders
insertion breakthrough. The model:
1. Created both tables + FK (steps 1–3, reward 0.50).
2. Spent steps 4–20 trying `INSERT INTO customers` with wrong column
   names (`name`, `email`, `address` instead of `customer_name`,
   `customer_email`, `customer_address`).
3. Switched to `INSERT INTO orders` at step 21 but used `id` instead
   of the correct column names — stuck again.
4. Exhausted the 25-step budget at 0.50.

Unlike Run 11 (which reached 0.55 by inserting orders without
`customer_id`), this run never found a partial-success path.

### hard — performance diagnosis (score: 0.010, 10 steps — FAILURE)

Identical format compliance failure. JSON+text hybrid on every step,
syntax error at `{`, context overflow at step 10. No progress possible.

### expert — backup & recovery (score: 0.410, 7 steps — FAILURE)

This is the regression. In Run 11 the model used `SELECT *` and scored
0.99. Here it tried explicit column lists and failed:

| Step | Action | Reward | Problem |
|------|--------|--------|---------|
| 1 | `CREATE TABLE customers_backup AS SELECT * FROM backup_customers` | 0.16 | OK |
| 2 | `CREATE TABLE audit_log AS SELECT * FROM backup_audit_log` | 0.41 | OK |
| 3 | `INSERT INTO customers (id, name, email, balance) SELECT …` | 0.41 | **NOT NULL on `created_at`** — insert listed 4 columns but `customers` has 6 (`created_at`, `updated_at` are NOT NULL) |
| 4 | `UPDATE customers SET created_at = …` | 0.41 | No-op: no rows were inserted (step 3 failed entirely) |
| 5 | `INSERT INTO orders (id, customer_id, order_date, total) SELECT …` | 0.41 | **NOT NULL on `status`** — same pattern, missing column |
| 6 | `UPDATE orders SET status = …` | 0.41 | No-op: same reason |
| 7 | `INSERT INTO audit_log (id, table_name, operation, data) SELECT …` | 0.41 | `column "operation" does not exist` — guessed wrong column name; `done=true` |

**Why `done=true` at 0.41?** The model likely output a JSON action with
`"done": true`, which `parse_action()` Strategy 1 handled correctly
(extracting both `sql` and `done`). The model believed the task was
complete even though reward was only 0.41 — a fundamentally wrong
self-assessment.

**Root cause:** The model chose explicit column lists instead of
`SELECT *`, then couldn't recover when NOT NULL constraints rejected
partial inserts. It never tried to introspect the schema. Contrast with
Run 11, where the same model used `INSERT … SELECT *` and avoided the
issue entirely. This is stochastic behavior at temperature 0.2.

### master — security audit (score: 0.990, 4 steps)

Identical to Run 11. Standard 4-step solve.

---

## Key observations

1. **Expert is the high-variance task for Llama 8B.** Runs 11 and 12
   show 0.990 vs 0.410 on expert — a 0.58-point swing. The difference
   is a single strategy choice: `SELECT *` (works) vs explicit columns
   (fails). GPT models show at most 0.04 variance on expert.

2. **Premature `done=true` is a new failure mode.** The model declared
   itself done at 0.41, wasting remaining budget. GPT models never
   signal done prematurely — they either hit the threshold or exhaust
   all steps.

3. **Medium is consistently bad.** Both runs fail on the same column
   names. The model never tries schema introspection (unlike gpt-4o
   in Run 1, which queried `information_schema.columns` first).

4. **2.900 is the new floor.** This is 1.56 points below gpt-3.5-turbo's
   worst (4.460) and 2.1 points below gpt-4o-mini's best (5.000).

---

## Raw log output

```
[START] task=easy env=postgres_dba_gym model=meta-llama/Llama-3.1-8B-Instruct
[STEP] step=1 action=EXPLAIN (ANALYZE, BUFFERS) SELECT * FROM task_schema.orders ...; reward=0.02 done=false error=null
[STEP] step=2 action=CREATE INDEX idx_orders_customer_id_status_order_date ON task_schema.orders (customer_id, status, order_date DESC); reward=0.99 done=true error=null
[END] success=true steps=2 score=0.990 rewards=0.02,0.99
[START] task=medium env=postgres_dba_gym model=meta-llama/Llama-3.1-8B-Instruct
[STEP] step=1 action=CREATE TABLE task_schema.customers (...); reward=0.31 done=false error=null
[STEP] step=2 action=CREATE TABLE task_schema.orders (...); reward=0.44 done=false error=null
[STEP] step=3 action=ALTER TABLE task_schema.orders ADD CONSTRAINT fk_orders_customers ...; reward=0.50 done=false error=null
[STEP] step=4–20 (column name loop on customers) reward=0.50 done=false error=column "name"/"email"/"address" does not exist
[STEP] step=21–25 (column name loop on orders) reward=0.50 done=false error=column "id" does not exist
[END] success=false steps=25 score=0.500 rewards=0.31,0.44,0.50,0.50,0.50,0.50,0.50,0.50,0.50,0.50,0.50,0.50,0.50,0.50,0.50,0.50,0.50,0.50,0.50,0.50,0.50,0.50,0.50,0.50,0.50
[START] task=hard env=postgres_dba_gym model=meta-llama/Llama-3.1-8B-Instruct
[STEP] step=1–9 (JSON+text format failure) action={"sql": "...", "done": false} ... reward=0.01 error=syntax error at or near "{"
[STEP] step=10 action= reward=0.01 done=true error=llm error: context length 8457 > 8192 limit
[END] success=false steps=10 score=0.010 rewards=0.01,0.01,0.01,0.01,0.01,0.01,0.01,0.01,0.01,0.01
[START] task=expert env=postgres_dba_gym model=meta-llama/Llama-3.1-8B-Instruct
[STEP] step=1 action=CREATE TABLE task_schema.customers_backup AS SELECT * FROM task_schema.backup_customers; reward=0.16 done=false error=null
[STEP] step=2 action=CREATE TABLE task_schema.audit_log AS SELECT * FROM task_schema.backup_audit_log; reward=0.41 done=false error=null
[STEP] step=3 action=INSERT INTO task_schema.customers (id, name, email, balance) SELECT ...; reward=0.41 done=false error=NOT NULL on created_at
[STEP] step=4 action=UPDATE task_schema.customers SET created_at = ...; reward=0.41 done=false error=null
[STEP] step=5 action=INSERT INTO task_schema.orders (id, customer_id, order_date, total) SELECT ...; reward=0.41 done=false error=NOT NULL on status
[STEP] step=6 action=UPDATE task_schema.orders SET status = ...; reward=0.41 done=false error=null
[STEP] step=7 action=INSERT INTO task_schema.audit_log (id, table_name, operation, data) SELECT ...; reward=0.41 done=true error=column "operation" does not exist
[END] success=false steps=7 score=0.410 rewards=0.16,0.41,0.41,0.41,0.41,0.41,0.41
[START] task=master env=postgres_dba_gym model=meta-llama/Llama-3.1-8B-Instruct
[STEP] step=1 action=ALTER ROLE analytics_user NOSUPERUSER; reward=0.25 done=false error=null
[STEP] step=2 action=REVOKE CREATE ON SCHEMA public FROM PUBLIC; reward=0.50 done=false error=null
[STEP] step=3 action=REVOKE SELECT ON task_schema.salaries FROM readonly_user; reward=0.75 done=false error=null
[STEP] step=4 action=ALTER ROLE intern_user WITH PASSWORD 'password123'; reward=0.99 done=true error=null
[END] success=true steps=4 score=0.990 rewards=0.25,0.50,0.75,0.99
```
