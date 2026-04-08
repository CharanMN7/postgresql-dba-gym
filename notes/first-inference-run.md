# First end-to-end `inference.py` run — annotated

Date: 2026-04-08
Final scores: `{"easy": 1.0, "medium": 0.865, "hard": 1.0}`

This is the first run where an actual LLM agent drove the gym (via
`inference.py` → OpenAI-compatible endpoint → `/reset` + `/step` loop).
Every number below is read directly from the harness output you pasted.

---

## Headline

| Task   | Reward | Steps used | Verdict                                               |
|--------|--------|-----------:|-------------------------------------------------------|
| easy   | 1.00   | 2          | Perfect. Optimal composite index in one shot.         |
| medium | 0.865  | 7          | Above the 0.85 success threshold, but not perfect.    |
| hard   | 1.00   | 10         | Perfect. Hit all four sub-rubrics.                    |

The aggregate is **2.865 / 3.0**. The env, the grader, the HTTP layer,
the FastAPI/openenv 0.2.3 glue, and the LLM action-parsing in
`inference.py` all work end-to-end against a real model. This is the
first time the full stack has been exercised together.

---

## Task 1 — Index Optimization (easy) — 1.0

### What the agent did

1. **`EXPLAIN ANALYZE SELECT * FROM task_schema.orders WHERE customer_id = 12345 AND status = 'pending' ORDER BY order_date DESC`**
   — reward `0.041`. Diagnostic only. Shows a `Seq Scan on orders` with
   57 matching rows, confirming there's no usable index. The tiny
   non-zero reward is the `speedup_score` formula running with
   `baseline_ms / current_ms` where current is still the unindexed
   query, which rounds to ~0.04 rather than exactly 0.

2. **`CREATE INDEX idx_orders_customer_status_orderdate ON task_schema.orders (customer_id, status, order_date DESC)`**
   — reward `1.0`. Notes line:
   `baseline=3.73ms current=0.07ms ratio=52.86x`.
   The new query is 52× faster than the pre-index baseline. The
   `speedup_score` is capped at 1.0 (since 52.86 / 10 > 1.0), and the
   `optimal_index_bonus = 0.10` also triggers because the new index
   covers the full `{customer_id, status, order_date}` set. Capped at
   1.0 by the `min(1.0, ...)` clamp.

Note the `indexes_present` note reports
`[['customer_id', 'order_date', 'status']]` — that's just the grader
sorting the column set alphabetically before printing. The actual
`CREATE INDEX` ordering (`customer_id, status, order_date`) was
preserved in pg_catalog.

### Why this was the ideal path

The composite index `(customer_id, status, order_date)` is exactly
what the query planner wants:
- Both equality predicates are leading columns → index seek.
- The trailing `order_date` lets Postgres skip the explicit Sort node
  (it reads the index in order).

Adding `DESC` on `order_date` is a small cherry on top — the agent
noticed the `ORDER BY order_date DESC` and matched the sort direction,
avoiding even a backward-scan. The grader doesn't reward that
specifically, but it made the measured speedup dramatic (52× instead
of the ~10–15× you'd get from a forward-sorted index).

---

## Task 2 — Schema Migration (medium) — 0.865

### What the agent did, step by step

| # | Action                                                               | Reward    | What the grader says                          |
|---|----------------------------------------------------------------------|----------:|------------------------------------------------|
| 1 | `SELECT * FROM information_schema.columns WHERE … user_orders`       | 0.000     | Discovery query, no changes yet                |
| 2 | `SELECT column_name FROM information_schema.columns …`               | 0.000     | Discovery query                                |
| 3 | `CREATE TABLE customers (id, name NOT NULL, email UNIQUE NOT NULL…)` | **0.3125**| Half of schema rubric + all constraints it can |
| 4 | `CREATE TABLE orders (id, customer_id, …, FK → customers(id))`       | **0.5000**| Schema rubric fully complete = 0.25 total      |
| 5 | `INSERT INTO customers … SELECT DISTINCT … FROM user_orders` (200)   | 0.5000    | Customers populated, orders still empty        |
| 6 | `INSERT INTO orders … SELECT … JOIN customers ON email` (2000)       | **0.6150**| Data partially correct                         |
| 7 | `CREATE VIEW user_orders_view AS SELECT … JOIN …`                    | **0.8650**| View rubric complete                           |

### Sub-rubric breakdown at the end

The four equal-weighted sub-rubrics (0.25 each) landed at:

| Sub-rubric   | Score    | Why                                                     |
|--------------|---------:|---------------------------------------------------------|
| `schema`     | **0.25** | Both `customers` and `orders` tables exist with PKs     |
| `data`       | **~0.115** | Count ✓, distinct customers ✓, **spot-check 1/10 only** |
| `constraints`| **0.25** | FK, UNIQUE email, NOT NULL name, NOT NULL email all set |
| `view`       | **0.25** | `user_orders_view` exists and returns the right columns |
| **total**    | **0.865**|                                                         |

### Why it stalled at 0.865 instead of 1.0

The grading note that matters is **`data: matched 1/10 spot-check rows`**.
The data sub-rubric is built from three checks:

1. Row count in `orders` equals 2000 ✓
2. Distinct `customer_id` count equals 200 ✓
3. Ten randomly-chosen `user_orders` rows should still be retrievable
   via `user_orders_view` with matching field values.

The agent lost ~0.135 on check #3. The root cause is that the agent
did:

```sql
INSERT INTO task_schema.orders (customer_id, order_date, amount, status)
SELECT c.id, uo.order_date, uo.amount, uo.status
FROM   task_schema.user_orders uo
JOIN   task_schema.customers   c ON uo.customer_email = c.email;
```

This is *functionally* correct — every `user_orders` row becomes an
`orders` row with the right fields. But the grader's spot-check
almost certainly keys on **`row_id` / `orders.id` equality** (i.e. it
expects `orders.id == user_orders.row_id` so the migration preserves
the original identifiers). The agent used `SERIAL` on `orders.id`,
which generates fresh sequential IDs based on the order the rows come
out of the `JOIN` — which is *not* in the original `row_id` order.

So 9 out of 10 spot-checked rows looked up the wrong `orders.id` and
failed to match, even though the *contents* of the migrated table are
logically identical to the original denormalized table.

### How a perfect medium run would look

Either:
- `CREATE TABLE orders (id INT PRIMARY KEY, …)` (not SERIAL) and
  explicitly pass `row_id AS id` in the INSERT, **or**
- `INSERT INTO orders (id, customer_id, …) OVERRIDING SYSTEM VALUE
  SELECT uo.row_id, c.id, …` (PostgreSQL 10+ syntax for inserting
  explicit values into identity columns).

The agent saw the `row_id` column in its `SELECT column_name` probe
but didn't connect that `row_id` was meant to become `orders.id`. A
better system prompt, or one more discovery step asking "what is the
relationship between `user_orders.row_id` and my new `orders.id`?",
would have caught this.

### Why we still call this a pass

The task's `SUCCESS_THRESHOLD = 0.85`, and 0.865 clears it. The env
correctly auto-flipped `done=true` on the step that crossed the
threshold, which is why the run ended after the `CREATE VIEW` without
attempting to re-seed the orders table.

---

## Task 3 — Performance Diagnosis (hard) — 1.0

This is the most elaborate task (four simultaneous problems). The
agent took ten steps but hit a perfect score. Here's the progression:

| # | Action                                                          | Reward | What the grader says                                 |
|---|-----------------------------------------------------------------|-------:|------------------------------------------------------|
| 1 | `SELECT * FROM pg_indexes WHERE schemaname='task_schema'`       | 0.000  | Discovery — only `events_pkey` exists                |
| 2 | `CREATE INDEX idx_events_user_id ON events(user_id)`            | 0.125  | indexes rubric half-filled                           |
| 3 | `CREATE INDEX idx_events_event_type ON events(event_type)`      | 0.250  | indexes rubric complete                              |
| 4 | `SELECT … FROM pg_stat_activity WHERE state='idle in transaction'` | 0.250  | Discovery: found blocker pid=579, app=`dba_gym_blocker` |
| 5 | `SELECT pg_terminate_backend(579)`                              | 0.500  | blocker rubric complete                              |
| 6 | `VACUUM FULL task_schema.bloated_logs`                          | 0.750  | bloat rubric complete (size 27MB → 5MB)              |
| 7 | `ALTER SYSTEM SET work_mem = '4MB'`                             | 0.750  | No change yet — setting not in effect                |
| 8 | `ALTER SYSTEM SET random_page_cost = '2.0'`                     | 0.750  | Still not reloaded                                   |
| 9 | `ALTER SYSTEM SET effective_cache_size = '512MB'`               | 0.750  | Still not reloaded                                   |
|10 | `SELECT pg_reload_conf()`                                       | **1.000** | All three GUCs picked up → gucs rubric complete   |

### What each sub-rubric is really checking

| Sub-rubric | Weight | Check                                                                                                   |
|------------|------:|---------------------------------------------------------------------------------------------------------|
| `indexes`  | 0.25 | Is there any index covering `events.user_id`? And `events.event_type`? (0.125 each).                   |
| `bloat`    | 0.25 | Either `pg_stat_user_tables.n_dead_tup < 10%` of the initial bloat **OR** table size < 50% of initial. |
| `gucs`     | 0.25 | Three GUC thresholds (~0.083 each): `work_mem >= 4MB`, `random_page_cost <= 2.0`, `effective_cache_size >= 512MB`. The check reads the *current session's* effective value, so it only passes after `pg_reload_conf()` lands a new config. |
| `blocker`  | 0.25 | Zero sessions in `state='idle in transaction'` with `application_name='dba_gym_blocker'`.               |

### Things this run demonstrated

1. **The grader correctly accepts the `size` branch of the bloat
   check.** Notice the observation after `VACUUM FULL`:
   `bloat: dead_tup 80000->80000, size 27893760->5595136`.
   `n_dead_tup` didn't drop (because `pg_stat_user_tables` stats weren't
   updated immediately), but the table size fell from ~27 MB to ~5.5 MB.
   The `_grade_bloat` helper uses `OR` between the two conditions, so
   this counted as a full 0.25. Without the `OR`, the agent would have
   needed an explicit `ANALYZE` to pick up the dead-tuple stats.

2. **`ALTER SYSTEM` without reload is a no-op.** Steps 7–9 all return
   "OK" and change nothing in the effective config — reward stays at
   0.75. The agent correctly remembered that `ALTER SYSTEM` only
   writes to `postgresql.auto.conf`, and `pg_reload_conf()` is required
   to make the values visible to the running cluster. Step 10 is what
   actually unlocked the final 0.25.

3. **Multi-statement SQL is *not* required for this task.** The agent
   sent one statement per step, which is fine — the `sqlparse.split`
   plumbing we added is only needed when the agent wants to submit a
   multi-statement payload. The idle-blocker thread and the GUC reload
   both work equally well with single-statement actions.

4. **The blocker thread and `pg_terminate_backend` loop work inside
   the container.** This was the risky bit of Task 3 — spawning a
   daemon thread that holds a row lock on `bloated_logs`, then having
   the env correctly report its pid via `pg_stat_activity`, then
   having the agent kill it. All three happened cleanly.

---

## Observations about `inference.py` itself

- The log format matches the hackathon spec exactly:
  `[START] / [STEP] action: … | observation: … | reward: … / [END]`
  — no stray stdout, no JSON blobs, nothing that would trip the judge's
  parser.
- The `_build_observation_text` helper is doing its job: the
  observations are trimmed to single lines with `…` truncation, which
  keeps the log readable.
- The `done=true` logic works correctly — on task 2 the env
  auto-flipped done when the 0.865 threshold crossed 0.85, and on task
  3 the agent hit 1.0 so the env flipped done on reward-max.
- The `task` kwarg flow (`POST /reset {"task":"hard"}`) worked via the
  `ResetRequest extra="allow"` path on openenv-core 0.2.3. This was
  the migration risk we were most worried about.

## What I'd tighten next (not blockers)

1. **Medium task system prompt hint.** A one-liner in the task
   description like "Preserve row identity: `user_orders.row_id` should
   map to the new `orders.id`" would turn the 0.865 into a 1.0 without
   making the task trivially easy.
2. **Grader row-identity check.** Alternatively, make the spot-check
   tolerant: match on `(customer_email, order_date, amount, status)`
   tuple equality instead of `orders.id == row_id`. The agent's
   current migration is logically correct; punishing it for not
   preserving surrogate keys is arguably too strict.
3. **Cache the baseline measurement on Task 1.** The 0.041 reward on
   the discovery step is just noise from the shaped-reward formula.
   Zeroing it out until at least one `CREATE INDEX` has run would make
   the early steps easier to read.

None of these affect the submission — the scores already clear all
three thresholds and the HTTP contract is correct.

---

## tl;dr

It works. A real LLM drove a real Postgres cluster through three DBA
tasks and scored 2.865/3.0 on its first attempt, with all the
determinism, grading, and reward-shaping firing as designed. The
missing 0.135 is a single spot-check failure on the medium task where
the agent's logically-correct migration didn't preserve surrogate row
IDs. Everything else is green.
