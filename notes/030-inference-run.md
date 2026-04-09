# Run 30 — Llama-4-Scout (clean run + comprehensive 4-run summary)

Date: 2026-04-09
Model: `meta-llama/Llama-4-Scout-17B-16E-Instruct`
Final scores: `{"easy": 0.990, "medium": 0.865, "hard": 0.990, "expert": 0.990, "master": 0.990}`
Aggregate: **4.825 / 5.0**

All five tasks pass. The cleanest Llama-4-Scout run — no JSON format
issues on medium, expert uses the standard 9-step audit_log struggle,
master solves in 4 steps without inspection.

---

## Per-task analysis

### easy — index optimization (score: 0.990, 2 steps)

Standard `EXPLAIN (ANALYZE, BUFFERS)` → `CREATE INDEX`.

### medium — schema migration (score: 0.865, 7 steps) — SUCCESS

The most efficient medium solve across all Llama-4-Scout runs:

| Step | Action | Reward | Notes |
|------|--------|--------|-------|
| 1 | CREATE TABLE customers | 0.31 | |
| 2 | INSERT INTO orders → orders table doesn't exist | 0.31 | Premature orders INSERT |
| 3 | CREATE TABLE IF NOT EXISTS customers + orders + INSERT (SELECT DISTINCT name …) | 0.50 | Column "name" error on INSERT but tables created |
| 4 | INSERT with uo.name → uo.name error | 0.50 | |
| 5 | `information_schema` introspection | 0.50 | Discovers `customer_name` |
| 6 | Combined: INSERT customers + INSERT orders + ADD FK → 0.61 | 0.61 | FK constraint already exists error |
| 7 | DROP + ADD FK constraint + CREATE VIEW | **0.86** | `CREATE VIEW user_orders_view` passes |

No JSON format issues in this run. The model creates both tables in
step 3's multi-statement action, discovers correct column names at
step 5, and completes the migration with a view at step 7.

### hard — performance diagnosis (score: 0.990, 7 steps)

Standard 7-step pattern with individual GUC changes:
indexes → pg_indexes verify → pg_stat_activity → pg_terminate_backend →
VACUUM FULL → ALTER SYSTEM SET (work_mem 32MB, random_page_cost 1.5,
effective_cache_size 2048MB).

**Non-standard GUC values:** This model consistently sets `work_mem`
to 32MB and `effective_cache_size` to 2048MB — significantly higher
than the 4MB / 512MB values used by Qwen and GPT models. The rubric
still scores 0.99, suggesting the grading checks that values were
*changed*, not that specific values were set.

### expert — backup & recovery (score: 0.990, 9 steps)

Same 9-step pattern as the cleanest runs: LEFT JOIN anti-join for
customers/orders, then a 6-step `audit_log` struggle:

| Step | Action | Reward | Notes |
|------|--------|--------|-------|
| 1 | `INSERT INTO customers SELECT bc.* … LEFT JOIN … WHERE c.id IS NULL` | 0.46 | Anti-join |
| 2 | `INSERT INTO orders SELECT bo.* … LEFT JOIN … WHERE o.id IS NULL` | 0.71 | Anti-join |
| 3 | CREATE TABLE audit_log (hallucinated columns) + INSERT SELECT * | 0.71 | "more expressions than target" |
| 4 | Check info_schema + assume columns → "relation already exists" | 0.71 | |
| 5 | DROP + CREATE audit_log (hallucinated) + INSERT SELECT * | 0.71 | Same error |
| 6 | Check info_schema + explicit INSERT → "log_time" doesn't exist | 0.71 | **Reads schema, still hallucinates** |
| 7 | UPDATE customers balance | 0.75 | Pivots to balance fix |
| 8 | Another audit_log attempt → log_time error | 0.75 | |
| 9 | `DROP TABLE IF EXISTS; CREATE TABLE AS SELECT *` | **0.99** | Finally uses CREATE AS |

**The audit_log problem is systematic:** In Runs 27 and 30 (9 and 8
steps respectively), the model reads `information_schema` to discover
the `backup_audit_log` columns, but then **guesses** column names like
`log_time`, `event_type`, `details` instead of using the names it
just queried. In Runs 28 and 29 (4 steps each), it skips the guessing
and goes directly to `CREATE TABLE AS SELECT *`. The hallucination
appears ~50% of the time.

### master — security audit (score: 0.990, 4 steps)

Standard 4-step sequence. Password: `password123`.

---

## Llama-4-Scout four-run summary

### Score matrix

| Run | Easy | Medium | Hard | Expert | Master | Aggregate |
|-----|------|--------|------|--------|--------|-----------|
| 27 | 0.990 | **0.785** ✗ | 0.990 | 0.990 | 0.990 | 4.745 |
| 28 | 0.990 | 0.865 ✓ | 0.990 | 0.990 | 0.990 | 4.825 |
| 29 | 0.990 | **0.660** ✗ | 0.990 | 0.990 | 0.990 | 4.620 |
| 30 | 0.990 | 0.865 ✓ | 0.990 | 0.990 | 0.990 | 4.825 |
| **Mean** | 0.990 | 0.794 | 0.990 | 0.990 | 0.990 | **4.754** |
| **Best** | 0.990 | 0.865 | 0.990 | 0.990 | 0.990 | **4.825** |

**Medium pass rate: 2/4 (50%)**. When it passes, it scores 0.865.
When it fails, the scores vary (0.785 from format issues, 0.660 from
destructive spiral).

### Key model behaviors

#### 1. LEFT JOIN anti-join pattern (expert)

Unique to Llama-4-Scout. Used in all 4 runs for the "insert missing
rows" pattern:

```sql
INSERT INTO customers
SELECT bc.*
FROM backup_customers bc
LEFT JOIN customers c ON bc.id = c.id
WHERE c.id IS NULL;
```

This is textbook SQL — more readable than `NOT IN`, `NOT EXISTS`, or
`EXCEPT`, and generally has better query plans on large tables.

#### 2. JSON format instability (medium)

In 2 of 4 runs (27, 28), the model intermittently outputs raw JSON:
```
{ "sql": "INSERT INTO task_schema.customers ...", "done": false }
```

This fails with `syntax error at or near "{"` because `parse_action()`
treats it as raw SQL (Strategy 3). The issue is **intermittent within
a single run** — the model switches between raw SQL and JSON-wrapped
responses mid-episode. This is different from Llama-3.1-8B which
consistently failed on format.

| Run | JSON format errors | Medium steps | Medium score |
|-----|-------------------|-------------|-------------|
| 27 | 5 (steps 2,3,8,9,13) | 15 | 0.785 ✗ |
| 28 | 4 (steps 2,3,8,9) | 13 | 0.865 ✓ |
| 29 | 0 | 25 | 0.660 ✗ |
| 30 | 0 | 7 | 0.865 ✓ |

Format issues cost ~4–5 wasted steps but don't necessarily cause
failure — Run 28 has 4 format errors but still passes.

#### 3. Audit_log schema hallucination (expert)

The model reads `information_schema.columns` to get the actual schema
of `backup_audit_log`, then ignores the results and uses hallucinated
column names (`log_time`, `event_type`, `details`, `column1`, `column2`):

| Run | Expert steps | Hallucinated? | Resolution |
|-----|-------------|---------------|------------|
| 27 | 8 | Yes (steps 3–6) | DROP + CREATE AS at step 7 |
| 28 | **4** | No — goes straight to CREATE AS | |
| 29 | **4** | No — goes straight to CREATE AS | |
| 30 | 9 | Yes (steps 3–8) | DROP + CREATE AS at step 9 |

When the model avoids hallucinating, it achieves the most efficient
expert solve of any model (4 steps). When it hallucinates, it takes
8–9 steps. The hallucination rate is 50%.

#### 4. Destructive spiral on medium (Run 29)

The worst failure mode: the model drops its own tables, loses data,
breaks sequences, and then loops on `TRUNCATE`/`DELETE` blocked by
`_DESTRUCTIVE_PATTERNS`. This is unique to Llama-4-Scout.

#### 5. GUC value variation on hard

| Model | work_mem | random_page_cost | effective_cache_size |
|-------|----------|-------------------|---------------------|
| **Llama-4-Scout** | **32MB** | **1.5** | **2048MB** |
| Qwen 72B | 4MB | 2.0 | 512MB |
| Gemma 27B | 4MB | 2.0 | 512MB |
| gpt-4o-mini | 4MB | 2.0 | 512MB |

Llama-4-Scout uses significantly different values. Both sets score
0.99, confirming the rubric checks for value changes, not specific
values. The model's higher values are arguably more appropriate for a
modern server.

#### 6. Master: inspection vs action-first

| Run | Master steps | Inspection queries | Approach |
|-----|-------------|-------------------|----------|
| 27 | 5 | 1 (pg_roles) | Moderate caution |
| 28 | 9 | 5 (roles, grants, namespace, authid) | Very cautious |
| 29 | 4 | 0 | Action-first |
| 30 | 4 | 0 | Action-first |

The model's master behavior is highly variable — ranging from zero
inspection (Runs 29–30) to comprehensive inspection of all security
surfaces (Run 28). Temperature sampling drives this variation.

---

## Cross-model comparison (updated)

### Model tier ranking

| Tier | Model | Params | Runs | Mean agg | Best agg | Medium pass rate |
|------|-------|--------|------|----------|----------|-----------------|
| S | gpt-4o-mini | — | 5 | 4.932 | 4.950 | 100% |
| A | Gemma-3-27B-IT | 27B | 3 | 4.815 | 4.825 | 100% |
| A | Llama-3.3-70B | 70B | 3 | 4.798 | 4.825 | 100% |
| A | **Llama-4-Scout** | **17B MoE** | **4** | **4.754** | **4.825** | **50%** |
| A | Qwen2.5-72B | 72B | 2* | 4.700 | 4.825 | 50% |
| A- | gpt-3.5-turbo | — | 3 | 4.595 | 4.825 | 67% |
| C | Llama-3.1-8B | 8B | 3 | 3.283 | 3.363 | 0% |

*Qwen runs are post-v2-fix only.

### Parameter efficiency

| Model | Active params (est.) | Mean agg | Efficiency |
|-------|---------------------|----------|------------|
| gpt-4o-mini | ~8B? | 4.932 | Best |
| **Llama-4-Scout** | **~3.5B active** | **4.754** | **Excellent** |
| Gemma-3-27B-IT | 27B | 4.815 | Good |
| Llama-3.3-70B | 70B | 4.798 | Moderate |
| Qwen2.5-72B | 72B | 4.700 | Moderate |

Llama-4-Scout with 17B total / ~3.5B active parameters per token
achieves 4.754 mean — competitive with 27B–72B dense models. This
is the **most parameter-efficient open model** in our evaluation.

### Expert strategy comparison

| Model | Expert approach | Best steps | Distinctive feature |
|-------|---------------|-----------|-------------------|
| **Llama-4-Scout** | LEFT JOIN anti-join | **4** | Anti-join pattern |
| gpt-4o-mini | ON CONFLICT DO NOTHING | 4 | Upsert pattern |
| Qwen 72B | EXCEPT + NOT IN | 5 | Set difference |
| Gemma 27B | NOT EXISTS / NOT IN | 5 | Subquery filter |
| Llama 70B | ON CONFLICT DO NOTHING | 5 | Upsert pattern |

### Medium failure modes by model

| Model | Failure mode | Frequency |
|-------|-------------|-----------|
| Llama-4-Scout | JSON format + `uo.row_id` hallucination + destructive spiral | 2/4 fail |
| Qwen 72B | `o.row_id` column hallucination | 4/6 fail |
| Llama-3.1-8B | Context window + column name retry loop | 3/3 fail |
| gpt-3.5-turbo | premature `done=true` | 1/3 fail |
| Gemma 27B | — | 0/3 fail |
| Llama 70B | — | 0/3 fail |
| gpt-4o-mini | — | 0/5 fail |

---

## Key takeaways

1. **Llama-4-Scout is solidly A-tier.** Mean 4.754 with best 4.825,
   competitive with models 4–20× its parameter count. MoE architecture
   delivers excellent efficiency.

2. **Medium is the sole weakness, and it's multi-modal.** Three
   distinct failure mechanisms: JSON format instability, `uo.row_id`
   hallucination, and a destructive `DROP TABLE` spiral. No other model
   exhibits the destructive spiral.

3. **The LEFT JOIN anti-join is the cleanest expert approach.** It's
   textbook SQL that reads naturally and performs well. This is a
   behavioral signature unique to Llama-4-Scout.

4. **4-step expert is the shared record** (with gpt-4o-mini). When the
   model avoids audit_log hallucination, it achieves optimal expert
   efficiency.

5. **The model is less deterministic than Qwen or Gemma.** Master
   behavior ranges from 4–9 steps, expert from 4–9 steps, medium from
   7–25 steps. Temperature=0.2 produces high variance in this model.

6. **GUC values are non-standard but valid.** The model independently
   chooses more aggressive PostgreSQL tuning parameters (32MB work_mem,
   2048MB effective_cache_size) that are arguably better for production
   workloads.

7. **Destructive action guard proved its value.** Run 29's medium task
   triggered the guard 8 times, preventing further environmental damage.
   This validates the environment design. Open question: should
   `DROP TABLE` itself be guarded on non-backup tables?

---

## Raw log output

```
[START] task=easy env=postgres_dba_gym model=meta-llama/Llama-4-Scout-17B-16E-Instruct
[STEP] step=1 action=EXPLAIN (ANALYZE, BUFFERS) ... reward=0.07 done=false error=null
[STEP] step=2 action=CREATE INDEX idx_orders_customer_id_status_order_date ... reward=0.99 done=true error=null
[END] success=true steps=2 score=0.990 rewards=0.07,0.99
[START] task=medium env=postgres_dba_gym model=meta-llama/Llama-4-Scout-17B-16E-Instruct
[STEP] step=1 (CREATE TABLE customers) reward=0.31
[STEP] step=2 (INSERT orders → table doesn't exist) reward=0.31
[STEP] step=3 (CREATE TABLE IF NOT EXISTS + INSERT → column name error) reward=0.50
[STEP] step=4 (uo.name error) reward=0.50
[STEP] step=5 (information_schema) reward=0.50
[STEP] step=6 (INSERT + FK constraint exists error) reward=0.61
[STEP] step=7 (DROP/ADD FK + CREATE VIEW) reward=0.86 done=true
[END] success=true steps=7 score=0.865 rewards=0.31,0.31,0.50,0.50,0.50,0.61,0.86
[START] task=hard ...
[END] success=true steps=7 score=0.990 rewards=0.01,0.25,0.25,0.25,0.50,0.75,0.99
[START] task=expert ...
[STEP] step=1 (LEFT JOIN anti-join customers) reward=0.46
[STEP] step=2 (LEFT JOIN anti-join orders) reward=0.71
[STEP] step=3–8 (audit_log hallucination struggle) reward=0.71→0.75
[STEP] step=9 (DROP + CREATE TABLE AS SELECT) reward=0.99
[END] success=true steps=9 score=0.990 rewards=0.46,0.71,0.71,0.71,0.71,0.71,0.75,0.75,0.99
[START] task=master ...
[STEP] step=1–4 (standard 4-step security) reward=0.25→0.99
[END] success=true steps=4 score=0.990 rewards=0.25,0.50,0.75,0.99
```
