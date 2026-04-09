# Fourteenth end-to-end `inference.py` run — annotated (Llama-3.3-70B-Instruct, first GPT-tier open model)

Date: 2026-04-09
Model: `meta-llama/Llama-3.3-70B-Instruct`
Final scores: `{"easy": 0.990, "medium": 0.865, "hard": 0.990, "expert": 0.990, "master": 0.990}`
Aggregate: **4.825 / 5.0**

All five tasks pass on the first run. This is the first open-source
model to clear all five thresholds, and the first to rival GPT-family
aggregates. The 70B model has **zero format compliance issues** (the
failure that destroyed Llama 8B on hard), discovers the `customer_name`
column prefix after only 2 failed attempts on medium, and solves hard
in 5 efficient steps with multi-statement actions.

---

## Headline — fourteen runs side by side

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

---

## Per-task analysis

### easy — index optimization (score: 0.990, 1 step)

Solved in a **single step** — no diagnostic EXPLAIN, just the
optimal composite index:

```
CREATE INDEX idx_orders_customer_id_status_order_date
  ON task_schema.orders (customer_id, status, order_date DESC);
```

This is the most efficient easy solve of any model. GPT models
typically use 1–2 steps; the 70B model skips discovery entirely and
goes straight to the correct index.

### medium — schema migration (score: 0.865, 7 steps)

The breakthrough: this model **discovers the column name prefix
after only 2 failed attempts**.

| Step | Action | Reward | Notes |
|------|--------|--------|-------|
| 1 | `CREATE TABLE customers (…)` | 0.31 | Schema started |
| 2 | `CREATE TABLE orders (…); ALTER TABLE … ADD CONSTRAINT FK …` | 0.50 | Multi-statement: table + FK in one step |
| 3 | `INSERT INTO customers (name, email, address) SELECT DISTINCT name, email, address FROM user_orders` | 0.50 | Error: column "name" does not exist |
| 4 | `INSERT … SELECT DISTINCT uo.name, uo.email, uo.address FROM user_orders uo` | 0.50 | Error: column uo.name does not exist |
| 5 | `INSERT … SELECT DISTINCT customer_name, customer_email, customer_address FROM user_orders` | **0.61** | **Found the prefix!** |
| 6 | `CREATE VIEW user_orders_view AS SELECT c.name, c.email, c.address, …` | 0.79 | View created but column names aren't aliased |
| 7 | `DROP VIEW …; CREATE VIEW … AS SELECT c.name AS customer_name, c.email AS customer_email, …` | **0.86** | View with correct aliases → done |

**Why 0.865 not 1.0:** Same as gpt-4o in Run 1 — the data sub-rubric's
spot-check fails because `orders.id` doesn't preserve
`user_orders.row_id`. The agent used `SERIAL` for `orders.id`, giving
fresh sequential IDs. 0.865 clears the 0.85 threshold → success.

**Critical contrast with Llama 8B:** The 8B model tried `name`,
`u.name`, then dropped columns one by one, never trying `customer_name`.
The 70B model tried `name`, `uo.name`, then correctly hypothesized
`customer_name` — a fundamental reasoning capability gap.

### hard — performance diagnosis (score: 0.990, 5 steps)

Clean 5-step solve with multi-statement efficiency:

| Step | Action | Reward | Notes |
|------|--------|--------|-------|
| 1 | `EXPLAIN ANALYZE …; SELECT * FROM pg_indexes …; SELECT * FROM pg_stat_user_tables …; SELECT name, setting FROM pg_settings …` | 0.01 | **4-query discovery in 1 step** — found missing indexes, blocker pid, GUC values |
| 2 | `CREATE INDEX … (user_id); CREATE INDEX … (event_type)` | 0.25 | Both indexes in one step |
| 3 | `SELECT pg_terminate_backend(81)` | 0.50 | Targeted kill using pid from step 1 |
| 4 | `ALTER SYSTEM SET work_mem = '4MB'; ALTER SYSTEM SET random_page_cost = 2.0; ALTER SYSTEM SET effective_cache_size = '512MB'; SELECT pg_reload_conf()` | 0.75 | All 3 GUCs + reload in one step |
| 5 | `VACUUM FULL task_schema.bloated_logs` | 0.99 | Bloat reclaimed → done |

**No format compliance issues.** The 70B model outputs raw SQL
consistently — no JSON wrappers, no trailing explanations. Every action
parses cleanly via `parse_action()` Strategy 3.

**Contrast with Llama 8B:** The 8B model scored 0.01 on hard because
it wrapped SQL in JSON+text. The 70B model scores 0.99 by simply
outputting SQL. Same system prompt, same environment, same parser —
the difference is purely instruction-following capability.

### expert — backup & recovery (score: 0.990, 4 steps)

Most efficient expert solve of any model:

1. `INSERT INTO customers (SELECT * FROM backup_customers WHERE id NOT IN (SELECT id FROM customers))` → 0.46
2. `INSERT INTO orders (SELECT * FROM backup_orders WHERE id NOT IN …)` → 0.71
3. `CREATE TABLE audit_log AS SELECT * FROM backup_audit_log WITH NO DATA; INSERT INTO audit_log SELECT * FROM backup_audit_log` → 0.96
4. `UPDATE customers SET balance = backup_customers.balance FROM backup_customers WHERE customers.id = backup_customers.id AND customers.balance = 0.00` → 0.99

The model used `SELECT *` throughout (no column-name risk) and the
`FROM … WHERE id NOT IN` pattern without needing intermediate backup
tables. The `WITH NO DATA` + `INSERT` for audit_log is a clean idiom.

GPT models typically took 4–8 steps on expert. This 4-step solve with
clean reward progression (0.46 → 0.71 → 0.96 → 0.99) is optimal.

### master — security audit (score: 0.990, 1 step)

All four security fixes in a single multi-statement action:

```
ALTER ROLE analytics_user NOSUPERUSER;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
REVOKE SELECT ON task_schema.salaries FROM readonly_user;
ALTER ROLE intern_user WITH PASSWORD 'intern_password';
```

Tied with Llama 8B Run 13 for fastest master solve.

---

## Key observations

1. **First open model to pass all five tasks.** Llama 8B failed hard
   (format) and medium (column names) on every run. The 70B model
   passes both — the parameter count jump from 8B to 70B crosses a
   qualitative capability threshold.

2. **No format compliance issues.** The 70B model always produces raw
   SQL that `parse_action()` Strategy 3 handles cleanly. It never
   wraps output in JSON despite the system prompt requesting it — the
   same "accidental compatibility" as GPT models.

3. **Column-name reasoning.** The 70B model hypothesized
   `customer_name` after seeing `column "name" does not exist` twice.
   This is a non-trivial inference: the error says "name" doesn't exist
   in `user_orders`, the target table is `customers`, so the source
   columns likely have a `customer_` prefix. The 8B model lacks this
   reasoning capability entirely.

4. **Multi-statement efficiency.** The model packs related operations
   into single steps (4-query discovery on hard, both indexes in one
   step, all GUCs + reload together, all master fixes at once). This
   reduces step count and keeps the context window lean.

5. **4.825 places it between gpt-3.5-turbo and gpt-4o-mini.**
   - gpt-4o-mini best: 5.000
   - **Llama-3.3-70B: 4.825**
   - gpt-3.5-turbo best: 4.865
   - Llama-3.1-8B best: 3.530

---

## Raw log output

```
[START] task=easy env=postgres_dba_gym model=meta-llama/Llama-3.3-70B-Instruct
[STEP] step=1 action=CREATE INDEX idx_orders_customer_id_status_order_date ON task_schema.orders (customer_id, status, order_date DESC); reward=0.99 done=true error=null
[END] success=true steps=1 score=0.990 rewards=0.99
[START] task=medium env=postgres_dba_gym model=meta-llama/Llama-3.3-70B-Instruct
[STEP] step=1 action=CREATE TABLE task_schema.customers (...); reward=0.31 done=false error=null
[STEP] step=2 action=CREATE TABLE task_schema.orders (...); ALTER TABLE ... ADD CONSTRAINT fk_customer_...; reward=0.50 done=false error=null
[STEP] step=3 action=INSERT INTO task_schema.customers (name, email, address) SELECT DISTINCT name, email, address FROM task_schema.user_orders; reward=0.50 done=false error=column "name" does not exist
[STEP] step=4 action=INSERT INTO task_schema.customers (name, email, address) SELECT DISTINCT uo.name, uo.email, uo.address FROM task_schema.user_orders uo; reward=0.50 done=false error=column uo.name does not exist
[STEP] step=5 action=INSERT INTO task_schema.customers (name, email, address) SELECT DISTINCT customer_name, customer_email, customer_address FROM task_schema.user_orders; reward=0.61 done=false error=null
[STEP] step=6 action=CREATE VIEW task_schema.user_orders_view AS SELECT c.name, c.email, c.address, o.order_date, o.amount, o.status FROM task_schema.customers c JOIN task_schema.orders o ON c.id = o.customer_id; reward=0.79 done=false error=null
[STEP] step=7 action=DROP VIEW task_schema.user_orders_view; CREATE VIEW task_schema.user_orders_view AS SELECT c.name AS customer_name, c.email AS customer_email, c.address AS customer_address, ...; reward=0.86 done=true error=null
[END] success=true steps=7 score=0.865 rewards=0.31,0.50,0.50,0.50,0.61,0.79,0.86
[START] task=hard env=postgres_dba_gym model=meta-llama/Llama-3.3-70B-Instruct
[STEP] step=1 action=EXPLAIN ANALYZE ...; SELECT * FROM pg_indexes ...; SELECT * FROM pg_stat_user_tables ...; SELECT name, setting FROM pg_settings ...; reward=0.01 done=false error=null
[STEP] step=2 action=CREATE INDEX idx_events_user_id ON task_schema.events (user_id); CREATE INDEX idx_events_event_type ON task_schema.events (event_type); reward=0.25 done=false error=null
[STEP] step=3 action=SELECT pg_terminate_backend(81); reward=0.50 done=false error=null
[STEP] step=4 action=ALTER SYSTEM SET work_mem = '4MB'; ALTER SYSTEM SET random_page_cost = 2.0; ALTER SYSTEM SET effective_cache_size = '512MB'; SELECT pg_reload_conf(); reward=0.75 done=false error=null
[STEP] step=5 action=VACUUM FULL task_schema.bloated_logs; reward=0.99 done=true error=null
[END] success=true steps=5 score=0.990 rewards=0.01,0.25,0.50,0.75,0.99
[START] task=expert env=postgres_dba_gym model=meta-llama/Llama-3.3-70B-Instruct
[STEP] step=1 action=INSERT INTO customers (SELECT * FROM backup_customers WHERE id NOT IN (SELECT id FROM customers)) reward=0.46 done=false error=null
[STEP] step=2 action=INSERT INTO orders (SELECT * FROM backup_orders WHERE id NOT IN (SELECT id FROM orders)) reward=0.71 done=false error=null
[STEP] step=3 action=CREATE TABLE audit_log AS SELECT * FROM backup_audit_log WITH NO DATA; INSERT INTO audit_log SELECT * FROM backup_audit_log reward=0.96 done=false error=null
[STEP] step=4 action=UPDATE customers SET balance = backup_customers.balance FROM backup_customers WHERE customers.id = backup_customers.id AND customers.balance = 0.00 reward=0.99 done=true error=null
[END] success=true steps=4 score=0.990 rewards=0.46,0.71,0.96,0.99
[START] task=master env=postgres_dba_gym model=meta-llama/Llama-3.3-70B-Instruct
[STEP] step=1 action=ALTER ROLE analytics_user NOSUPERUSER; REVOKE CREATE ON SCHEMA public FROM PUBLIC; REVOKE SELECT ON task_schema.salaries FROM readonly_user; ALTER ROLE intern_user WITH PASSWORD 'intern_password'; reward=0.99 done=true error=null
[END] success=true steps=1 score=0.990 rewards=0.99
```
