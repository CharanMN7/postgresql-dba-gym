# Third end-to-end `inference.py` run — annotated (gpt-4o-mini, take 2)

Date: 2026-04-08
Model: `gpt-4o-mini`
Final scores: `{"easy": 1.0, "medium": 0.920, "hard": 0.917}`
Aggregate: **2.837 / 3.0**

This is the third full run of the gym, and the second one driven by
`gpt-4o-mini`. Same model, same prompt, same grader as run 2 — but a
*lower* aggregate (2.837 vs 2.917). The interesting question is why,
and the answer is a clean illustration of model-side stochasticity
inside a fully deterministic grader.

---

## Headline — three runs side by side

| Task   | Run 1 (gpt-4o) | Run 2 (gpt-4o-mini) | **Run 3 (gpt-4o-mini)** |
|--------|---------------:|--------------------:|------------------------:|
| easy   | 1.000 / 2 steps | 1.000 / 2 steps    | **1.000 / 2 steps**     |
| medium | 0.865 / 7 steps | 1.000 / 8 steps    | **0.920 / 6 steps**     |
| hard   | 1.000 / 10 steps | 0.917 / 8 steps   | **0.917 / 8 steps**     |
| total  | 2.865          | **2.917**          | **2.837**               |

Easy is rock-stable across both models and three runs. Hard is now
reproduced *exactly* twice for mini — same eight steps, same auto-done
ceiling at 0.917. The whole movement between runs 2 and 3 lives in the
medium task, which dropped from a perfect 1.0 to 0.92.

---

## Task 1 — Index Optimization (easy) — 1.0

| # | Action | Reward | Note |
|---|--------|-------:|------|
| 1 | `EXPLAIN (ANALYZE, BUFFERS) SELECT * FROM task_schema.orders WHERE customer_id = 12345 AND status = 'pending' ORDER BY order_date DESC` | 0.07 | Diagnostic — same `BUFFERS` flag mini used in run 2 |
| 2 | `CREATE INDEX idx_customer_status_order_date ON task_schema.orders (customer_id, status, order_date DESC)` | **1.00** | Same composite-index shape as runs 1 and 2 |

The shaped diagnostic reward drifted slightly (0.04 → 0.05 → 0.07
across the three runs) — that's just `baseline_ms / current_ms`
jitter on a small table. The final score is clamped to 1.0 by the
`min(1.0, …)` cap, the optimal-index bonus fires, and we're done in
two steps. Easy is now confirmed-stable across three runs and two
models.

---

## Task 2 — Schema Migration (medium) — 0.920

This is where run 3 regressed against run 2 (1.0 → 0.92), with the
same model on the same prompt. The cause is *not* in the grader.

### Step-by-step

| # | Action | Reward | Note |
|---|--------|-------:|------|
| 1 | `CREATE TABLE customers (id SERIAL, name VARCHAR NOT NULL, email VARCHAR UNIQUE NOT NULL, address VARCHAR)` | **0.31** | Schema half + 3 of 4 constraints |
| 2 | `CREATE TABLE orders (id SERIAL, customer_id INT REFERENCES customers, order_date TIMESTAMP, amount DECIMAL, status VARCHAR)` | **0.50** | Schema full. **Note `TIMESTAMP` + `DECIMAL`** — the lossless type choices that won run 2 |
| 3 | `INSERT INTO customers (name, email, address) SELECT DISTINCT name, email, address FROM user_orders` | 0.50 | **Errored**: `column "name" does not exist` (the source columns are `customer_name`, etc.) |
| 4 | `… SELECT DISTINCT customer_name, customer_email, customer_address …` | 0.50 | Recovered, 200 customers inserted |
| 5 | `INSERT INTO orders (customer_id, order_date, amount, status) SELECT c.id, u.order_date, u.amount, u.status FROM user_orders u JOIN customers c ON u.customer_email = c.email` | **0.75** | **+0.25** = full data sub-rubric |
| 6 | `CREATE VIEW user_orders_view AS SELECT c.id AS customer_id, c.name, c.email, c.address, o.order_date, o.amount, o.status FROM customers c JOIN orders o ON c.id = o.customer_id` | **0.92** | View earns +0.17, **not the full +0.25** — env auto-done at threshold 0.85 |

### Sub-rubric reconstruction

The grader (`server/tasks/schema_migration.py`) is fully
deterministic — I read it carefully to rule out the "flaky spot-check"
hypothesis from earlier run notes. Specifically:

- `setup()` caches the first 10 `user_orders` rows via
  `ORDER BY row_id LIMIT 10` (lines 92–95). No `random.sample`, no
  RNG, no per-run variation.
- `_grade_data` joins each cached tuple back via a literal
  `c.name = %s AND c.email = %s AND o.order_date = %s AND o.amount = %s AND o.status = %s`
  query — the same 10 rows are checked every run.
- `_grade_view` requires the *exact column-name set*
  `_REQUIRED_VIEW_COLUMNS = {customer_name, customer_email, customer_address, order_date, amount, status}`
  (`server/tasks/schema_migration.py:40`) and uses `issubset` at
  `:369`.

So the run 3 score of 0.92 reconstructs exactly:

| Sub-rubric    | Score    | Reasoning                                                                                                            |
|---------------|---------:|----------------------------------------------------------------------------------------------------------------------|
| `schema`      | **0.25** | Both tables exist with all required columns                                                                          |
| `data`        | **0.25** | Step 5's +0.25 jump = count ✓ + distinct ✓ + 10/10 spot-checks ✓ (TIMESTAMP+DECIMAL preserved type fidelity)         |
| `constraints` | **0.25** | FK ✓, UNIQUE email ✓, NOT NULL name ✓, NOT NULL email ✓                                                              |
| `view`        | **0.17** | view exists +0.08, row count matches +0.09, **column-set check fails −0.08**                                         |
| **total**     | **0.92** |                                                                                                                      |

### The actual root cause

Step 6's `CREATE VIEW` exposes the columns as `name`, `email`,
`address` — *not* `customer_name`, `customer_email`,
`customer_address`. The grader's `issubset` check sees three of the
six required column names missing and skips the +0.08.

Run 2's mini, on the same task, must have aliased them correctly
(`c.name AS customer_name`, etc.) or selected the prefixed names
straight from `user_orders`. Run 3's mini just forgot. **Same model,
same prompt, same grader, different SQL emitted.** That is the entire
0.08 delta.

This is a real and useful finding: the medium task is
*grader-deterministic* but *model-stochastic*, and the column-name
aliasing is a sharp edge that mini sometimes trips on. It corrects
the run-1 note's hypothesis (`SERIAL`-vs-`row_id` identity mismatch)
*and* the implicit assumption in the run-2 note that mini's success
on medium was deterministic.

### Efficiency / accuracy tradeoff

Notice that this run took **6 steps** on medium vs run 2's 8 steps.
Mini errored only once here (vs twice in run 2) and skipped the
explicit `SELECT * FROM user_orders LIMIT 5` discovery step. It was
*more* efficient — and that efficiency is part of why it fumbled the
view aliasing. With one fewer round trip looking at the actual
column names of `user_orders`, the model didn't get the
`customer_name`/`customer_email`/`customer_address` strings in front
of itself often enough to remember they had to appear in the view.
The discovery step in run 2 was the thing that primed the right
aliasing.

---

## Task 3 — Performance Diagnosis (hard) — 0.917

| # | Action | Reward | Note |
|---|--------|-------:|------|
| 1 | `EXPLAIN ANALYZE SELECT * FROM events WHERE user_id = 42` | 0.00 | Discovery: Seq Scan |
| 2 | `CREATE INDEX idx_events_user_id ON task_schema.events (user_id)` | 0.12 | indexes: half |
| 3 | `CREATE INDEX idx_events_event_type ON task_schema.events (event_type)` | 0.25 | indexes: full |
| 4 | `SELECT pid, application_name, state, query FROM pg_stat_activity WHERE state = 'idle in transaction'` | 0.25 | Discovery: blocker pid=140 |
| 5 | `SELECT pg_terminate_backend(140)` | 0.50 | blocker: full |
| 6 | `VACUUM FULL task_schema.bloated_logs` | 0.75 | bloat: full (size branch) |
| 7 | `ALTER SYSTEM SET work_mem = '4MB'; SELECT pg_reload_conf()` | 0.75 | gucs: 1/3 (~0.083) — multi-statement bundle |
| 8 | `ALTER SYSTEM SET random_page_cost = '2.0'; SELECT pg_reload_conf()` | **0.92** | gucs: 2/3 (~0.167) — env auto-done at threshold |

This is **identical** to run 2's hard task — same eight steps, same
order, same multi-statement `ALTER SYSTEM …; SELECT pg_reload_conf();`
bundling, same auto-done at 0.92 after the second GUC, same
unattempted third GUC (`effective_cache_size`). Two runs in, mini's
hard-task strategy is deterministically reproducible, and the
auto-done ceiling is the *only* thing keeping it from a perfect
score.

This datapoint cleanly motivates the recommendation from the run-2
note: bumping hard's `SUCCESS_THRESHOLD` would let mini reach 1.0
without changing the agent or the prompt at all.

---

## Run-over-run variance findings

| Source of variance              | Easy                | Medium                                | Hard                              |
|---------------------------------|---------------------|---------------------------------------|-----------------------------------|
| Grader RNG                      | none                | **none** (verified — `ORDER BY row_id LIMIT 10`) | none                  |
| Timing jitter (shaped reward)   | ±0.03 on diagnostic | none on final score                   | none on final score               |
| Model output stochasticity      | none observed       | **±0.08** (column-alias forget run 3) | none observed across two mini runs |
| Auto-done ceiling               | n/a                 | n/a (always crosses cleanly)          | **caps mini at 0.917**            |

The medium task's run-to-run variance is **entirely model-side**:
same prompt, same grader, different SQL emitted on a single
`CREATE VIEW` line. That is a benchmark-quality concern: two runs of
the same model on the same task disagreeing by 0.08 reward means any
A/B comparison on the medium task needs more than one trial per
model.

### Why this finding matters more than it looks

The run-2 note framed the gpt-4o vs gpt-4o-mini comparison as "mini
beats 4o by 0.05 aggregate" — a real and surprising signal. Run 3
shows that mini's *own* run-to-run variance on medium (0.08) is
**larger than the gap mini opened up over 4o** (0.05). One trial per
model is not enough to distinguish two models that are this close.
This doesn't invalidate the run-2 conclusion — mini's `TIMESTAMP`
type choice was correct on both runs and that's the thing that
beat 4o's `DATE` truncation — it just means the *aggregate* number
needs error bars before you can lean on it.

---

## Code change made in this run

Bumped `SUCCESS_THRESHOLD` from `0.85` to `0.95` in
`server/tasks/performance_diagnosis.py:133`. This lets the hard task
keep running after mini reaches 0.92 with two GUCs fixed, instead of
the env auto-flipping `done=true` and capping the score. The
expectation is that mini's next hard run finishes the third
`ALTER SYSTEM` + reload and lands a perfect 1.0. Easy and medium
keep their 0.85 threshold — neither has a "ceiling" problem and
their shaped rewards are friendlier to early termination.

No changes to task description prompts.

---

## What I'd watch on the next run

1. **Re-run hard with the new 0.95 threshold** and verify mini gets a
   ninth step in to set `effective_cache_size` and reload, taking
   the score to 1.0. If it doesn't, that means mini's stop condition
   isn't actually score-driven — it might be using `done` from the
   env or hitting some other early-exit path. Either way, useful to
   know.
2. **Run medium 3–5 more times** with the same model and seed to
   measure how often the column-alias miss happens. If it's a coin
   flip, the run-2 perfect 1.0 was lucky and the run-3 0.92 is
   actually closer to mini's expected score. If run 3 is the
   outlier, the perfect score is the steady state.
3. **Watch easy's diagnostic-step shaped reward** (0.04 → 0.05 →
   0.07 across three runs). If it keeps drifting upward, the
   `speedup_score` formula is leaking measurable noise into the
   early-step rewards that the run-1 note already flagged as worth
   zeroing out.

---

## tl;dr

`gpt-4o-mini` ran the gym a second time and scored **2.837 / 3.0**,
*lower* than its previous run (2.917). Easy and hard are stable
across both runs (1.0 and 0.917 respectively, the latter still
capped by the `SUCCESS_THRESHOLD = 0.85` auto-done). The whole
delta is in medium, where mini's `CREATE VIEW` aliased the columns
as `name`/`email`/`address` instead of `customer_name`/
`customer_email`/`customer_address`, missing the grader's
`_REQUIRED_VIEW_COLUMNS` subset check by exactly 0.08. The grader
itself is fully deterministic — confirmed by reading
`server/tasks/schema_migration.py`. The variance is on the model
side, and it's larger than the gap between gpt-4o and gpt-4o-mini
in the run-2 comparison, so any future model-vs-model claims on
this benchmark need more than one trial each. To address the
hard-task ceiling I bumped
`server/tasks/performance_diagnosis.py:133`'s `SUCCESS_THRESHOLD`
from `0.85` to `0.95`; the next hard run should be able to reach
1.0 by completing the third GUC.
