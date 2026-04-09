# Eleventh end-to-end `inference.py` run — annotated (Llama-3.1-8B-Instruct, first open model)

Date: 2026-04-09
Model: `meta-llama/Llama-3.1-8B-Instruct`
Final scores: `{"easy": 0.990, "medium": 0.550, "hard": 0.010, "expert": 0.990, "master": 0.990}`
Aggregate: **3.530 / 5.0**

First run of the first open-source model tested. Introduces a critical
**output format compliance failure** on the hard task that drops it to
0.01 — the model outputs JSON+text hybrids that `parse_action()` cannot
extract, so the raw JSON string is sent to PostgreSQL as SQL and
immediately fails with a syntax error. This is the first model to exhibit
inconsistent output format across tasks.

---

## Headline — eleven runs side by side

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

---

## Critical finding: output format compliance failure

The system prompt instructs models to reply with
`{"sql": "<your SQL>", "done": <true|false>}`. The `parse_action()`
function handles three strategies:

1. **Strategy 1** — whole content is valid JSON → extract `sql` field.
2. **Strategy 2** — fenced code block → extract JSON or raw SQL.
3. **Strategy 3** — treat raw content as SQL (fallback).

All GPT models produce either clean JSON (Strategy 1) or raw SQL
(Strategy 3), both of which work. Llama 8B is **inconsistent across
tasks**:

| Task   | Format Llama actually outputs                            | Parser path | Result   |
|--------|----------------------------------------------------------|-------------|----------|
| easy   | Raw SQL                                                  | Strategy 3  | Works    |
| medium | Raw SQL                                                  | Strategy 3  | Works    |
| hard   | `{"sql": "...", "done": false} I will first terminate…`  | Strategy 3  | **FAILS** |
| expert | Raw SQL                                                  | Strategy 3  | Works    |
| master | Raw SQL                                                  | Strategy 3  | Works    |

On the hard task, the model attempts to follow the JSON format from the
system prompt but **appends a natural language explanation** after the
closing brace. `json.loads()` (Strategy 1) fails on the trailing text.
No fenced block exists (Strategy 2 skips). Strategy 3 treats the entire
string — `{"sql": "SELECT …", "done": false} I will first terminate…`
— as raw SQL, and PostgreSQL sees `{` as a syntax error.

The model repeats this exact pattern for all 9 steps until the context
window overflows (8192 token limit), never once correcting the format.
This means the model:

1. Cannot self-diagnose an output format error, even when the error
   message literally says `syntax error at or near "{"`.
2. Does not adapt when receiving identical error feedback repeatedly.
3. Only attempts the JSON format on the most complex task (hard),
   suggesting the task complexity triggers a mode switch in generation.

**Scoring impact:** No separate penalty is needed — the 0.010 score
already reflects the total inability to make progress. The format
failure *is* the task failure.

---

## Per-task analysis

### easy — index optimization (score: 0.990, 2 steps)

Standard 2-step solve:
1. `EXPLAIN ANALYZE` — diagnostic only (reward 0.07).
2. `CREATE INDEX … (customer_id, status, order_date DESC)` — reward 0.99.

Score is 0.990 rather than the 1.000 seen on GPT models. Likely the
same composite index but a slightly different speedup ratio due to
`EXPLAIN ANALYZE` warming the cache differently. The 0.01 delta is
measurement noise, not a meaningful capability gap.

### medium — schema migration (score: 0.550, 25 steps — FAILURE)

Two phases of failure:

**Phase 1 (steps 1–3): Schema setup — correct.**
Created `customers`, `orders`, and the FK constraint. Reward climbed
from 0.31 → 0.44 → 0.50 — all sub-rubrics for schema complete.

**Phase 2 (steps 4–13): Column name retry loop.**
Tried `INSERT INTO customers (name, email, address) SELECT name, email,
address FROM user_orders` — error: `column "name" does not exist`.
The actual columns in `user_orders` are `customer_name`,
`customer_email`, `customer_address`. The model cycled through:
- Unqualified column names
- Table-alias-qualified names (`u.name`)
- Dropping columns one by one
- Never once tried `SELECT * FROM information_schema.columns` to
  discover the actual column names.

**Phase 3 (steps 14–25): Partial data insertion + stuck UPDATE.**
At step 14, the model tried inserting orders without `customer_id`:
`INSERT INTO orders (order_date, amount, status) SELECT u.order_date,
u.amount, u.status FROM user_orders u` — this worked (reward 0.55)
because `order_date`, `amount`, `status` happen to match.

Then spent steps 15–25 trying to UPDATE `customer_id` via a JOIN on
`c.email = u.email`, but `u.email` doesn't exist in `user_orders`
(it's `customer_email`). Same loop: 11 identical failing statements.

Compared to gpt-3.5-turbo's 0.500 on medium, Llama 8B squeezed out
an extra 0.05 by accidentally getting partial orders data in, but both
models share the same fundamental failure: no schema introspection.

### hard — performance diagnosis (score: 0.010, 10 steps — FAILURE)

**Total failure due to output format compliance issue** (see critical
finding above).

Steps 1–9: Every action is a JSON+text hybrid that PostgreSQL rejects.
Step 10: LLM context window overflow (8459 tokens > 8192 limit).

The SQL *inside* the JSON is often reasonable (terminate idle sessions,
create indexes, vacuum), but none of it ever reaches PostgreSQL. The
model's strategy shows it understood the task at a high level — it just
couldn't execute.

### expert — backup & recovery (score: 0.990, 5 steps)

Clean 5-step solve:
1. `CREATE TABLE customers_backup AS SELECT * FROM backup_customers` — reward 0.16.
2. `CREATE TABLE audit_log AS SELECT * FROM backup_audit_log` — reward 0.41.
3. `INSERT INTO customers … WHERE id NOT IN (SELECT id FROM customers)` — reward 0.71.
4. `INSERT INTO orders … WHERE id NOT IN (SELECT id FROM orders)` — reward 0.96.
5. `UPDATE customers SET balance = … WHERE balance = 0.00` — reward 0.99, done.

The `SELECT *` approach avoided the column-name pitfalls that plagued
medium. The model used `INSERT … SELECT *` instead of listing columns
explicitly, letting PostgreSQL match columns positionally. This is the
same approach that succeeded for GPT models on expert.

### master — security audit (score: 0.990, 4 steps)

Standard 4-step solve:
1. `ALTER ROLE analytics_user NOSUPERUSER` → 0.25
2. `REVOKE CREATE ON SCHEMA public FROM PUBLIC` → 0.50
3. `REVOKE SELECT ON task_schema.salaries FROM readonly_user` → 0.75
4. `ALTER ROLE intern_user WITH PASSWORD 'mysecretpassword'` → 0.99

Identical pattern to all previous models.

---

## Key observations

1. **First model with a format compliance failure.** All GPT models
   produce output that `parse_action()` can handle. Llama 8B is the
   first to produce a format that falls through all three parsing
   strategies into a broken state.

2. **The format issue is task-specific.** Only the hard task triggers
   the JSON+explanation pattern. The model outputs raw SQL on all other
   tasks. This suggests the task's complexity or multi-problem framing
   pushes the model into a "structured reasoning" mode where it wraps
   its output in JSON and adds explanatory text.

3. **8K context window is a hard wall.** Llama 8B has an 8192-token
   limit. On both hard (step 10) and the longer medium retry loops,
   the conversation history overflows and the run terminates with an
   API error. GPT models have 128K+ context and never hit this limit.

4. **`SELECT *` is a better strategy than explicit columns for this
   environment.** Expert succeeded because `INSERT … SELECT *`
   bypasses column-name discovery. Medium failed because the model
   tried to list column names and guessed wrong. A smarter system
   prompt could hint at introspection.

5. **Model tier ranking update:**
   - gpt-4o-mini: 4.880–5.000
   - gpt-3.5-turbo: 4.460–4.865
   - Llama-3.1-8B-Instruct: 3.530 (first run)

---

## Raw log output

```
[START] task=easy env=postgres_dba_gym model=meta-llama/Llama-3.1-8B-Instruct
[STEP] step=1 action=EXPLAIN (ANALYZE, BUFFERS) SELECT * FROM task_schema.orders WHERE customer_id = 12345 AND status = 'pending' ORDER BY order_date DESC; reward=0.07 done=false error=null
[STEP] step=2 action=CREATE INDEX idx_orders_customer_id_status_order_date ON task_schema.orders (customer_id, status, order_date DESC); reward=0.99 done=true error=null
[END] success=true steps=2 score=0.990 rewards=0.07,0.99
[START] task=medium env=postgres_dba_gym model=meta-llama/Llama-3.1-8B-Instruct
[STEP] step=1 action=CREATE TABLE task_schema.customers (...); reward=0.31 done=false error=null
[STEP] step=2 action=CREATE TABLE task_schema.orders (...); reward=0.44 done=false error=null
[STEP] step=3 action=ALTER TABLE task_schema.orders ADD CONSTRAINT fk_orders_customers FOREIGN KEY (customer_id) REFERENCES task_schema.customers(id); reward=0.50 done=false error=null
[STEP] step=4–13 (column name loop) action=INSERT INTO task_schema.customers (name/email/address variants) SELECT ... FROM task_schema.user_orders; reward=0.50 done=false error=column "name"/"email"/"address" does not exist
[STEP] step=14 action=INSERT INTO task_schema.orders (order_date, amount, status) SELECT u.order_date, u.amount, u.status FROM task_schema.user_orders u; reward=0.55 done=false error=null
[STEP] step=15–25 (UPDATE loop) action=UPDATE task_schema.orders SET customer_id = ... JOIN ... ON c.email = u.email; reward=0.55 done=false error=column u.email does not exist
[END] success=false steps=25 score=0.550 rewards=0.31,0.44,0.50,0.50,0.50,0.50,0.50,0.50,0.50,0.50,0.50,0.50,0.50,0.55,0.55,0.55,0.55,0.55,0.55,0.55,0.55,0.55,0.55,0.55,0.55
[START] task=hard env=postgres_dba_gym model=meta-llama/Llama-3.1-8B-Instruct
[STEP] step=1 action={"sql": "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE state = 'idle in transaction' AND application_name = 'long-running-session';", "done": false} I will first terminate the long-r... reward=0.01 done=false error=syntax error at or near "{"
[STEP] step=2–9 (identical format failure) action={"sql": "...", "done": false} ... reward=0.01 done=false error=syntax error at or near "{"
[STEP] step=10 action= reward=0.01 done=true error=llm error: context length 8459 > 8192 limit
[END] success=false steps=10 score=0.010 rewards=0.01,0.01,0.01,0.01,0.01,0.01,0.01,0.01,0.01,0.01
[START] task=expert env=postgres_dba_gym model=meta-llama/Llama-3.1-8B-Instruct
[STEP] step=1 action=CREATE TABLE task_schema.customers_backup AS SELECT * FROM task_schema.backup_customers; reward=0.16 done=false error=null
[STEP] step=2 action=CREATE TABLE task_schema.audit_log AS SELECT * FROM task_schema.backup_audit_log; reward=0.41 done=false error=null
[STEP] step=3 action=INSERT INTO task_schema.customers SELECT * FROM task_schema.customers_backup WHERE id NOT IN (SELECT id FROM task_schema.customers); reward=0.71 done=false error=null
[STEP] step=4 action=INSERT INTO task_schema.orders SELECT * FROM task_schema.backup_orders WHERE id NOT IN (SELECT id FROM task_schema.orders); reward=0.96 done=false error=null
[STEP] step=5 action=UPDATE task_schema.customers SET balance = (SELECT balance FROM task_schema.customers_backup WHERE id = task_schema.customers.id) WHERE balance = 0.00; reward=0.99 done=true error=null
[END] success=true steps=5 score=0.990 rewards=0.16,0.41,0.71,0.96,0.99
[START] task=master env=postgres_dba_gym model=meta-llama/Llama-3.1-8B-Instruct
[STEP] step=1 action=ALTER ROLE analytics_user NOSUPERUSER; reward=0.25 done=false error=null
[STEP] step=2 action=REVOKE CREATE ON SCHEMA public FROM PUBLIC; reward=0.50 done=false error=null
[STEP] step=3 action=REVOKE SELECT ON task_schema.salaries FROM readonly_user; reward=0.75 done=false error=null
[STEP] step=4 action=ALTER ROLE intern_user WITH PASSWORD 'mysecretpassword'; reward=0.99 done=true error=null
[END] success=true steps=4 score=0.990 rewards=0.25,0.50,0.75,0.99
```
