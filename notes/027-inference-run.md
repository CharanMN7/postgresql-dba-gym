# Run 27 — first Llama-4-Scout encounter (format issues, medium fails)

Date: 2026-04-09
Model: `meta-llama/Llama-4-Scout-17B-16E-Instruct`
Final scores: `{"easy": 0.990, "medium": 0.785, "hard": 0.990, "expert": 0.990, "master": 0.990}`
Aggregate: **4.745 / 5.0**

First documented run of Llama-4-Scout, a **Mixture of Experts** model
(17B total params, 16 experts). Introduces several unique behaviors:
a **LEFT JOIN anti-join pattern** on expert (no other model uses this),
**intermittent JSON format failures** on medium, and an
**`audit_log` schema-hallucination struggle** that takes 6+ steps to
resolve on expert. Medium fails at 0.785 due to combined format errors
and a `uo.row_id` hallucination.

---

## Per-task analysis

### easy — index optimization (score: 0.990, 2 steps)

Standard `EXPLAIN (ANALYZE, BUFFERS)` → `CREATE INDEX`.

### medium — schema migration (score: 0.785, 15 steps) — FAILED

This run exhibits **two distinct failure modes** on medium:

**1. JSON format instability (steps 2–3, 8–9, 13):**
The model intermittently outputs raw JSON (`{ "sql": "INSERT ...", "done": false }`)
that `parse_action()` treats as raw SQL (Strategy 3), causing
`syntax error at or near "{"`. This is the same class of format issue
seen in Llama-3.1-8B-Instruct (Runs 11–13), but here it's intermittent
rather than consistent — the model switches between raw SQL and JSON
mid-episode.

**2. View column hallucination (steps 12, 15):**
`SELECT uo.row_id` references both a non-existent `row_id` column and
a non-existent `uo` alias. The `FROM` clause only has `orders o` and
`customers c`, so `uo` causes "missing FROM-clause entry for table uo".
Model signals `done=true` after the error on step 15.

| Step | Action | Reward | Issue |
|------|--------|--------|-------|
| 1 | CREATE TABLE customers | 0.31 | |
| 2–3 | JSON-wrapped INSERT | 0.31 | Format error × 2 |
| 4–5 | Raw INSERT (name, uo.name) | 0.31 | Column name errors |
| 6 | `information_schema` introspection | 0.31 | |
| 7 | INSERT customers (correct names) | 0.31 | |
| 8–9 | JSON-wrapped CREATE TABLE orders | 0.31 | Format error × 2 |
| 10 | Raw CREATE TABLE orders | 0.50 | |
| 11 | CREATE VIEW (no aliases) | 0.58 | |
| 12 | `CREATE OR REPLACE VIEW … uo.row_id` | 0.58 | Missing FROM "uo" |
| 13 | JSON-wrapped INSERT orders | 0.58 | Format error |
| 14 | Raw INSERT orders | 0.79 | |
| 15 | `CREATE OR REPLACE VIEW … uo.row_id` | 0.79 | Same error + done=true |

The orders table doesn't exist until step 10 because the model tried
to create it inside JSON blocks that failed. This delays the entire
pipeline by 5+ steps.

### hard — performance diagnosis (score: 0.990, 6 steps)

Different task ordering from other models: indexes → GUCs → blocker → VACUUM.

| Step | Action | Reward |
|------|--------|--------|
| 1 | `pg_indexes` inspection | 0.01 |
| 2 | `CREATE INDEX (user_id); CREATE INDEX (event_type)` | 0.25 |
| 3 | `ALTER SYSTEM SET work_mem TO '4MB'; … random_page_cost TO '2.0'; … effective_cache_size TO '512MB'; SELECT pg_reload_conf()` | 0.50 |
| 4 | `SELECT pid, query FROM pg_stat_activity WHERE state = 'idle in transaction'` | 0.50 |
| 5 | `SELECT pg_terminate_backend(205)` | 0.75 |
| 6 | `VACUUM FULL task_schema.bloated_logs` | 0.99 |

### expert — backup & recovery (score: 0.990, 8 steps)

**New: LEFT JOIN anti-join pattern** for inserting missing rows:

| Step | Action | Reward | Notes |
|------|--------|--------|-------|
| 1 | `INSERT INTO customers SELECT bc.* FROM backup_customers bc LEFT JOIN customers c ON bc.id = c.id WHERE c.id IS NULL` | 0.46 | **Anti-join** — elegant |
| 2 | `INSERT INTO orders SELECT bo.* FROM backup_orders bo LEFT JOIN orders o ON bo.id = o.id WHERE o.id IS NULL` | 0.71 | Same pattern |
| 3 | `CREATE TABLE IF NOT EXISTS audit_log (id SERIAL PRIMARY KEY, column1 VARCHAR(255), column2 JSONB); INSERT INTO audit_log SELECT * FROM backup_audit_log` | 0.71 | Error: more expressions than target columns |
| 4 | `SELECT column_name, data_type FROM information_schema.columns WHERE table_name='backup_audit_log'` | 0.71 | Introspection |
| 5–6 | Explicit column attempts with wrong names | 0.71 | `log_time`, `event_type` don't exist |
| 7 | `DROP TABLE IF EXISTS audit_log; CREATE TABLE audit_log (correct columns); INSERT SELECT *` | 0.96 | Finally drops and recreates |
| 8 | `UPDATE customers c SET balance = bc.balance FROM backup_customers bc WHERE c.id = bc.id AND c.balance != bc.balance` | 0.99 | Uses `!=` instead of `= 0.00` |

The LEFT JOIN anti-join is the most SQL-elegant approach to the "insert
missing rows" problem. Compare:
- **Llama-4-Scout:** `LEFT JOIN … WHERE c.id IS NULL` (anti-join)
- **Qwen 72B:** `EXCEPT` or `WHERE id NOT IN`
- **Gemma 27B:** `WHERE customer_id NOT IN`
- **gpt-4o-mini:** `ON CONFLICT (id) DO NOTHING`

The `audit_log` struggle (steps 3–7) is caused by hallucinating the
table schema. The model creates explicit columns (`column1 VARCHAR`,
`log_time TIMESTAMP`, etc.) that don't match the actual backup, and
only resolves this after 5 attempts by using `CREATE TABLE AS SELECT *`.

### master — security audit (score: 0.990, 5 steps)

**Inspection-first approach:** queries `pg_roles` before acting:

| Step | Action | Reward |
|------|--------|--------|
| 1 | `SELECT rolname, rolsuper, rolcanlogin FROM pg_roles WHERE rolname='analytics_user'` | 0.01 |
| 2 | `ALTER ROLE analytics_user NOSUPERUSER` | 0.25 |
| 3 | `REVOKE CREATE ON SCHEMA public FROM PUBLIC` | 0.50 |
| 4 | `REVOKE SELECT ON task_schema.salaries FROM readonly_user` | 0.75 |
| 5 | `ALTER ROLE intern_user WITH PASSWORD 'a_final_strong_password'` | 0.99 |

Password is stronger than other models (`a_final_strong_password` vs
`password123` or `securepassword123`).

---

## Raw log output

```
[START] task=easy ... model=meta-llama/Llama-4-Scout-17B-16E-Instruct
[END] success=true steps=2 score=0.990
[START] task=medium ...
[STEP] step=2–3 (JSON format errors) reward=0.31
[STEP] step=4–5 (column name errors) reward=0.31
[STEP] step=6 (information_schema) reward=0.31
[STEP] step=8–9 (JSON format errors) reward=0.31
[STEP] step=10 (CREATE TABLE orders) reward=0.50
[STEP] step=14 (INSERT orders) reward=0.79
[STEP] step=15 (CREATE VIEW uo.row_id error + done=true) reward=0.79
[END] success=false steps=15 score=0.785
[START] task=hard ...
[END] success=true steps=6 score=0.990
[START] task=expert ...
[STEP] step=1 (LEFT JOIN anti-join customers) reward=0.46
[STEP] step=2 (LEFT JOIN anti-join orders) reward=0.71
[STEP] step=3–6 (audit_log schema struggles) reward=0.71
[STEP] step=7 (DROP + CREATE TABLE AS SELECT) reward=0.96
[STEP] step=8 (UPDATE balance) reward=0.99
[END] success=true steps=8 score=0.990
[START] task=master ...
[END] success=true steps=5 score=0.990
```
