# Twenty-second end-to-end `inference.py` run — annotated (Qwen2.5-72B-Instruct, cross-model analysis)

Date: 2026-04-09
Model: `Qwen/Qwen2.5-72B-Instruct`
Final scores: `{"easy": 0.990, "medium": 0.615, "hard": 0.990, "expert": 0.990, "master": 0.990}`
Aggregate: **4.575 / 5.0**

Third and final Qwen run. Expert finally succeeds (4 steps, 0.990)
because the model uses `id` (correct PK column) instead of `customer_id`.
With correct SQL, the `BEGIN; … COMMIT;` wrapping works fine — the
environment bug only triggers when an error occurs inside an explicit
transaction. Medium still fails at 0.615 with the same `o.row_id`
hallucination as Run 21.

---

## Headline — twenty-two runs side by side

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
| 20  | Qwen2.5-72B-Instruct        | 0.990 |  0.865 | 0.990 |  0.010 |  0.010 | 2.865 / 5.0     |
| 21  | Qwen2.5-72B-Instruct        | 0.990 |  0.615 | 0.990 |  0.010 |  0.010 | 2.615 / 5.0     |
| **22** | **Qwen2.5-72B-Instruct** | 0.990 |  0.615 | 0.990 |  **0.990** | **0.990** | **4.575 / 5.0** |

---

## Per-task analysis

### easy — index optimization (score: 0.990, 2 steps)

Identical to Runs 20–21.

### medium — schema migration (score: 0.615, 12 steps) — FAILED

Same failure pattern as Run 21: 6-step column-name retry loop →
`information_schema` introspection at step 9 → correct inserts →
`CREATE VIEW … o.row_id …` → error + `done=true`. The view column
hallucination (`o.row_id` instead of `o.id AS row_id`) is now
reproducible across 2 of 3 runs.

### hard — performance diagnosis (score: 0.990, 6 steps)

This run shows the model's **efficient mode**: indexes and GUCs are
combined into multi-statement steps.

| Step | Action | Reward |
|------|--------|--------|
| 1 | `EXPLAIN ANALYZE SELECT * FROM events WHERE user_id = 42` | 0.01 |
| 2 | `CREATE INDEX … (user_id); CREATE INDEX … (event_type)` | 0.25 |
| 3 | `SELECT pid, … FROM pg_stat_activity …` | 0.25 |
| 4 | `SELECT pg_terminate_backend(101)` | 0.50 |
| 5 | `VACUUM FULL task_schema.bloated_logs` | 0.75 |
| 6 | `ALTER SYSTEM SET work_mem = '4MB'; ALTER SYSTEM SET random_page_cost = '2.0'; ALTER SYSTEM SET effective_cache_size = '512MB'; SELECT pg_reload_conf()` | 0.99 |

**6 steps vs 9 steps** in Runs 20–21. The model non-deterministically
chooses between individual-step and batched approaches. The 6-step
version matches Gemma 27B's efficiency (though Gemma does it in 5 by
also combining indexes + GUCs).

### expert — backup & recovery (score: 0.990, 4 steps) — SUCCESS

The critical difference from Runs 20–21: the model uses `id` (correct)
instead of `customer_id` (hallucinated).

| Step | Action | Reward | Notes |
|------|--------|--------|-------|
| 1 | `BEGIN; INSERT INTO customers (SELECT * FROM backup_customers WHERE id NOT IN (SELECT id FROM customers)); COMMIT;` | 0.46 | `id` — correct column! |
| 2 | `BEGIN; INSERT INTO orders (SELECT * FROM backup_orders WHERE id NOT IN (SELECT id FROM orders)); COMMIT;` | 0.71 | Both tables use `id` |
| 3 | `BEGIN; CREATE TABLE audit_log AS SELECT * FROM backup_audit_log; COMMIT;` | 0.96 | |
| 4 | `UPDATE customers SET balance = bc.balance FROM backup_customers bc WHERE customers.id = bc.id AND customers.balance = 0.00` | 0.99 | No `BEGIN` wrapper here |

The `BEGIN; … COMMIT;` wrapping works perfectly when the SQL is correct
— the environment only breaks when an error occurs inside the explicit
transaction. This confirms the attribution: the model's `BEGIN` habit
is harmless in isolation; the environment bug is what makes it
catastrophic on failure.

Note: the model uses `WHERE id NOT IN (SELECT id FROM …)` — a
`NOT IN` subquery — rather than `ON CONFLICT DO NOTHING` or
`NOT EXISTS`. Functionally correct but `NOT IN` has a known caveat
with NULLs (returns empty set if any `id` in the subquery is NULL).

### master — security audit (score: 0.990, 4 steps)

Standard 4-step solve. Password: `securepassword123`.

---

## Qwen2.5-72B-Instruct: three-run summary

| Task   | Run 20 | Run 21 | Run 22 | Mean  | Std   | Verdict |
|--------|--------|--------|--------|-------|-------|---------|
| easy   | 0.990  | 0.990  | 0.990  | 0.990 | 0.000 | Reliable pass |
| medium | 0.865  | 0.615  | 0.615  | 0.698 | 0.118 | **Unstable** — view column hallucination |
| hard   | 0.990  | 0.990  | 0.990  | 0.990 | 0.000 | Reliable pass |
| expert | 0.010  | 0.010  | 0.990  | 0.337 | 0.462 | **Extremely volatile** — env bug amplifies |
| master | 0.010  | 0.010  | 0.990  | 0.337 | 0.462 | Mirrors expert (poisoned in 2/3 runs) |
| **agg**| 2.865  | 2.615  | 4.575  | **3.352** | 0.873 | |

### Adjusted scores (if environment bug were fixed)

If the environment properly cleaned up stale transactions, the model
would still fail the first INSERT on expert (wrong column name), but
would have 24 remaining steps to recover. Estimating conservatively
(no guarantee the model would introspect):

| Task   | Run 20 adj | Run 21 adj | Run 22 | Mean adj | Notes |
|--------|-----------|-----------|--------|----------|-------|
| expert | 0.010–0.990 | 0.010–0.990 | 0.990 | — | Depends on recovery |
| master | 0.990     | 0.990     | 0.990  | 0.990 | Would not be poisoned |

Conservative lower bound (expert still fails but master recovers):
Mean agg ≥ (2.865 + 0.98) + (2.615 + 0.98) + 4.575) / 3 = **3.972**

This suggests the environment bug costs Qwen roughly **0.6 aggregate
points** on average.

---

## Qwen's unique behavioral patterns

### 1. `BEGIN; … COMMIT;` wrapping

Qwen is the **only model** that wraps individual actions in explicit
transaction blocks. All other tested models send raw SQL statements and
rely on the connection's autocommit mode.

| Model | Expert step 1 pattern |
|-------|-----------------------|
| Qwen 72B | `BEGIN; INSERT … ON CONFLICT …; COMMIT;` |
| Gemma 27B | `INSERT INTO customers SELECT * FROM backup_customers WHERE customer_id NOT IN …` |
| Llama 70B | `INSERT INTO customers SELECT * FROM backup_customers ON CONFLICT DO NOTHING` |
| gpt-4o-mini | `INSERT INTO customers SELECT * FROM backup_customers ON CONFLICT (id) DO NOTHING` |

This suggests Qwen was trained on examples that use explicit transaction
control, possibly from enterprise database documentation or DBA tutorials
where transactions are standard practice. While technically correct SQL
practice, it interacts badly with the environment's connection pooling.

### 2. Non-deterministic batching

The model inconsistently chooses between individual-step and
multi-statement approaches:

| Task | Run 20 | Run 21 | Run 22 |
|------|--------|--------|--------|
| hard indexes | 2 steps (separate) | 2 steps (separate) | 1 step (combined) |
| hard GUCs | 3 steps (separate) | 3 steps (separate) | 1 step (combined) |
| hard total | 9 steps | 9 steps | 6 steps |

Run 22 batches more aggressively — the same model can solve hard in
6 or 9 steps depending on the sampling path.

### 3. Medium: correct alias is fragile

The `CREATE VIEW` step shows the model's understanding of column
mapping is unstable:
- Run 20: `o.id AS row_id` → correct (0.865)
- Run 21: `o.row_id` → hallucinated column (0.615)
- Run 22: `o.row_id` → hallucinated column (0.615)

The 2/3 failure rate on this specific column reference is the primary
variance source for medium (excluding expert/master env-bug effects).

---

## Model tier ranking (final, all 22 runs)

| Tier | Model                        | Runs | Agg range       | Mean agg | Variance source |
|------|------------------------------|------|-----------------|----------|-----------------|
| S    | gpt-4o-mini                  | 5    | 4.880 – 5.000   | 4.932    | Medium (0.920–1.000) |
| A    | Gemma-3-27B-IT               | 3    | 4.795 – 4.825   | 4.815    | Expert (0.960–0.990) |
| A    | Llama-3.3-70B-Instruct       | 3    | 4.745 – 4.825   | 4.798    | Medium (0.785–0.865) |
| A-   | gpt-3.5-turbo                | 3    | 4.460 – 4.865   | 4.595    | Medium (0.500–0.865) |
| B*   | Qwen2.5-72B-Instruct         | 3    | 2.615 – 4.575   | 3.352    | Expert/master env-bug (0.010–0.990) |
| B    | gpt-4o                       | 1    | 2.865 (3 tasks) | —        | Incomplete data |
| C    | Llama-3.1-8B-Instruct        | 3    | 2.900 – 3.530   | 3.283    | Format + medium + expert |

*\*Qwen's B tier is heavily influenced by the environment bug. With the
fix applied, the model would likely rank A- to A (estimated adjusted
mean ~3.97–4.58).*

### Raw score vs environment-adjusted ranking

| Model | Raw mean agg | Environment-adjusted estimate | True tier |
|-------|-------------|------------------------------|-----------|
| Gemma-3-27B-IT | 4.815 | 4.815 (no env issues) | A |
| Llama-3.3-70B-Instruct | 4.798 | 4.798 (no env issues) | A |
| Qwen2.5-72B-Instruct | 3.352 | ~3.97–4.58 | **A- (estimated)** |
| Llama-3.1-8B-Instruct | 3.283 | 3.283 (no env issues) | C |

### Parameter efficiency (open models only)

| Model | Parameters | Raw mean agg | Env-adjusted | Best single run |
|-------|-----------|-------------|-------------|-----------------|
| Gemma-3-27B-IT | 27B | 4.815 | 4.815 | 4.825 |
| Qwen2.5-72B-Instruct | 72B | 3.352 | ~4.28 | 4.575 |
| Llama-3.3-70B-Instruct | 70B | 4.798 | 4.798 | 4.825 |
| Llama-3.1-8B-Instruct | 8B | 3.283 | 3.283 | 3.530 |

Qwen's best single run (4.575) is competitive with Llama 70B's worst
(4.745) but falls short of its mean (4.798). The medium-task view
hallucination — a pure model issue unrelated to the environment bug —
is the differentiator.

---

## Environment improvement: stale transaction cleanup

### Root cause

`borrow_connection()` in `server/db.py` skips `conn.rollback()` when
`autocommit=True`. If the agent issues `BEGIN` and an error occurs
before `COMMIT`, the connection returns to the pool with
`TRANSACTION_STATUS_INERROR`. All future borrows of that connection fail.

### Impact across all runs

| Run | Expert approach | Transaction error? | Expert score | Master score |
|-----|----------------|-------------------|-------------|-------------|
| 20 | `BEGIN; … ON CONFLICT (customer_id) …; COMMIT;` | Yes → stale txn | 0.010 | 0.010 (poisoned) |
| 21 | Same | Yes → stale txn | 0.010 | 0.010 (poisoned) |
| 22 | `BEGIN; … WHERE id NOT IN …; COMMIT;` | No (SQL correct) | 0.990 | 0.990 |

### Fix

Check `conn.get_transaction_status()` in the `finally` block and force
a rollback for stale transactions, even in autocommit mode. See the
applied fix in `server/db.py`.

---

## Key takeaways

1. **Qwen 72B is competitive but fragile.** Its best run (4.575)
   approaches A-tier, but two catastrophic failures drag the mean to
   3.352. The environment bug is the primary cause, but medium
   instability (0.615–0.865) is also a factor.

2. **`BEGIN;…COMMIT;` wrapping is a model-specific risk.** No other
   tested model uses explicit transactions. This habit is harmless
   when SQL is correct, but interacts catastrophically with the
   environment's connection pooling when errors occur.

3. **The environment needs hardening.** The stale transaction bug
   should never have allowed a single wrong column name to cascade
   into multi-task, multi-run failures. The fix (transaction status
   check in `borrow_connection`) is straightforward.

4. **View column hallucination is Qwen's medium-task weakness.**
   `o.row_id` (non-existent) vs `o.id AS row_id` (correct) is a
   single-token difference that causes a 0.25-point score swing.
   Combined with premature `done=true`, the model gets no chance
   to self-correct.

5. **Gemma 27B remains the most parameter-efficient open model.**
   At 27B parameters, it achieves a higher and more consistent
   aggregate (4.815) than both 70B+ models (Qwen 3.352 raw,
   Llama 70B 4.798).

---

## Raw log output

```
[START] task=easy env=postgres_dba_gym model=Qwen/Qwen2.5-72B-Instruct
[STEP] step=1 action=EXPLAIN (ANALYZE, BUFFERS) ... reward=0.07 done=false error=null
[STEP] step=2 action=CREATE INDEX ... reward=0.99 done=true error=null
[END] success=true steps=2 score=0.990 rewards=0.07,0.99
[START] task=medium env=postgres_dba_gym model=Qwen/Qwen2.5-72B-Instruct
[STEP] step=1 action=CREATE TABLE customers (…) reward=0.31
[STEP] step=2 action=CREATE TABLE orders (…) reward=0.50
[STEP] step=3–8 (column name retry loop × 6) reward=0.50 error=column "name" does not exist
[STEP] step=9 action=SELECT column_name FROM information_schema.columns ... reward=0.50
[STEP] step=10 action=INSERT INTO customers ... customer_name ... reward=0.50
[STEP] step=11 action=INSERT INTO orders ... reward=0.61
[STEP] step=12 action=CREATE VIEW ... o.row_id ... reward=0.61 done=true error=column o.row_id does not exist
[END] success=false steps=12 score=0.615 rewards=0.31,0.50,0.50,0.50,0.50,0.50,0.50,0.50,0.50,0.50,0.61,0.61
[START] task=hard env=postgres_dba_gym model=Qwen/Qwen2.5-72B-Instruct
[STEP] step=1 action=EXPLAIN ANALYZE ... reward=0.01
[STEP] step=2 action=CREATE INDEX (user_id); CREATE INDEX (event_type); reward=0.25
[STEP] step=3 action=SELECT pid ... pg_stat_activity ... reward=0.25
[STEP] step=4 action=SELECT pg_terminate_backend(101); reward=0.50
[STEP] step=5 action=VACUUM FULL task_schema.bloated_logs; reward=0.75
[STEP] step=6 action=ALTER SYSTEM SET work_mem = '4MB'; ALTER SYSTEM SET random_page_cost = '2.0'; ALTER SYSTEM SET effective_cache_size = '512MB'; SELECT pg_reload_conf(); reward=0.99 done=true
[END] success=true steps=6 score=0.990 rewards=0.01,0.25,0.25,0.50,0.75,0.99
[START] task=expert env=postgres_dba_gym model=Qwen/Qwen2.5-72B-Instruct
[STEP] step=1 action=BEGIN; INSERT INTO customers (SELECT * FROM backup_customers WHERE id NOT IN (SELECT id FROM customers)); COMMIT; reward=0.46 error=null
[STEP] step=2 action=BEGIN; INSERT INTO orders (SELECT * FROM backup_orders WHERE id NOT IN (SELECT id FROM orders)); COMMIT; reward=0.71 error=null
[STEP] step=3 action=BEGIN; CREATE TABLE audit_log AS SELECT * FROM backup_audit_log; COMMIT; reward=0.96 error=null
[STEP] step=4 action=UPDATE customers SET balance = bc.balance FROM backup_customers bc WHERE customers.id = bc.id AND customers.balance = 0.00; reward=0.99 done=true error=null
[END] success=true steps=4 score=0.990 rewards=0.46,0.71,0.96,0.99
[START] task=master env=postgres_dba_gym model=Qwen/Qwen2.5-72B-Instruct
[STEP] step=1 action=ALTER ROLE analytics_user NOSUPERUSER; reward=0.25
[STEP] step=2 action=REVOKE CREATE ON SCHEMA public FROM PUBLIC; reward=0.50
[STEP] step=3 action=REVOKE SELECT ON task_schema.salaries FROM readonly_user; reward=0.75
[STEP] step=4 action=ALTER ROLE intern_user WITH PASSWORD 'securepassword123'; reward=0.99 done=true
[END] success=true steps=4 score=0.990 rewards=0.25,0.50,0.75,0.99
```
