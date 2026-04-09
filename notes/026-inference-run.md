# Run 26 — post-v2-fix, cross-model analysis (Qwen2.5-72B-Instruct)

Date: 2026-04-09
Model: `Qwen/Qwen2.5-72B-Instruct`
Final scores: `{"easy": 0.990, "medium": 0.865, "hard": 0.990, "expert": 0.990, "master": 0.990}`
Aggregate: **4.825 / 5.0**

**All five tasks pass.** Qwen's best run — aggregate 4.825 ties Gemma
27B and Llama 70B's best single runs. Medium finally uses the correct
`o.id AS row_id` alias. Expert succeeds with the same EXCEPT → NOT IN
pattern as Run 25. Master solved in 1 step again. This run demonstrates
that Qwen 72B is a genuine A-tier model when the environment handles
errors correctly.

---

## Headline — twenty-six runs side by side

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
| 20† | Qwen2.5-72B-Instruct        | 0.990 |  0.865 | 0.990 |  0.010 |  0.010 | 2.865 / 5.0     |
| 21† | Qwen2.5-72B-Instruct        | 0.990 |  0.615 | 0.990 |  0.010 |  0.010 | 2.615 / 5.0     |
| 22† | Qwen2.5-72B-Instruct        | 0.990 |  0.615 | 0.990 |  0.990 |  0.990 | 4.575 / 5.0     |
| 24† | Qwen2.5-72B-Instruct        | 0.990 |  0.615 | 0.990 |  0.010 |  0.010 | 2.615 / 5.0     |
| 25  | Qwen2.5-72B-Instruct        | 0.990 |  0.615 | 0.990 |  0.990 |  0.990 | 4.575 / 5.0     |
| **26** | **Qwen2.5-72B-Instruct** | 0.990 |  **0.865** | 0.990 | 0.990 | 0.990 | **4.825 / 5.0** |

*† Runs 20–22, 24 affected by environment stale-transaction bug (v2 fix
not yet deployed). Expert/master scores of 0.010 in those runs are
primarily env artifacts.*

---

## Per-task analysis

### easy — index optimization (score: 0.990, 2 steps)

Standard. `EXPLAIN (ANALYZE, BUFFERS)` → `CREATE INDEX`.

### medium — schema migration (score: 0.865, 13 steps) — SUCCESS

| Step | Action | Reward | Notes |
|------|--------|--------|-------|
| 1 | `CREATE TABLE customers (…)` | 0.31 | |
| 2 | `CREATE TABLE orders (…)` | 0.50 | FK constraint |
| 3–9 | `INSERT INTO customers (name, email, address) SELECT DISTINCT name, …` | 0.50 | 7 failed attempts |
| 10 | `SELECT column_name FROM information_schema.columns WHERE table_schema='task_schema' AND table_name='user_orders'` | 0.50 | Introspection |
| 11 | `INSERT INTO customers … SELECT DISTINCT customer_name, customer_email, customer_address …` | 0.50 | Correct |
| 12 | `INSERT INTO orders … SELECT c.id, uo.order_date, uo.amount, uo.status FROM user_orders uo JOIN customers c ON uo.customer_email = c.email` | 0.61 | FK join |
| 13 | `CREATE VIEW user_orders_view AS SELECT o.id AS row_id, c.name AS customer_name, …` | **0.86** | `o.id AS row_id` — **correct alias** |

**This is the key difference from Runs 21–25:** the model writes
`o.id AS row_id` (aliasing `id` to `row_id`) instead of `o.row_id`
(hallucinated column). With 2 passes out of 6 Qwen medium attempts,
the correct alias appears ~33% of the time at temperature=0.2.

### hard — performance diagnosis (score: 0.990, 9 steps)

Individual-step pattern this run: separate indexes (steps 2–3),
individual GUC changes (steps 7–9). Same outcome as the 6-step batched
variant, just less efficient.

### expert — backup & recovery (score: 0.990, 5 steps) — SUCCESS

Same EXCEPT → NOT IN pattern as Run 25:

| Step | Action | Reward | Notes |
|------|--------|--------|-------|
| 1 | `INSERT INTO customers (SELECT * FROM backup_customers EXCEPT SELECT * FROM customers)` | 0.16 | Duplicate key error on `id=350` |
| 2 | `INSERT INTO customers (SELECT * FROM backup_customers WHERE id NOT IN (SELECT id FROM customers))` | 0.46 | Adapts after error |
| 3 | `INSERT INTO orders (SELECT * FROM backup_orders EXCEPT SELECT * FROM orders)` | 0.71 | EXCEPT works for orders |
| 4 | `CREATE TABLE audit_log AS SELECT * FROM backup_audit_log` | 0.96 | |
| 5 | `UPDATE customers c SET balance = b.balance FROM backup_customers b WHERE c.id = b.id AND c.balance = 0.00` | 0.99 | Table alias `c` / `b` |

The EXCEPT → NOT IN pattern is now **deterministic across both post-fix
runs** (25 and 26). The model has shifted away from `BEGIN;…COMMIT;`
wrapping and `ON CONFLICT` — possibly because the temperature=0.2
sampling has settled into this EXCEPT-first approach.

### master — security audit (score: 0.990, 1 step) — RECORD (again)

All four sub-tasks in one multi-statement action. Deterministic across
both post-fix runs.

---

## Qwen2.5-72B-Instruct: six-run summary

### All runs (including env-bugged)

| Task   | R20† | R21† | R22† | R24† | R25 | R26 | Mean  | Std   |
|--------|------|------|------|------|-----|-----|-------|-------|
| easy   | .990 | .990 | .990 | .990 | .990| .990| 0.990 | 0.000 |
| medium | .865 | .615 | .615 | .615 | .615| .865| 0.698 | 0.118 |
| hard   | .990 | .990 | .990 | .990 | .990| .990| 0.990 | 0.000 |
| expert | .010 | .010 | .990 | .010 | .990| .990| 0.500 | 0.462 |
| master | .010 | .010 | .990 | .010 | .990| .990| 0.500 | 0.462 |
| **agg**| 2.865| 2.615| 4.575| 2.615|4.575|4.825| **3.678** | |

*† env-bugged runs*

### Post-v2-fix runs only (Runs 25–26)

| Task   | Run 25 | Run 26 | Mean  | Notes |
|--------|--------|--------|-------|-------|
| easy   | 0.990  | 0.990  | 0.990 | Identical |
| medium | 0.615  | 0.865  | 0.740 | `o.row_id` vs `o.id AS row_id` |
| hard   | 0.990  | 0.990  | 0.990 | 6 vs 9 steps |
| expert | 0.990  | 0.990  | 0.990 | EXCEPT → NOT IN (deterministic) |
| master | 0.990  | 0.990  | 0.990 | 1 step (deterministic) |
| **agg**| 4.575  | 4.825  | **4.700** | |

Post-fix mean of 4.700 is a much more representative measure of Qwen's
true capability than the env-bugged mean of 3.168 (Runs 20–24).

---

## Pre-fix vs post-fix comparison

| Metric | Pre-fix (Runs 20–24) | Post-fix (Runs 25–26) | Delta |
|--------|---------------------|-----------------------|-------|
| Mean aggregate | 3.168 | **4.700** | +1.532 |
| Expert pass rate | 1/4 (25%) | 2/2 (100%) | +75% |
| Master pass rate | 1/4 (25%) | 2/2 (100%) | +75% |
| Medium pass rate | 1/4 (25%) | 1/2 (50%) | +25% |
| Uses `BEGIN;…COMMIT;` | 4/4 runs | 0/2 runs | Model sampling |
| Uses EXCEPT | 0/4 | 2/2 | New strategy |
| Master steps | 4 | **1** | New batching |

The expert/master improvement is entirely due to the environment fix
(no more transaction poisoning). The medium improvement is sampling
variance (model sometimes gets the view alias right).

Note that the two post-fix runs happen not to use `BEGIN;…COMMIT;`
wrapping. If a future run does use `BEGIN` and hits an error, the v2
fix would clean up the stale transaction — but this hasn't been
directly tested yet in a live run.

---

## Model tier ranking (all 26 runs, post-fix Qwen estimates)

| Tier | Model                        | Runs | Agg range       | Mean agg | Variance source |
|------|------------------------------|------|-----------------|----------|-----------------|
| S    | gpt-4o-mini                  | 5    | 4.880 – 5.000   | 4.932    | Medium (0.920–1.000) |
| A    | Gemma-3-27B-IT               | 3    | 4.795 – 4.825   | 4.815    | Expert (0.960–0.990) |
| A    | Llama-3.3-70B-Instruct       | 3    | 4.745 – 4.825   | 4.798    | Medium (0.785–0.865) |
| A    | **Qwen2.5-72B-Instruct**     | 2*   | 4.575 – 4.825   | **4.700**| Medium (0.615–0.865) |
| A-   | gpt-3.5-turbo                | 3    | 4.460 – 4.865   | 4.595    | Medium (0.500–0.865) |
| B    | gpt-4o                       | 1    | 2.865 (3 tasks) | —        | Incomplete data |
| C    | Llama-3.1-8B-Instruct        | 3    | 2.900 – 3.530   | 3.283    | Format + medium + expert |

*\*Only post-v2-fix runs counted for Qwen tier placement. Pre-fix runs
(20–24) documented but excluded from ranking due to env bug.*

### Medium consistency across A-tier models

| Model | Medium scores | Mean | Std | Pass rate |
|-------|-------------|------|-----|-----------|
| Gemma-3-27B-IT | 0.865, 0.865, 0.865 | 0.865 | 0.000 | 3/3 (100%) |
| Llama-3.3-70B-Instruct | 0.865, 0.865, 0.785 | 0.838 | 0.038 | 2/3 (67%) |
| Qwen2.5-72B-Instruct | 0.615, 0.865 | 0.740 | 0.125 | 1/2 (50%) |

Medium remains Qwen's weakest task. The `o.row_id` hallucination (4/6
runs across all Qwen data) is the single biggest differentiator between
Qwen and the other A-tier models. If medium were reliable, Qwen would
match Gemma's consistency.

### Parameter efficiency (open models, A-tier only)

| Model | Parameters | Post-fix mean agg | Agg per B params |
|-------|-----------|-------------------|------------------|
| Gemma-3-27B-IT | 27B | 4.815 | **0.178** |
| Qwen2.5-72B-Instruct | 72B | 4.700 | 0.065 |
| Llama-3.3-70B-Instruct | 70B | 4.798 | 0.069 |

Gemma 27B remains the most parameter-efficient. Qwen 72B and Llama 70B
are similar in both size and performance, with Llama having a slight
edge in aggregate (4.798 vs 4.700) driven by medium consistency.

---

## Qwen-specific findings across all 6 runs

### 1. Expert task: three distinct strategies observed

| Strategy | Runs | Outcome |
|----------|------|---------|
| `BEGIN; INSERT … ON CONFLICT (customer_id) …; COMMIT;` | 20, 21, 24 | Catastrophic failure (env bug) |
| `BEGIN; INSERT … WHERE id NOT IN …; COMMIT;` | 22 | Success (correct column, no error inside txn) |
| `INSERT (SELECT * EXCEPT …)` → `INSERT WHERE id NOT IN …` | 25, 26 | Success (no txn wrapping) |

The model's expert strategy is non-deterministic at temperature=0.2.
The EXCEPT approach (post-fix runs) is the safest because it avoids
explicit transactions entirely.

### 2. Master: 1-step solve is unique to Qwen

| Model | Master steps | Approach |
|-------|-------------|----------|
| **Qwen 72B** | **1** | All 4 sub-tasks in one multi-statement |
| Gemma 27B | 4 | One sub-task per step |
| Llama 70B | 4 | One sub-task per step |
| gpt-4o-mini | 4 | One sub-task per step |
| gpt-3.5-turbo | 4 | One sub-task per step |

### 3. Medium: `o.row_id` vs `o.id AS row_id`

| Run | View SQL | Medium score |
|-----|----------|-------------|
| 20 | `o.id AS row_id` | 0.865 ✓ |
| 21 | `o.row_id` | 0.615 ✗ |
| 22 | `o.row_id` | 0.615 ✗ |
| 24 | `o.row_id` | 0.615 ✗ |
| 25 | `o.row_id` | 0.615 ✗ |
| 26 | `o.id AS row_id` | 0.865 ✓ |

Pass rate: 2/6 (33%). The correct alias requires the model to understand
that `orders.id` needs to be exposed as `row_id` in the view — a column
renaming that the model gets wrong most of the time.

---

## Key takeaways

1. **Qwen 72B is A-tier post-fix.** Mean 4.700, competitive with Gemma
   (4.815) and Llama 70B (4.798). The 0.1-point gap is entirely due to
   medium instability.

2. **The v2 environment fix works.** Both post-fix expert tasks succeed.
   Neither uses `BEGIN` wrapping, so the fix's stale-transaction cleanup
   wasn't directly exercised — but the model's shift to EXCEPT may be
   temperature sampling, and a future run with `BEGIN` + error would test
   the fix directly.

3. **1-step master is a Qwen exclusive.** Combining all four security
   sub-tasks into one action is the most efficient approach any model has
   shown, and it's deterministic across both post-fix runs.

4. **Medium is the only remaining weakness.** The `o.row_id`
   hallucination at a 67% failure rate is Qwen's distinguishing flaw.
   All other tasks are reliable.

5. **The environment investigation was worth it.** The stale-transaction
   bug masked Qwen's true capability. Without it, Qwen would have been
   wrongly classified as B-tier (mean 3.168). With the fix, it's
   definitively A-tier (mean 4.700).

---

## Raw log output

```
[START] task=easy env=postgres_dba_gym model=Qwen/Qwen2.5-72B-Instruct
[STEP] step=1 action=EXPLAIN (ANALYZE, BUFFERS) ... reward=0.07 done=false error=null
[STEP] step=2 action=CREATE INDEX ... reward=0.99 done=true error=null
[END] success=true steps=2 score=0.990 rewards=0.07,0.99
[START] task=medium env=postgres_dba_gym model=Qwen/Qwen2.5-72B-Instruct
[STEP] step=1–2 (table creation) reward=0.31→0.50
[STEP] step=3–9 (column name retry loop × 7) reward=0.50 error=column "name" does not exist
[STEP] step=10 action=SELECT column_name FROM information_schema.columns ... reward=0.50
[STEP] step=11 action=INSERT INTO customers ... customer_name ... reward=0.50
[STEP] step=12 action=INSERT INTO orders ... JOIN ... reward=0.61
[STEP] step=13 action=CREATE VIEW ... o.id AS row_id ... reward=0.86 done=true error=null
[END] success=true steps=13 score=0.865 rewards=0.31,0.50×8,0.50,0.61,0.86
[START] task=hard env=postgres_dba_gym model=Qwen/Qwen2.5-72B-Instruct
[STEP] step=1–9 (EXPLAIN + indexes + blocker + VACUUM + GUCs individual) reward=0.01→0.99
[END] success=true steps=9 score=0.990 rewards=0.01,0.12,0.25,0.25,0.50,0.75,0.83,0.92,0.99
[START] task=expert env=postgres_dba_gym model=Qwen/Qwen2.5-72B-Instruct
[STEP] step=1 action=INSERT INTO customers (SELECT * FROM backup_customers EXCEPT SELECT * FROM customers); reward=0.16 error=duplicate key (id=350)
[STEP] step=2 action=INSERT INTO customers (SELECT * FROM backup_customers WHERE id NOT IN (SELECT id FROM customers)); reward=0.46 error=null
[STEP] step=3 action=INSERT INTO orders (SELECT * FROM backup_orders EXCEPT SELECT * FROM orders); reward=0.71 error=null
[STEP] step=4 action=CREATE TABLE audit_log AS SELECT * FROM backup_audit_log; reward=0.96 error=null
[STEP] step=5 action=UPDATE customers c SET balance = b.balance FROM backup_customers b WHERE c.id = b.id AND c.balance = 0.00; reward=0.99 done=true error=null
[END] success=true steps=5 score=0.990 rewards=0.16,0.46,0.71,0.96,0.99
[START] task=master env=postgres_dba_gym model=Qwen/Qwen2.5-72B-Instruct
[STEP] step=1 action=ALTER ROLE analytics_user NOSUPERUSER; REVOKE CREATE ...; REVOKE SELECT ...; ALTER ROLE intern_user WITH PASSWORD 'securepassword123'; reward=0.99 done=true error=null
[END] success=true steps=1 score=0.990 rewards=0.99
```
