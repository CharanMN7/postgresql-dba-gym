# Sixteenth end-to-end `inference.py` run — annotated (Llama-3.3-70B-Instruct, cross-model analysis)

Date: 2026-04-09
Model: `meta-llama/Llama-3.3-70B-Instruct`
Final scores: `{"easy": 0.990, "medium": 0.785, "hard": 0.990, "expert": 0.990, "master": 0.990}`
Aggregate: **4.745 / 5.0**

Third and final 70B run. Medium drops to 0.785 (below the 0.85
threshold — the only failure) because the model signaled `done=true`
after creating the view without proper column aliases. All other tasks
pass identically to Runs 14–15.

---

## Headline — sixteen runs side by side

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

---

## Per-task analysis

### easy — index optimization (score: 0.990, 1 step)

Combined `EXPLAIN ANALYZE` + `CREATE INDEX` into a single step. The
EXPLAIN runs first (diagnostic), then the index is created. Both execute
in one round-trip. Same 0.99 reward as previous runs.

### medium — schema migration (score: 0.785, 12 steps — FAILURE)

The only failure across three 70B runs.

| Step | Action | Reward | Notes |
|------|--------|--------|-------|
| 1 | `CREATE TABLE customers (…)` | 0.31 | |
| 2 | `CREATE TABLE orders (…)` | 0.44 | |
| 3 | `ALTER TABLE … ADD CONSTRAINT FK …` | 0.50 | Schema complete |
| 4–10 | INSERT with `name`/`uo.name`/`ROW_NUMBER()` variants | 0.50 | 7-step column name retry loop |
| 11 | `INSERT … SELECT DISTINCT customer_name, customer_email, customer_address` | **0.61** | Found the prefix after 7 errors |
| 12 | `CREATE VIEW user_orders_view AS SELECT c.name, c.email, c.address, …` | **0.79** | View created — but **done=true** |

**Why it failed:** The view at step 12 used `c.name, c.email,
c.address` instead of `c.name AS customer_name, c.email AS
customer_email, c.address AS customer_address`. Without the aliases,
the view sub-rubric awarded partial credit (0.79) but not the full
0.25 needed to cross 0.85.

The model signaled `done=true` at 0.79, believing the task was
complete. This is the same **premature done** failure mode seen with
Llama 8B Run 12 (expert at 0.41). The model lacks calibration about
its own progress — it doesn't read the grading_breakdown feedback
to see that the view sub-rubric is incomplete.

**Contrast with Runs 14–15:** Both previous runs created the view,
saw 0.79, then re-created with proper aliases to reach 0.86.
The difference is stochastic: at temperature 0.2, sometimes the
model declares done immediately after the view, sometimes it
recognizes the aliases are needed.

### hard — performance diagnosis (score: 0.990, 5 steps)

Same 5-step structure as Run 14, with slightly different ordering:

1. Multi-statement discovery (EXPLAIN + pg_indexes + pg_stat_user_tables + pg_settings) → 0.01
2. `CREATE INDEX … (user_id); CREATE INDEX … (event_type)` → 0.25
3. `SELECT pg_terminate_backend(201)` → 0.50
4. `VACUUM FULL task_schema.bloated_logs` → 0.75
5. `ALTER SYSTEM SET … (3 GUCs); SELECT pg_reload_conf()` → 0.99

Run 14 did GUCs before VACUUM; this run reverses the order. Both
achieve 0.99 because the grader checks each sub-rubric independently.

### expert — backup & recovery (score: 0.990, 4 steps)

Same as Runs 14–15. Step 3 used `CREATE TABLE IF NOT EXISTS audit_log
AS SELECT * FROM backup_audit_log` instead of the `WITH NO DATA;
INSERT` variant — slightly cleaner SQL.

### master — security audit (score: 0.990, 1 step)

Combined all 4 statements in one step, same as Run 14.

---

## Llama-3.3-70B-Instruct: three-run summary

| Task   | Run 14 | Run 15 | Run 16 | Mean  | Std   | Verdict |
|--------|--------|--------|--------|-------|-------|---------|
| easy   | 0.990  | 0.990  | 0.990  | 0.990 | 0.000 | Reliable pass |
| medium | 0.865  | 0.865  | 0.785  | 0.838 | 0.038 | Usually pass — view alias miss in Run 16 |
| hard   | 0.990  | 0.990  | 0.990  | 0.990 | 0.000 | Reliable pass |
| expert | 0.990  | 0.990  | 0.990  | 0.990 | 0.000 | Reliable pass |
| master | 0.990  | 0.990  | 0.990  | 0.990 | 0.000 | Reliable pass |
| **agg**| 4.825  | 4.825  | 4.745  | 4.798 | 0.038 | |

The 70B model is remarkably consistent. Four of five tasks are
deterministic at 0.990. Medium is the only variance source, and even
there the failure mode is narrow: the model discovers the column
prefix (all 3 runs), inserts data correctly (all 3 runs), and creates
the view (all 3 runs) — it just sometimes forgets the aliases.

---

## Llama 8B vs 70B: head-to-head

| Dimension | Llama-3.1-8B | Llama-3.3-70B | Gap |
|-----------|-------------|---------------|-----|
| Mean aggregate | 3.283 | 4.798 | **+1.515** |
| easy | 0.990 (always) | 0.990 (always) | None |
| medium | 0.496 (always fail) | 0.838 (2/3 pass) | **+0.342** |
| hard | 0.010 (always fail) | 0.990 (always pass) | **+0.980** |
| expert | 0.797 (unstable) | 0.990 (always pass) | **+0.193** |
| master | 0.990 (always) | 0.990 (always) | None |
| Format compliance | JSON+text on hard | Clean SQL always | Fixed |
| Schema introspection | Never | Sometimes (1/3 runs) | New capability |
| Context window | 8K (hit limit) | 128K (never hit) | No longer a constraint |
| Column-name inference | Never finds prefix | Finds prefix (all runs) | Critical reasoning gap |
| Premature done | 1/3 runs (expert) | 1/3 runs (medium) | Both models do this |

The 8B → 70B jump fixes the two fatal deficiencies:
1. **Format compliance** (hard: 0.01 → 0.99)
2. **Column-name reasoning** (medium: 0.50 → 0.86)

These two fixes alone account for +1.32 of the +1.515 aggregate gap.

---

## Model tier ranking (final, all 16 runs)

| Tier | Model                        | Runs | Agg range       | Mean agg | Key differentiator |
|------|------------------------------|------|-----------------|----------|--------------------|
| S    | gpt-4o-mini                  | 5    | 4.880 – 5.000   | 4.932    | Reliable medium, no failures |
| A    | Llama-3.3-70B-Instruct       | 3    | 4.745 – 4.825   | 4.798    | Open model, passes hard, medium sometimes misses alias |
| A-   | gpt-3.5-turbo                | 3    | 4.460 – 4.865   | 4.595    | Medium retry loop (2/3 runs) |
| B    | gpt-4o                       | 1    | 2.865 (3 tasks) | —        | Incomplete data |
| C    | Llama-3.1-8B-Instruct        | 3    | 2.900 – 3.530   | 3.283    | Format failure, no introspection |

### Key takeaways

1. **Llama-3.3-70B outperforms gpt-3.5-turbo.** The open 70B model
   (mean 4.798) beats the closed gpt-3.5-turbo (mean 4.595) by 0.20
   points. The gap comes from gpt-3.5-turbo's degenerate medium loop
   (0.50 in 2/3 runs) vs 70B's ability to find column names.

2. **gpt-4o-mini remains the champion.** Its 0.920–1.000 range on
   medium and reliable expert performance keep it ahead. The 70B model
   would need to solve medium's view-alias issue more reliably to
   close the 0.134 mean-aggregate gap.

3. **Parameter count is the biggest differentiator for open models.**
   8B → 70B is a +1.515 aggregate jump. Format compliance, reasoning
   about column-name patterns, and context window utilization all
   improve dramatically with scale.

4. **Medium is the universal discriminator.** Every model tested has
   its best and worst runs separated primarily by medium task
   performance. The column-name discovery problem, data migration
   correctness, and view aliasing are the three sub-challenges that
   separate tiers.

5. **Open models can compete with closed models.** The 70B Llama
   model at 4.825 sits between gpt-3.5-turbo's best (4.865) and
   worst (4.460), demonstrating that open-source models are viable
   for agentic DBA tasks when sufficiently large.

---

## Raw log output

```
[START] task=easy env=postgres_dba_gym model=meta-llama/Llama-3.3-70B-Instruct
[STEP] step=1 action=EXPLAIN (ANALYZE, BUFFERS) SELECT * FROM task_schema.orders ...; CREATE INDEX idx_orders_customer_id_status_order_date ON task_schema.orders (customer_id, status, order_date DESC); reward=0.99 done=true error=null
[END] success=true steps=1 score=0.990 rewards=0.99
[START] task=medium env=postgres_dba_gym model=meta-llama/Llama-3.3-70B-Instruct
[STEP] step=1 action=CREATE TABLE task_schema.customers (...); reward=0.31 done=false error=null
[STEP] step=2 action=CREATE TABLE task_schema.orders (...); reward=0.44 done=false error=null
[STEP] step=3 action=ALTER TABLE task_schema.orders ADD CONSTRAINT fk_customer_id ...; reward=0.50 done=false error=null
[STEP] step=4–10 (column name retry loop) reward=0.50 done=false error=column "name"/uo.name does not exist
[STEP] step=11 action=INSERT INTO task_schema.customers (name, email, address) SELECT DISTINCT customer_name, customer_email, customer_address FROM task_schema.user_orders; INSERT INTO task_schema.orders ...; reward=0.61 done=false error=null
[STEP] step=12 action=CREATE VIEW task_schema.user_orders_view AS SELECT c.name, c.email, c.address, o.order_date, o.amount, o.status FROM task_schema.customers c JOIN task_schema.orders o ON c.id = o.customer_id; reward=0.79 done=true error=null
[END] success=false steps=12 score=0.785 rewards=0.31,0.44,0.50,0.50,0.50,0.50,0.50,0.50,0.50,0.50,0.61,0.79
[START] task=hard env=postgres_dba_gym model=meta-llama/Llama-3.3-70B-Instruct
[STEP] step=1 action=EXPLAIN ANALYZE ...; SELECT * FROM pg_indexes ...; SELECT * FROM pg_stat_user_tables ...; SELECT name, setting FROM pg_settings ...; reward=0.01 done=false error=null
[STEP] step=2 action=CREATE INDEX idx_events_user_id ON task_schema.events (user_id); CREATE INDEX idx_events_event_type ON task_schema.events (event_type); reward=0.25 done=false error=null
[STEP] step=3 action=SELECT pg_terminate_backend(201); reward=0.50 done=false error=null
[STEP] step=4 action=VACUUM FULL task_schema.bloated_logs; reward=0.75 done=false error=null
[STEP] step=5 action=ALTER SYSTEM SET work_mem = '4MB'; ALTER SYSTEM SET random_page_cost = 1.5; ALTER SYSTEM SET effective_cache_size = '512MB'; SELECT pg_reload_conf(); reward=0.99 done=true error=null
[END] success=true steps=5 score=0.990 rewards=0.01,0.25,0.50,0.75,0.99
[START] task=expert env=postgres_dba_gym model=meta-llama/Llama-3.3-70B-Instruct
[STEP] step=1 action=INSERT INTO customers (SELECT * FROM backup_customers WHERE id NOT IN (SELECT id FROM customers)) reward=0.46 done=false error=null
[STEP] step=2 action=INSERT INTO orders (SELECT * FROM backup_orders WHERE id NOT IN (SELECT id FROM orders)) reward=0.71 done=false error=null
[STEP] step=3 action=CREATE TABLE IF NOT EXISTS audit_log AS SELECT * FROM backup_audit_log reward=0.96 done=false error=null
[STEP] step=4 action=UPDATE customers SET balance = backup_customers.balance FROM backup_customers WHERE customers.id = backup_customers.id AND customers.balance = 0.00 reward=0.99 done=true error=null
[END] success=true steps=4 score=0.990 rewards=0.46,0.71,0.96,0.99
[START] task=master env=postgres_dba_gym model=meta-llama/Llama-3.3-70B-Instruct
[STEP] step=1 action=ALTER ROLE analytics_user NOSUPERUSER; REVOKE CREATE ON SCHEMA public FROM PUBLIC; REVOKE SELECT ON task_schema.salaries FROM readonly_user; ALTER ROLE intern_user WITH PASSWORD 'intern_password'; reward=0.99 done=true error=null
[END] success=true steps=1 score=0.990 rewards=0.99
```
