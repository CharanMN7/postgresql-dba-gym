# Run 25 — post-v2-fix (Qwen2.5-72B-Instruct)

Date: 2026-04-09
Model: `Qwen/Qwen2.5-72B-Instruct`
Final scores: `{"easy": 0.990, "medium": 0.615, "hard": 0.990, "expert": 0.990, "master": 0.990}`
Aggregate: **4.575 / 5.0**

First run after deploying the v2 stale-transaction fix
(`_drain_stale_transaction` with raw SQL ROLLBACK via cursor). Expert
succeeds for the first time with a **new strategy**: `EXCEPT` on step 1,
then `WHERE id NOT IN` on step 2 after the duplicate-key error. No
`BEGIN;…COMMIT;` wrapping appears in this run. Master solved in a single
multi-statement step — the most efficient master solve of any model.

---

## Per-task analysis

### easy — index optimization (score: 0.990, 2 steps)

Standard. `EXPLAIN (ANALYZE, BUFFERS)` → `CREATE INDEX`.

### medium — schema migration (score: 0.615, 13 steps) — FAILED

Same column-name retry loop (7 attempts, steps 3–9) →
`information_schema` introspection at step 10 → correct inserts →
`CREATE VIEW … o.row_id …` at step 13 with `done=true`.

The `o.row_id` hallucination persists. Now observed in **4 of 5 Qwen
runs** where medium reaches the view step. Only Run 20 used the correct
`o.id AS row_id`.

### hard — performance diagnosis (score: 0.990, 6 steps)

Efficient combined approach: indexes batched (step 2), GUCs batched
(step 6). Same as Runs 22 and 24.

### expert — backup & recovery (score: 0.990, 5 steps) — SUCCESS

**No `BEGIN;…COMMIT;` wrapping.** The model uses a different approach
from all previous Qwen runs:

| Step | Action | Reward | Notes |
|------|--------|--------|-------|
| 1 | `INSERT INTO customers (SELECT * FROM backup_customers EXCEPT SELECT * FROM customers)` | 0.16 | **New: EXCEPT** — duplicate key error on `id=350` |
| 2 | `INSERT INTO customers (SELECT * FROM backup_customers WHERE id NOT IN (SELECT id FROM customers))` | 0.46 | Adapts to `NOT IN` after error |
| 3 | `INSERT INTO orders (SELECT * FROM backup_orders EXCEPT SELECT * FROM orders)` | 0.71 | EXCEPT works for orders (no PK clash) |
| 4 | `CREATE TABLE audit_log AS SELECT * FROM backup_audit_log` | 0.96 | |
| 5 | `UPDATE customers SET balance = bc.balance FROM backup_customers bc WHERE customers.id = bc.id AND customers.balance = 0.00` | 0.99 | |

**Why EXCEPT fails on customers but works on orders:** `EXCEPT` returns
rows in the first set that aren't in the second set, comparing ALL
columns. If a customer exists in both tables but with a different
`balance`, `EXCEPT` considers it a "new" row and tries to insert it,
hitting the PK unique constraint. Orders apparently have no such overlap.

**Why this run avoids the transaction bug:** No explicit `BEGIN` means no
server-side transaction to poison. The duplicate-key error on step 1 is
a normal autocommit-mode error — the environment handles it cleanly and
step 2 gets a fresh connection.

### master — security audit (score: 0.990, 1 step) — NEW RECORD

```sql
ALTER ROLE analytics_user NOSUPERUSER;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
REVOKE SELECT ON task_schema.salaries FROM readonly_user;
ALTER ROLE intern_user WITH PASSWORD 'securepassword123';
```

**All four sub-tasks solved in a single multi-statement action.** Every
other model (and previous Qwen runs) takes 4 separate steps. This is the
most efficient master solve across all runs.

---

## New patterns in this run

### 1. `EXCEPT` as a set-difference insertion strategy

No other tested model uses `EXCEPT` for the expert task. The typical
approaches:

| Model | Expert step 1 |
|-------|---------------|
| **Qwen (Run 25)** | `INSERT INTO customers (SELECT * FROM backup_customers EXCEPT SELECT * FROM customers)` |
| Qwen (Runs 20–24) | `BEGIN; INSERT … ON CONFLICT (customer_id) …; COMMIT;` |
| Gemma 27B | `INSERT … WHERE customer_id NOT IN …` |
| Llama 70B | `INSERT … ON CONFLICT DO NOTHING` |

`EXCEPT` is semantically correct but fragile — it compares all columns,
so any data difference in existing rows causes a PK clash. The model
correctly diagnoses the error and switches to `NOT IN` on step 2.

### 2. One-step master

The 1-step master demonstrates Qwen's ability to combine all sub-tasks
into a single action when the solution is unambiguous. This is a pure
efficiency win — no other model achieves this.

---

## Raw log output

```
[START] task=easy env=postgres_dba_gym model=Qwen/Qwen2.5-72B-Instruct
[STEP] step=1 action=EXPLAIN (ANALYZE, BUFFERS) ... reward=0.07 done=false error=null
[STEP] step=2 action=CREATE INDEX idx_orders_customer_id_status_order_date ... reward=0.99 done=true error=null
[END] success=true steps=2 score=0.990 rewards=0.07,0.99
[START] task=medium env=postgres_dba_gym model=Qwen/Qwen2.5-72B-Instruct
[STEP] step=1–2 (table creation) reward=0.31→0.50
[STEP] step=3–9 (column name retry loop × 7) reward=0.50 error=column "name" does not exist
[STEP] step=10 action=SELECT column_name FROM information_schema.columns ... reward=0.50
[STEP] step=11 action=INSERT INTO customers ... customer_name ... reward=0.50
[STEP] step=12 action=INSERT INTO orders ... JOIN ... reward=0.61
[STEP] step=13 action=CREATE VIEW ... o.row_id ... reward=0.61 done=true error=column o.row_id does not exist
[END] success=false steps=13 score=0.615 rewards=0.31,0.50×8,0.50,0.61,0.61
[START] task=hard env=postgres_dba_gym model=Qwen/Qwen2.5-72B-Instruct
[STEP] step=1–6 (EXPLAIN + indexes + blocker + VACUUM + GUCs combined) reward=0.01→0.99
[END] success=true steps=6 score=0.990 rewards=0.01,0.25,0.25,0.50,0.75,0.99
[START] task=expert env=postgres_dba_gym model=Qwen/Qwen2.5-72B-Instruct
[STEP] step=1 action=INSERT INTO customers (SELECT * FROM backup_customers EXCEPT SELECT * FROM customers); reward=0.16 error=duplicate key value violates unique constraint "customers_pkey" Key (id)=(350)
[STEP] step=2 action=INSERT INTO customers (SELECT * FROM backup_customers WHERE id NOT IN (SELECT id FROM customers)); reward=0.46 error=null
[STEP] step=3 action=INSERT INTO orders (SELECT * FROM backup_orders EXCEPT SELECT * FROM orders); reward=0.71 error=null
[STEP] step=4 action=CREATE TABLE audit_log AS SELECT * FROM backup_audit_log; reward=0.96 error=null
[STEP] step=5 action=UPDATE customers SET balance = bc.balance FROM backup_customers bc WHERE customers.id = bc.id AND customers.balance = 0.00; reward=0.99 done=true error=null
[END] success=true steps=5 score=0.990 rewards=0.16,0.46,0.71,0.96,0.99
[START] task=master env=postgres_dba_gym model=Qwen/Qwen2.5-72B-Instruct
[STEP] step=1 action=ALTER ROLE analytics_user NOSUPERUSER; REVOKE CREATE ON SCHEMA public FROM PUBLIC; REVOKE SELECT ON task_schema.salaries FROM readonly_user; ALTER ROLE intern_user WITH PASSWORD 'securepassword123'; reward=0.99 done=true error=null
[END] success=true steps=1 score=0.990 rewards=0.99
```
