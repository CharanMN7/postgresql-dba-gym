# Thirteenth end-to-end `inference.py` run — annotated (Llama-3.1-8B-Instruct, cross-model analysis)

Date: 2026-04-09
Model: `meta-llama/Llama-3.1-8B-Instruct`
Final scores: `{"easy": 0.990, "medium": 0.438, "hard": 0.010, "expert": 0.990, "master": 0.990}`
Aggregate: **3.418 / 5.0**

Third and final Llama-3.1-8B run. Confirms the same pattern: easy,
expert, and master reliably pass; hard is a total loss (format issue);
medium is a total loss (column-name loop). This run also shows the
model's ability to combine multiple statements into a single step
(master solved in 1 step), but also the downside of that approach
(medium never established the FK constraint, capping reward lower).

---

## Headline — thirteen runs side by side

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

---

## Per-task analysis

### easy — index optimization (score: 0.990, 2 steps)

Identical to Runs 11–12. EXPLAIN + CREATE INDEX.

### medium — schema migration (score: 0.438, 25 steps — FAILURE)

Lowest medium score of the three Llama runs. The model combined both
CREATE TABLE statements into a single step (reward 0.44) but **skipped
the FK constraint** entirely, so it never reached the 0.50 baseline
that Runs 11–12 achieved.

Steps 2–24 were the same column-name retry loop. Step 25 hit the
8192-token context window limit — the first time medium itself
triggered the context overflow (previously only hard and medium
Run 11/12 hit the step limit naturally).

The combined-statements strategy that brilliantly solved master in
one step actively hurt medium: by packing CREATE TABLE into one step,
the model moved on to INSERT before establishing the FK, losing the
constraint sub-rubric.

### hard — performance diagnosis (score: 0.010, 18 steps — FAILURE)

Same JSON+text format failure as Runs 11–12. The model survived
slightly longer (18 steps vs 10) before context overflow, but the
extra steps are meaningless since every one produces a syntax error.

The initial SQL varied slightly from previous runs — step 1 tried
`EXPLAIN ANALYZE`, steps 2–3 tried CREATE INDEX, step 4 tried
VACUUM FULL, step 5 tried pg_terminate_backend — showing the model
has a reasonable strategy for the hard task. It just can't deliver
the SQL in a parseable format.

### expert — backup & recovery (score: 0.990, 5 steps)

Same clean 5-step path as Run 11:
1. `CREATE TABLE customers_backup AS SELECT * FROM backup_customers` → 0.16
2. `CREATE TABLE audit_log AS SELECT * FROM backup_audit_log` → 0.41
3. `INSERT INTO customers SELECT * … WHERE id NOT IN (…)` → 0.71
4. `INSERT INTO orders SELECT * … WHERE id NOT IN (…)` → 0.96
5. `UPDATE customers SET balance = … WHERE balance = 0.00` → 0.99

Used `SELECT *` (the winning strategy), unlike Run 12's explicit
columns. This confirms expert variance is driven by the stochastic
choice between `SELECT *` and explicit column lists.

### master — security audit (score: 0.990, 1 step)

**Solved in a single step** by combining all four statements:
```
ALTER ROLE analytics_user NOSUPERUSER;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
REVOKE SELECT ON task_schema.salaries FROM readonly_user;
ALTER ROLE intern_user WITH PASSWORD 'intern_user_passwo...';
```

Reward jumped straight to 0.99. This is the most efficient master
solve across all 13 runs. The multi-statement splitting in the
environment handled it correctly.

---

## Llama-3.1-8B-Instruct: three-run summary

| Task   | Run 11 | Run 12 | Run 13 | Mean  | Std   | Verdict |
|--------|--------|--------|--------|-------|-------|---------|
| easy   | 0.990  | 0.990  | 0.990  | 0.990 | 0.000 | Reliable pass |
| medium | 0.550  | 0.500  | 0.438  | 0.496 | 0.046 | Reliable fail — column-name loop |
| hard   | 0.010  | 0.010  | 0.010  | 0.010 | 0.000 | Reliable fail — format compliance |
| expert | 0.990  | 0.410  | 0.990  | 0.797 | 0.273 | **Unstable** — SELECT * vs explicit |
| master | 0.990  | 0.990  | 0.990  | 0.990 | 0.000 | Reliable pass |
| **agg**| 3.530  | 2.900  | 3.418  | 3.283 | 0.272 | |

The expert task is the only source of inter-run variance. Everything
else is deterministic: easy and master always pass, medium and hard
always fail.

---

## Open vs. closed models: qualitative findings

This is the first open-source model tested. Three systemic differences
emerge compared to GPT-family models:

### 1. Output format compliance

**GPT models** (gpt-4o, gpt-4o-mini, gpt-3.5-turbo): Always produce
output that `parse_action()` can handle — either clean JSON matching
Strategy 1 or raw SQL matching Strategy 3. Zero format-related failures
across 10 runs.

**Llama-3.1-8B-Instruct**: Inconsistent. Outputs raw SQL on 4 of 5
tasks (works via Strategy 3) but outputs JSON+trailing-explanation on
the hard task (falls through to Strategy 3 which sends raw JSON to
PostgreSQL). The model says "I will remove the unnecessary curly
brackets" in its explanation but never actually does — it cannot
self-correct its format even when the error message says
`syntax error at or near "{"`.

**Implication:** Instruction-following reliability is a clear
differentiator between open and closed models at this parameter count.
The system prompt's JSON format instruction is consistently ignored or
half-followed.

### 2. Context window as a hard wall

**GPT models**: 128K+ context window. Never hit the limit across any
run, even with 25-step conversations.

**Llama-3.1-8B-Instruct**: 8192-token limit. Hit the limit on:
- Hard task (all 3 runs): at step 10, 10, 18 respectively.
- Medium task (Run 13): at step 25.

When the context overflows, the API returns a 400 error, the harness
logs an LLM error, and the episode terminates. This means the model
has fewer effective retries — compounding the format and column-name
issues by giving it less room to eventually stumble onto a fix.

### 3. Error-recovery and schema introspection

**GPT models** (especially gpt-4o, gpt-4o-mini): Use
`information_schema.columns` or `pg_catalog` to discover schema before
acting. When an error occurs, they read the error message and adapt.

**Llama-3.1-8B-Instruct**: Never queries the schema. When an INSERT
fails with `column "name" does not exist`, it tries the same column
name with different SQL syntax variations instead of asking what
columns actually exist. It repeats the same error 20+ times without
changing strategy.

### 4. Premature done signaling

**GPT models**: Never signal `done=true` unless reward is at or near
the success threshold (0.85+).

**Llama-3.1-8B-Instruct** (Run 12): Signaled `done=true` at reward
0.41 on expert, wasting the remaining step budget. This suggests the
model has poor calibration about its own progress — it believes the
task is complete when less than half the rubric is satisfied.

---

## Model tier ranking (final, all 13 runs)

| Model                    | Runs | Agg range       | Mean agg | Key weakness |
|--------------------------|------|-----------------|----------|--------------|
| gpt-4o-mini              | 5    | 4.880 – 5.000   | 4.932    | None (minor expert threshold) |
| gpt-3.5-turbo            | 3    | 4.460 – 4.865   | 4.595    | Medium retry loop (2 of 3 runs) |
| gpt-4o                   | 1    | 2.865 (3 tasks) | —        | Incomplete (only 3 tasks tested) |
| Llama-3.1-8B-Instruct    | 3    | 2.900 – 3.530   | 3.283    | Format compliance, context window, no introspection |

The environment discriminates effectively between model tiers. The gap
between gpt-3.5-turbo (4.595 mean) and Llama 8B (3.283 mean) is 1.31
points — almost entirely from hard (always 0.01 vs always 1.0) and
medium (always <0.55 vs sometimes 0.865). Easy and master are solved
by all models; expert is the variance source for both.

---

## Raw log output

```
[START] task=easy env=postgres_dba_gym model=meta-llama/Llama-3.1-8B-Instruct
[STEP] step=1 action=EXPLAIN (ANALYZE, BUFFERS) SELECT * FROM task_schema.orders ...; reward=0.06 done=false error=null
[STEP] step=2 action=CREATE INDEX idx_orders_customer_id_status_order_date ON task_schema.orders (customer_id, status, order_date DESC); reward=0.99 done=true error=null
[END] success=true steps=2 score=0.990 rewards=0.06,0.99
[START] task=medium env=postgres_dba_gym model=meta-llama/Llama-3.1-8B-Instruct
[STEP] step=1 action=CREATE TABLE task_schema.customers (...); CREATE TABLE task_schema.orders (...); reward=0.44 done=false error=null
[STEP] step=2–24 (column name loop) action=INSERT INTO task_schema.customers (...) SELECT ... FROM task_schema.user_orders; reward=0.44 done=false error=column "name"/"email" does not exist
[STEP] step=25 action= reward=0.44 done=true error=llm error: context length 8416 > 8192 limit
[END] success=false steps=25 score=0.438 rewards=0.44,0.44,0.44,0.44,0.44,0.44,0.44,0.44,0.44,0.44,0.44,0.44,0.44,0.44,0.44,0.44,0.44,0.44,0.44,0.44,0.44,0.44,0.44,0.44,0.44
[START] task=hard env=postgres_dba_gym model=meta-llama/Llama-3.1-8B-Instruct
[STEP] step=1 action={"sql": "EXPLAIN (ANALYZE, BUFFERS) SELECT * FROM events WHERE user_id = 42;", "done": false} ... reward=0.01 done=false error=syntax error at or near "{"
[STEP] step=2–4 (varied SQL inside JSON: CREATE INDEX, VACUUM FULL, pg_terminate_backend) reward=0.01 error=syntax error at or near "{"
[STEP] step=5–17 (identical pg_terminate_backend in JSON wrapper) reward=0.01 error=syntax error at or near "{"
[STEP] step=18 action= reward=0.01 done=true error=llm error: context length 8312 > 8192 limit
[END] success=false steps=18 score=0.010 rewards=0.01,0.01,0.01,0.01,0.01,0.01,0.01,0.01,0.01,0.01,0.01,0.01,0.01,0.01,0.01,0.01,0.01,0.01
[START] task=expert env=postgres_dba_gym model=meta-llama/Llama-3.1-8B-Instruct
[STEP] step=1 action=CREATE TABLE task_schema.customers_backup AS SELECT * FROM task_schema.backup_customers; reward=0.16 done=false error=null
[STEP] step=2 action=CREATE TABLE task_schema.audit_log AS SELECT * FROM task_schema.backup_audit_log; reward=0.41 done=false error=null
[STEP] step=3 action=INSERT INTO task_schema.customers SELECT * FROM task_schema.customers_backup WHERE id NOT IN (SELECT id FROM task_schema.customers); reward=0.71 done=false error=null
[STEP] step=4 action=INSERT INTO task_schema.orders SELECT * FROM task_schema.backup_orders WHERE id NOT IN (SELECT id FROM task_schema.orders); reward=0.96 done=false error=null
[STEP] step=5 action=UPDATE task_schema.customers SET balance = (SELECT balance FROM task_schema.customers_backup WHERE id = task_schema.customers.id) WHERE balance = 0.00; reward=0.99 done=true error=null
[END] success=true steps=5 score=0.990 rewards=0.16,0.41,0.71,0.96,0.99
[START] task=master env=postgres_dba_gym model=meta-llama/Llama-3.1-8B-Instruct
[STEP] step=1 action=ALTER ROLE analytics_user NOSUPERUSER; REVOKE CREATE ON SCHEMA public FROM PUBLIC; REVOKE SELECT ON task_schema.salaries FROM readonly_user; ALTER ROLE intern_user WITH PASSWORD '...'; reward=0.99 done=true error=null
[END] success=true steps=1 score=0.990 rewards=0.99
```
