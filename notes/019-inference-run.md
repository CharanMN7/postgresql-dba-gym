# Nineteenth end-to-end `inference.py` run — annotated (Gemma-3-27B-IT, cross-model analysis)

Date: 2026-04-09
Model: `google/gemma-3-27b-it`
Final scores: `{"easy": 0.990, "medium": 0.865, "hard": 0.990, "expert": 0.990, "master": 0.990}`
Aggregate: **4.825 / 5.0**

Third and final Gemma run. All five tasks pass. The standout: medium
solved in just **6 steps** — the most efficient medium solve of any
model across all 19 runs. The model used `SELECT * FROM user_orders
LIMIT 10` (data sampling) instead of `information_schema` to discover
column names, then nailed both the data insertion and the view with
proper aliases in the next two steps.

---

## Headline — nineteen runs side by side

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
| 19  | Gemma-3-27B-IT               | 0.990 |  0.865 | 0.990 |  0.990 |  0.990 | 4.825 / 5.0     |

---

## Per-task analysis

### easy — index optimization (score: 0.990, 2 steps)

Discovery-first approach: `SELECT * FROM pg_indexes` (0.06) → CREATE
INDEX (0.99). Different discovery query from Run 17's EXPLAIN ANALYZE
but same outcome.

### medium — schema migration (score: 0.865, 6 steps)

**Most efficient medium solve across all 19 runs.**

| Step | Action | Reward | Notes |
|------|--------|--------|-------|
| 1 | `CREATE TABLE customers (…); CREATE TABLE orders (…); ALTER TABLE … FK …` | 0.50 | Combined schema setup |
| 2 | `INSERT INTO customers (name, email, address) SELECT DISTINCT name, …` | 0.50 | Error: column "name" |
| 3 | Same INSERT | 0.50 | Same error |
| 4 | `SELECT * FROM task_schema.user_orders LIMIT 10` | 0.50 | **Data sampling** — sees actual column names in output |
| 5 | `INSERT INTO customers (…) SELECT DISTINCT customer_name, customer_email, customer_address …; INSERT INTO orders (…) SELECT …` | **0.61** | Both inserts in one step |
| 6 | `CREATE VIEW … SELECT c.name AS customer_name, c.email AS customer_email, c.address AS customer_address, …` | **0.86** | Proper aliases first try |

**Why this is better than information_schema:** `SELECT * LIMIT 10`
returns actual data rows with column headers, giving the model both
the column names and example values in one shot. The model sees
`customer_name | customer_email | customer_address | order_date | …`
and immediately maps them to the target schema. In contrast,
`information_schema.columns` returns just column names as row values,
requiring an extra cognitive step to parse the result format.

**6 steps vs competitors:**
- Gemma Run 19: 6 steps (data sampling)
- Llama 70B Run 14: 7 steps (column-name inference)
- Gemma Run 17: 8 steps (information_schema)
- Gemma Run 18: 8 steps (information_schema)
- Llama 70B Run 15: 17 steps (information_schema after 12 errors)
- gpt-4o Run 1: 7 steps (information_schema proactively)

### hard — performance diagnosis (score: 0.990, 5 steps)

Identical 5-step pattern to Runs 17–18.

### expert — backup & recovery (score: 0.990, 8 steps)

Cleaner than Run 18's 14-step struggle. The model introspected the
`backup_customers` and `backup_orders` tables (not the target tables)
which was more useful:

| Step | Action | Reward | Notes |
|------|--------|--------|-------|
| 1 | `INSERT INTO customers SELECT * … WHERE customer_id NOT IN …` | 0.16 | Error: `customer_id` doesn't exist |
| 2 | `SELECT * FROM information_schema.columns WHERE table_name = 'backup_customers'` | 0.16 | Introspect **backup** table — smarter target |
| 3 | `INSERT INTO customers SELECT * … WHERE id NOT IN (SELECT id FROM customers)` | **0.46** | Corrected after 1 introspection |
| 4 | `INSERT INTO orders SELECT * … WHERE order_id NOT IN …` | 0.46 | Error: `order_id` doesn't exist |
| 5 | `SELECT * FROM information_schema.columns WHERE table_name = 'backup_orders'` | 0.46 | Introspect backup_orders |
| 6 | `INSERT INTO orders SELECT * … WHERE id NOT IN (SELECT id FROM orders)` | **0.71** | Corrected |
| 7 | `CREATE TABLE audit_log AS SELECT * FROM backup_audit_log` | **0.96** | |
| 8 | `UPDATE customers SET balance = bc.balance FROM backup_customers bc WHERE customers.id = bc.id AND customers.balance = 0.00` | **0.99** | Uses table alias `bc` — clean |

**Key improvement over Run 18:** Introspecting `backup_customers`
(step 2) instead of `customers` (Run 18 step 2) gives the model the
source column names directly. After introspection, the model
immediately corrected to `id` (1 try), vs Run 18's 4 attempts after
introspection. Also, the final UPDATE correctly uses `customers.id`
(not `customer_id`), reaching 0.99.

### master — security audit (score: 0.990, 4 steps)

Standard 4-step solve. Same password.

---

## Gemma-3-27B-IT: three-run summary

| Task   | Run 17 | Run 18 | Run 19 | Mean  | Std   | Verdict |
|--------|--------|--------|--------|-------|-------|---------|
| easy   | 0.990  | 0.990  | 0.990  | 0.990 | 0.000 | Reliable pass |
| medium | 0.865  | 0.865  | 0.865  | 0.865 | 0.000 | **Deterministic** — same score every run |
| hard   | 0.990  | 0.990  | 0.990  | 0.990 | 0.000 | Reliable pass |
| expert | 0.990  | 0.960  | 0.990  | 0.980 | 0.014 | Mostly reliable — Run 18 `customer_id` regression |
| master | 0.990  | 0.990  | 0.990  | 0.990 | 0.000 | Reliable pass |
| **agg**| 4.825  | 4.795  | 4.825  | 4.815 | 0.014 | |

Gemma is the **most consistent model tested**: medium is perfectly
deterministic at 0.865 across all three runs (zero variance), and
the only variance source is a single expert run (0.960 vs 0.990).
Compare to Llama 70B (medium variance: 0.785–0.865) and gpt-3.5-turbo
(medium variance: 0.500–0.865).

---

## Discovery strategy comparison across all open models

| Strategy | Model | When used | Steps to correct columns | Example |
|----------|-------|-----------|-------------------------|---------|
| Pattern inference | Llama 70B (Run 14) | After 2 errors | 2 | `name` → `uo.name` → `customer_name` |
| `information_schema.columns` | Gemma 27B (Run 17) | After 4 errors | 6 | Query metadata → correct on next try |
| `information_schema.columns` | Llama 70B (Run 15) | After 12 errors | 13 | Query metadata → correct on next try |
| `SELECT * … LIMIT 10` | Gemma 27B (Run 19) | After 2 errors | 4 | See actual data → correct on next try |
| `table_constraints JOIN key_column_usage` | Gemma 27B (Run 17) | After 1 error (expert) | 3 | PK discovery via constraint metadata |
| `SELECT * FROM table LIMIT 5` | Gemma 27B (Run 18) | After introspection failed to help | 5 | See actual data as fallback |
| Never | Llama 8B (all runs) | — | ∞ | Retries same wrong columns forever |

Gemma 27B uses the widest variety of discovery strategies of any model.

---

## Model tier ranking (final, all 19 runs)

| Tier | Model                        | Runs | Agg range       | Mean agg | Variance source |
|------|------------------------------|------|-----------------|----------|-----------------|
| S    | gpt-4o-mini                  | 5    | 4.880 – 5.000   | 4.932    | Medium (0.920–1.000) |
| A    | Gemma-3-27B-IT               | 3    | 4.795 – 4.825   | 4.815    | Expert (0.960–0.990) |
| A    | Llama-3.3-70B-Instruct       | 3    | 4.745 – 4.825   | 4.798    | Medium (0.785–0.865) |
| A-   | gpt-3.5-turbo                | 3    | 4.460 – 4.865   | 4.595    | Medium (0.500–0.865) |
| B    | gpt-4o                       | 1    | 2.865 (3 tasks) | —        | Incomplete data |
| C    | Llama-3.1-8B-Instruct        | 3    | 2.900 – 3.530   | 3.283    | Format + medium + expert |

### Parameter efficiency

| Model | Parameters | Mean agg | Agg per billion params |
|-------|-----------|----------|------------------------|
| Gemma-3-27B-IT | 27B | 4.815 | **0.178** |
| Llama-3.3-70B-Instruct | 70B | 4.798 | 0.069 |
| Llama-3.1-8B-Instruct | 8B | 3.283 | 0.410 |

Gemma 27B achieves a higher aggregate than the 70B Llama model at
38% of the parameter count. Among open models capable of passing
all five tasks (excluding 8B), Gemma is 2.6× more parameter-efficient.

### Key takeaways

1. **Gemma-3-27B edges out Llama-3.3-70B.** Mean 4.815 vs 4.798 —
   a slim 0.017 margin, but with significantly lower parameter
   count. The gap comes from Gemma's deterministic medium (0.865
   × 3 runs) vs Llama 70B's medium variance (one 0.785 outlier).

2. **Medium consistency separates tiers.** The top performers:
   - gpt-4o-mini: 0.920–1.000 (always passes, sometimes perfect)
   - Gemma 27B: 0.865 × 3 (always passes, deterministic)
   - Llama 70B: 0.785–0.865 (usually passes, one miss)
   - gpt-3.5-turbo: 0.500–0.865 (coin flip)
   - Llama 8B: 0.438–0.550 (never passes)

3. **Schema introspection is the dividing line.** Models that can
   query the schema and apply the results (Gemma, Llama 70B, gpt-4o,
   gpt-4o-mini) pass medium. Models that can't (Llama 8B) or won't
   (gpt-3.5-turbo sometimes) fail it.

4. **Data sampling > metadata queries.** Gemma Run 19's `SELECT *
   LIMIT 10` approach is faster and more effective than
   `information_schema.columns` because the model sees column names
   in their natural context (as headers) rather than as row values
   in a metadata table.

5. **Open models are competitive.** Two of the top three model tiers
   (A-tier) are open-source. The only advantage gpt-4o-mini retains
   is medium task consistency (0.920+ vs 0.865), likely due to
   proactive schema introspection or better column-name inference.

---

## Raw log output

```
[START] task=easy env=postgres_dba_gym model=google/gemma-3-27b-it
[STEP] step=1 action=SELECT * FROM pg_indexes WHERE schemaname='task_schema'; reward=0.06 done=false error=null
[STEP] step=2 action=CREATE INDEX orders_customer_status_orderdate ON task_schema.orders (customer_id, status, order_date DESC); reward=0.99 done=true error=null
[END] success=true steps=2 score=0.990 rewards=0.06,0.99
[START] task=medium env=postgres_dba_gym model=google/gemma-3-27b-it
[STEP] step=1 action=CREATE TABLE customers (...); CREATE TABLE orders (...); ALTER TABLE ... FK ...; reward=0.50 done=false error=null
[STEP] step=2–3 (column name errors) reward=0.50 error=column "name" does not exist
[STEP] step=4 action=SELECT * FROM task_schema.user_orders LIMIT 10; reward=0.50 done=false error=null
[STEP] step=5 action=INSERT INTO customers (name, email, address) SELECT DISTINCT customer_name, customer_email, customer_address FROM task_schema.user_orders; INSERT INTO orders ...; reward=0.61 done=false error=null
[STEP] step=6 action=CREATE VIEW task_schema.user_orders_view AS SELECT c.name AS customer_name, c.email AS customer_email, c.address AS customer_address, o.order_date, o.amount, o.status FROM task_schema.customers c JOIN ...; reward=0.86 done=true error=null
[END] success=true steps=6 score=0.865 rewards=0.50,0.50,0.50,0.50,0.61,0.86
[START] task=hard env=postgres_dba_gym model=google/gemma-3-27b-it
[STEP] step=1 action=CREATE INDEX ... (user_id); CREATE INDEX ... (event_type); reward=0.25 done=false error=null
[STEP] step=2 action=SELECT pid, application_name, state, query FROM pg_stat_activity WHERE state = 'idle in transaction'; reward=0.25 done=false error=null
[STEP] step=3 action=SELECT pg_terminate_backend(309); reward=0.50 done=false error=null
[STEP] step=4 action=VACUUM FULL task_schema.bloated_logs; reward=0.75 done=false error=null
[STEP] step=5 action=ALTER SYSTEM SET work_mem = '4MB'; ALTER SYSTEM SET random_page_cost = '2.0'; ALTER SYSTEM SET effective_cache_size = '512MB'; SELECT pg_reload_conf(); reward=0.99 done=true error=null
[END] success=true steps=5 score=0.990 rewards=0.25,0.25,0.50,0.75,0.99
[START] task=expert env=postgres_dba_gym model=google/gemma-3-27b-it
[STEP] step=1 action=INSERT INTO customers SELECT * FROM backup_customers WHERE customer_id NOT IN (SELECT customer_id FROM customers); reward=0.16 error=column "customer_id" does not exist
[STEP] step=2 action=SELECT * FROM information_schema.columns WHERE table_name = 'backup_customers'; reward=0.16 error=null
[STEP] step=3 action=INSERT INTO customers SELECT * FROM backup_customers WHERE id NOT IN (SELECT id FROM customers); reward=0.46 error=null
[STEP] step=4 action=INSERT INTO orders SELECT * FROM backup_orders WHERE order_id NOT IN (SELECT order_id FROM orders); reward=0.46 error=column "order_id" does not exist
[STEP] step=5 action=SELECT * FROM information_schema.columns WHERE table_name = 'backup_orders'; reward=0.46 error=null
[STEP] step=6 action=INSERT INTO orders SELECT * FROM backup_orders WHERE id NOT IN (SELECT id FROM orders); reward=0.71 error=null
[STEP] step=7 action=CREATE TABLE audit_log AS SELECT * FROM backup_audit_log; reward=0.96 error=null
[STEP] step=8 action=UPDATE customers SET balance = bc.balance FROM backup_customers bc WHERE customers.id = bc.id AND customers.balance = 0.00; reward=0.99 done=true error=null
[END] success=true steps=8 score=0.990 rewards=0.16,0.16,0.46,0.46,0.46,0.71,0.96,0.99
[START] task=master env=postgres_dba_gym model=google/gemma-3-27b-it
[STEP] step=1 action=ALTER ROLE analytics_user NOSUPERUSER; reward=0.25 done=false error=null
[STEP] step=2 action=REVOKE CREATE ON SCHEMA public FROM PUBLIC; reward=0.50 done=false error=null
[STEP] step=3 action=REVOKE SELECT ON task_schema.salaries FROM readonly_user; reward=0.75 done=false error=null
[STEP] step=4 action=ALTER ROLE intern_user WITH PASSWORD 'P@sswOrd123'; reward=0.99 done=true error=null
[END] success=true steps=4 score=0.990 rewards=0.25,0.50,0.75,0.99
```
