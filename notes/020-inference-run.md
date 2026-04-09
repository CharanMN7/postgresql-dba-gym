# Twentieth end-to-end `inference.py` run — annotated (Qwen2.5-72B-Instruct, first run)

Date: 2026-04-09
Model: `Qwen/Qwen2.5-72B-Instruct`
Final scores: `{"easy": 0.990, "medium": 0.865, "hard": 0.990, "expert": 0.010, "master": 0.010}`
Aggregate: **2.865 / 5.0**

First encounter with Qwen 72B reveals a **catastrophic interaction between
the model's explicit transaction wrapping and an environment bug.** The model
uniquely wraps actions in `BEGIN; … COMMIT;` blocks. When an error occurs
inside the explicit transaction (wrong column name on expert), the
environment's connection pool returns the connection with a stale aborted
transaction that poisons all subsequent steps, the master task, and even
the next full inference run.

---

## Headline — twenty runs side by side

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
| **20** | **Qwen2.5-72B-Instruct** | 0.990 |  0.865 | 0.990 |  **0.010** | **0.010** | **2.865 / 5.0** |

---

## Per-task analysis

### easy — index optimization (score: 0.990, 2 steps)

Standard pattern: `EXPLAIN (ANALYZE, BUFFERS)` (0.07) → `CREATE INDEX
idx_orders_customer_id_status_order_date ON task_schema.orders
(customer_id, status, order_date DESC)` (0.99). Identical to Gemma/Llama
70B easy-task behavior.

### medium — schema migration (score: 0.865, 15 steps)

| Step | Action | Reward | Notes |
|------|--------|--------|-------|
| 1 | `CREATE TABLE customers (…)` | 0.31 | Separate from orders |
| 2 | `CREATE TABLE orders (…)` | 0.50 | FK constraint |
| 3–11 | `INSERT INTO customers (name, email, address) SELECT DISTINCT name, …` | 0.50 | **9 failed attempts** — column "name" does not exist |
| 12 | `SELECT column_name FROM information_schema.columns WHERE table_schema='task_schema' AND table_name='user_orders'` | 0.50 | Schema introspection after 9 errors |
| 13 | `INSERT INTO customers … SELECT DISTINCT customer_name, customer_email, customer_address FROM user_orders` | 0.50 | Correct column names |
| 14 | `INSERT INTO orders … SELECT c.id, uo.order_date, uo.amount, uo.status FROM user_orders uo JOIN customers c ON uo.customer_email = c.email` | 0.61 | FK join via email |
| 15 | `CREATE VIEW user_orders_view AS SELECT o.id AS row_id, c.name AS customer_name, …` | **0.86** | `o.id AS row_id` — correct alias |

Medium passes (0.865 ≥ 0.85) but is inefficient: 9 errors before
introspection, and tables created in separate steps. The view creation
uses `o.id AS row_id` which is the correct approach.

### hard — performance diagnosis (score: 0.990, 9 steps)

| Step | Action | Reward |
|------|--------|--------|
| 1 | `EXPLAIN ANALYZE SELECT * FROM events WHERE user_id = 42` | 0.01 |
| 2 | `CREATE INDEX idx_events_user_id ON task_schema.events (user_id)` | 0.12 |
| 3 | `CREATE INDEX idx_events_event_type ON task_schema.events (event_type)` | 0.25 |
| 4 | `SELECT pid, … FROM pg_stat_activity WHERE state = 'idle in transaction'` | 0.25 |
| 5 | `SELECT pg_terminate_backend(107)` | 0.50 |
| 6 | `VACUUM FULL task_schema.bloated_logs` | 0.75 |
| 7 | `ALTER SYSTEM SET work_mem = '4MB'; SELECT pg_reload_conf()` | 0.83 |
| 8 | `ALTER SYSTEM SET random_page_cost = '2.0'; SELECT pg_reload_conf()` | 0.92 |
| 9 | `ALTER SYSTEM SET effective_cache_size = '512MB'; SELECT pg_reload_conf()` | 0.99 |

Solves correctly but uses **individual steps** for each index and each
GUC — 9 steps vs Gemma 27B's 5-step combined approach. Competent but
not efficient.

### expert — backup & recovery (score: 0.010, 25 steps) — CATASTROPHIC FAILURE

**This is the critical finding of Run 20.**

| Step | Action | Reward | Notes |
|------|--------|--------|-------|
| 1 | `BEGIN; INSERT INTO customers SELECT * FROM backup_customers ON CONFLICT (customer_id) DO NOTHING; COMMIT;` | 0.01 | Error: column "customer_id" does not exist |
| 2 | `BEGIN; INSERT … ON CONFLICT DO NOTHING; COMMIT;` | 0.01 | **"current transaction is aborted"** |
| 3 | `ROLLBACK; INSERT … WHERE customer_id NOT IN …` | 0.01 | Same stale transaction error |
| 5 | `BEGIN; TRUNCATE customers; INSERT …; COMMIT;` | 0.01 | Destructive action blocked |
| 6–25 | Various ROLLBACK/INSERT/BEGIN attempts | 0.01 | **All fail with "current transaction is aborted"** |

**Root cause chain:**

1. **Model wraps SQL in `BEGIN; … COMMIT;`** — unique to Qwen, no other
   tested model does this.
2. **Model hallucinated `customer_id`** — the PK column is actually `id`.
   This is a common error (Gemma 27B also makes it initially).
3. **`_execute_sql()` splits the multi-statement via `sqlparse.split()`**
   into `['BEGIN', 'INSERT … ON CONFLICT (customer_id) …', 'COMMIT']` and
   executes them sequentially. `BEGIN` succeeds → `INSERT` fails → the
   `psycopg2.Error` exception is caught → **`COMMIT` never executes**.
4. **`borrow_connection()`'s `finally` block** only calls `conn.rollback()`
   when `autocommit=False`, but the connection uses `autocommit=True`.
   The stale explicit transaction is never cleaned up.
5. **Connection returned to pool dirty.** Every subsequent borrow gets
   a connection stuck in `TRANSACTION_STATUS_INERROR`.
6. **All remaining expert steps fail.** Even explicit `ROLLBACK` sent
   by the model fails because in autocommit mode, `psycopg2` sends the
   ROLLBACK without first acknowledging the transaction state.
7. **Master task poisoned** — `reset()` borrows from the same pool.
8. **Next `make inference` poisoned** — the server process persists.

### master — security audit (score: 0.010, 0 steps) — POISONED

```
[DEBUG] run_task error: Server error: current transaction is aborted,
commands ignored until end of transaction block (code: EXECUTION_ERROR)
```

Master never executes a single step. The `env.reset()` call itself
fails because it borrows a poisoned connection from the pool.

---

## Environment bug: stale explicit transaction

### The bug

In `server/db.py`, `borrow_connection()`:

```python
finally:
    try:
        if not conn.closed and not autocommit:  # ← bug: skips cleanup when autocommit=True
            conn.rollback()
    except psycopg2.Error:
        pass
    pool.putconn(conn)
```

When `autocommit=True` (the default), the rollback is skipped. If the
agent started an explicit `BEGIN` and an error occurred before `COMMIT`,
the connection is returned to the pool with a stale
`TRANSACTION_STATUS_INERROR` transaction. Every subsequent borrow of
that connection fails.

### Impact

- 2 of 3 Qwen expert runs scored 0.010 due to this bug
- In both cases, master was also poisoned (0.010)
- One full re-run (5 tasks) was entirely poisoned until `make down`

### Attribution: model vs environment

| Factor | Responsibility | Explanation |
|--------|---------------|-------------|
| Model: hallucinated `customer_id` | ~25% | Common error — Gemma/Llama also hallucinate this initially but recover via introspection |
| Model: `BEGIN;…COMMIT;` wrapping | ~5% | Unnecessary but not inherently wrong — works fine when the SQL is correct (Run 22) |
| Environment: no stale transaction cleanup | ~70% | Converted a recoverable column-name error into a 25-step cascading failure affecting 2+ tasks and future runs |

Without the environment bug, the model would have received a clean error
message on step 1 and had 24 remaining attempts to discover the correct
column name (as it does on medium via `information_schema`).

---

## Raw log output

```
[START] task=easy env=postgres_dba_gym model=Qwen/Qwen2.5-72B-Instruct
[STEP] step=1 action=EXPLAIN (ANALYZE, BUFFERS) SELECT * FROM task_schema.orders WHERE customer_id = 12345 AND status = 'pending' ORDER BY order_date DESC reward=0.07 done=false error=null
[STEP] step=2 action=CREATE INDEX idx_orders_customer_id_status_order_date ON task_schema.orders (customer_id, status, order_date DESC); reward=0.99 done=true error=null
[END] success=true steps=2 score=0.990 rewards=0.07,0.99
[START] task=medium env=postgres_dba_gym model=Qwen/Qwen2.5-72B-Instruct
[STEP] step=1–2 (table creation) reward=0.31→0.50
[STEP] step=3–11 (column name retry loop × 9) reward=0.50 error=column "name" does not exist
[STEP] step=12 action=SELECT column_name FROM information_schema.columns WHERE table_schema='task_schema' AND table_name='user_orders'; reward=0.50 error=null
[STEP] step=13 action=INSERT INTO customers (name, email, address) SELECT DISTINCT customer_name, customer_email, customer_address FROM user_orders; reward=0.50 error=null
[STEP] step=14 action=INSERT INTO orders ... JOIN customers c ON uo.customer_email = c.email; reward=0.61 error=null
[STEP] step=15 action=CREATE VIEW user_orders_view AS SELECT o.id AS row_id, c.name AS customer_name, ...; reward=0.86 done=true error=null
[END] success=true steps=15 score=0.865 rewards=0.31,0.50,0.50,0.50,0.50,0.50,0.50,0.50,0.50,0.50,0.50,0.50,0.50,0.61,0.86
[START] task=hard env=postgres_dba_gym model=Qwen/Qwen2.5-72B-Instruct
[STEP] step=1–3 (EXPLAIN + 2 indexes) reward=0.01→0.25
[STEP] step=4–5 (idle blocker discovery + terminate) reward=0.50
[STEP] step=6 (VACUUM FULL) reward=0.75
[STEP] step=7–9 (3 GUC changes, 1 per step) reward=0.83→0.92→0.99
[END] success=true steps=9 score=0.990 rewards=0.01,0.12,0.25,0.25,0.50,0.75,0.83,0.92,0.99
[START] task=expert env=postgres_dba_gym model=Qwen/Qwen2.5-72B-Instruct
[STEP] step=1 action=BEGIN; INSERT INTO customers SELECT * FROM backup_customers ON CONFLICT (customer_id) DO NOTHING; COMMIT; reward=0.01 error=column "customer_id" does not exist
[STEP] step=2–25 (all fail with "current transaction is aborted") reward=0.01
[END] success=false steps=25 score=0.010 rewards=0.01×25
[START] task=master env=postgres_dba_gym model=Qwen/Qwen2.5-72B-Instruct
[DEBUG] run_task error: Server error: current transaction is aborted
[END] success=false steps=0 score=0.010 rewards=
```
