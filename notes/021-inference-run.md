# Twenty-first end-to-end `inference.py` run — annotated (Qwen2.5-72B-Instruct, run 2)

Date: 2026-04-09
Model: `Qwen/Qwen2.5-72B-Instruct`
Final scores: `{"easy": 0.990, "medium": 0.615, "hard": 0.990, "expert": 0.010, "master": 0.010}`
Aggregate: **2.615 / 5.0**

Second Qwen run after a container restart (`make down` / `make up`).
Two new failures relative to Run 20: medium drops from 0.865 to 0.615
(view column hallucination + premature `done=true`), and the expert
transaction catastrophe recurs identically. This is the lowest aggregate
of any 72B-class model.

---

## Per-task analysis

### easy — index optimization (score: 0.990, 2 steps)

Identical to Run 20: `EXPLAIN (ANALYZE, BUFFERS)` → `CREATE INDEX`.

### medium — schema migration (score: 0.615, 12 steps) — FAILED

| Step | Action | Reward | Notes |
|------|--------|--------|-------|
| 1 | `CREATE TABLE customers (id SERIAL PRIMARY KEY, name TEXT NOT NULL, email TEXT NOT NULL UNIQUE, address TEXT NOT NULL)` | 0.31 | Separate table creation |
| 2 | `CREATE TABLE orders (… FOREIGN KEY (customer_id) REFERENCES customers(id))` | 0.50 | FK constraint |
| 3–8 | `INSERT INTO customers (name, email, address) SELECT DISTINCT name, …` | 0.50 | **6 failed attempts** — column "name" does not exist |
| 9 | `SELECT column_name FROM information_schema.columns WHERE table_schema='task_schema' AND table_name='user_orders'` | 0.50 | Introspection |
| 10 | `INSERT INTO customers … SELECT DISTINCT customer_name, customer_email, customer_address …` | 0.50 | Correct |
| 11 | `INSERT INTO orders … SELECT c.id, uo.order_date, uo.amount, uo.status FROM user_orders uo JOIN customers c ON uo.customer_email = c.email` | 0.61 | FK join |
| 12 | `CREATE VIEW user_orders_view AS SELECT o.row_id, c.name AS customer_name, …` | 0.61 | **Error: column `o.row_id` does not exist** + `done=true` |

**Why this fails when Run 20 passed:** In Run 20, the model wrote
`o.id AS row_id` (aliasing the `id` column to `row_id`). Here, the
model hallucinates a column `o.row_id` that doesn't exist in the
`orders` table, and signals `done=true` on the errored step, ending the
episode at 0.615 — well below the 0.85 threshold.

This is a dual failure: **column hallucination** (non-existent
`row_id` column) and **premature done signaling** (declaring completion
despite the error). The model sees the error in its observation but
does not realize the view creation failed.

### hard — performance diagnosis (score: 0.990, 9 steps)

Same individual-step pattern as Run 20: separate indexes (steps 2–3),
individual GUC changes (steps 7–9). Functionally identical.

### expert — backup & recovery (score: 0.010, 25 steps) — CATASTROPHIC FAILURE (repeat)

Identical failure pattern to Run 20:

1. Step 1: `BEGIN; INSERT INTO customers SELECT * FROM backup_customers
   ON CONFLICT (customer_id) DO NOTHING; COMMIT;` → column "customer_id"
   does not exist
2. Steps 2–25: all "current transaction is aborted"

The model uses the exact same `BEGIN; … ON CONFLICT (customer_id) …;
COMMIT;` template. Combined with the environment bug, the result is
deterministically catastrophic.

**Repeated ROLLBACK attempts (steps 3, 7, 9, 11, 13, 15, 18, 21, 23):**
The model tries `ROLLBACK;` prefixed to its SQL at least 9 times, showing
it recognizes the transaction state problem. However, the environment's
SQL executor splits `ROLLBACK; INSERT …` into two statements, and the
first `ROLLBACK` either doesn't reach PostgreSQL correctly (due to
autocommit mode interaction) or the pool keeps serving the same dirty
connection.

### master — security audit (score: 0.010, 0 steps) — POISONED

Same as Run 20: `reset()` itself fails because the connection pool is
dirty.

---

## Run 20 vs Run 21 comparison

| Task   | Run 20 | Run 21 | Delta  | Cause |
|--------|--------|--------|--------|-------|
| easy   | 0.990  | 0.990  | 0.000  | Identical |
| medium | 0.865  | 0.615  | −0.250 | `o.id AS row_id` (correct) vs `o.row_id` (hallucinated) |
| hard   | 0.990  | 0.990  | 0.000  | Identical approach, same steps |
| expert | 0.010  | 0.010  | 0.000  | Same catastrophe |
| master | 0.010  | 0.010  | 0.000  | Both poisoned |
| **agg**| 2.865  | 2.615  | −0.250 | Medium regression |

The medium regression shows Qwen's output instability: the same task
with the same model produces a correct alias in one run (`o.id AS
row_id`) and a hallucinated column in the next (`o.row_id`). This
0.250-point swing from a single column reference is consistent with
the temperature=0.2 sampling used by `inference.py`.

---

## New finding: view column hallucination as systematic failure

| Model | Run | View SQL | Medium score | Outcome |
|-------|-----|----------|-------------|---------|
| Qwen 72B | 20 | `o.id AS row_id` | 0.865 | Pass |
| Qwen 72B | 21 | `o.row_id` | 0.615 | Fail — hallucinated column |
| Llama 70B | 16 | (view missing aliases) | 0.785 | Fail — wrong aliases |
| Gemma 27B | all | correct aliases | 0.865 | Pass — deterministic |
| gpt-3.5 | 9,10 | (never reaches view) | 0.500 | Fail — stuck at inserts |

View creation is the final bottleneck on medium. Models that get the
column aliasing right pass; those that don't, fail. Gemma 27B is the
only open model that deterministically handles this correctly.

---

## Raw log output

```
[START] task=easy env=postgres_dba_gym model=Qwen/Qwen2.5-72B-Instruct
[STEP] step=1 action=EXPLAIN (ANALYZE, BUFFERS) ... reward=0.07 done=false error=null
[STEP] step=2 action=CREATE INDEX idx_orders_customer_id_status_order_date ... reward=0.99 done=true error=null
[END] success=true steps=2 score=0.990 rewards=0.07,0.99
[START] task=medium env=postgres_dba_gym model=Qwen/Qwen2.5-72B-Instruct
[STEP] step=1 action=CREATE TABLE customers (…) reward=0.31
[STEP] step=2 action=CREATE TABLE orders (…) reward=0.50
[STEP] step=3–8 (column name retry loop × 6) reward=0.50 error=column "name" does not exist
[STEP] step=9 action=SELECT column_name FROM information_schema.columns ... reward=0.50
[STEP] step=10 action=INSERT INTO customers ... customer_name ... reward=0.50
[STEP] step=11 action=INSERT INTO orders ... JOIN ... reward=0.61
[STEP] step=12 action=CREATE VIEW ... o.row_id ... reward=0.61 done=true error=column o.row_id does not exist
[END] success=false steps=12 score=0.615 rewards=0.31,0.50,0.50,0.50,0.50,0.50,0.50,0.50,0.50,0.50,0.61,0.61
[START] task=hard env=postgres_dba_gym model=Qwen/Qwen2.5-72B-Instruct
[STEP] step=1–9 (EXPLAIN + indexes + blocker + VACUUM + GUCs) reward=0.01→0.99
[END] success=true steps=9 score=0.990 rewards=0.01,0.12,0.25,0.25,0.50,0.75,0.83,0.92,0.99
[START] task=expert env=postgres_dba_gym model=Qwen/Qwen2.5-72B-Instruct
[STEP] step=1 action=BEGIN; INSERT ... ON CONFLICT (customer_id) ... reward=0.01 error=column "customer_id" does not exist
[STEP] step=2–25 (all "current transaction is aborted") reward=0.01
[END] success=false steps=25 score=0.010 rewards=0.01×25
[START] task=master env=postgres_dba_gym model=Qwen/Qwen2.5-72B-Instruct
[DEBUG] run_task error: Server error: current transaction is aborted
[END] success=false steps=0 score=0.010 rewards=
```
