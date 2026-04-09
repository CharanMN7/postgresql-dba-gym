# Run 29 — Llama-4-Scout (medium catastrophe, destructive action guard)

Date: 2026-04-09
Model: `meta-llama/Llama-4-Scout-17B-16E-Instruct`
Final scores: `{"easy": 0.990, "medium": 0.660, "hard": 0.990, "expert": 0.990, "master": 0.990}`
Aggregate: **4.620 / 5.0**

Medium degrades to **0.660** — the lowest medium score of any Llama-4-Scout
run. The model enters a destructive spiral: it drops and recreates tables,
loses existing data, breaks sequences, and then repeatedly attempts
`TRUNCATE` and `DELETE FROM` which are blocked by the
`_DESTRUCTIVE_PATTERNS` guard. This run exposes the model's inability to
recover from self-inflicted data corruption on medium. Other tasks pass
normally.

---

## Per-task analysis

### easy — index optimization (score: 0.990, 2 steps)

Standard `EXPLAIN` → `CREATE INDEX`.

### medium — schema migration (score: 0.660, 25 steps) — CATASTROPHIC FAILURE

This is the worst medium performance of any model except Llama-3.1-8B
(which never passed medium at all). The run reveals a destructive spiral:

**Phase 1 — Normal approach (steps 1–7, reward stalls at 0.50):**

| Step | Action | Reward | Notes |
|------|--------|--------|-------|
| 1 | CREATE TABLE customers | 0.31 | |
| 2 | Combined INSERT customers + orders → "name" error | 0.31 | |
| 3 | CREATE TABLE customers → already exists | 0.31 | |
| 4 | CREATE TABLE orders | 0.44 | |
| 5 | ADD CONSTRAINT fk_customer_id | 0.50 | |
| 6 | INSERT customers (name) → column error | 0.50 | |
| 7 | INSERT with uo.name → column error | 0.50 | |

**Phase 2 — Nuclear option: DROP + RECREATE (steps 8–12, peak 0.79):**

| Step | Action | Reward | Notes |
|------|--------|--------|-------|
| 8 | DROP TABLE customers → blocked by FK dependency | 0.50 | |
| 9 | DROP TABLE orders; DROP TABLE customers; recreate both | 0.79 | **Destroys existing data** |
| 10 | INSERT customers (ON CONFLICT) → duplicate key | 0.79 | |
| 11 | INSERT + CREATE VIEW → view already exists | 0.65 | **Reward DROPS from 0.79 to 0.65** |
| 12 | DROP VIEW + CREATE VIEW (with aliases) | 0.72 | Partial recovery |

The model loses progress at step 11 — the reward goes backwards from
0.79 → 0.65 because the environment detects missing data. This is the
first time we've seen reward regression from a model's own actions.

**Phase 3 — Spiral into destructive actions (steps 13–25):**

The model tries to re-insert data but breaks the sequence:
- Step 16: `DROP SEQUENCE … CASCADE` destroys the `orders.id` default
- Step 16: INSERT fails with "null value in column id violates not-null"
- Steps 17–19: `TRUNCATE TABLE` → `destructive_action_blocked`
- Steps 20–25: Alternates between `DELETE FROM` (blocked) and `TRUNCATE`
  (blocked), stuck in a loop

**The destructive action guard fires 8 times** (steps 17, 18, 19, 21,
22, 23, 24, and 25). The guard correctly prevents the model from
further damaging the environment.

**Root cause:** The model's initial `DROP TABLE orders; DROP TABLE
customers` at step 9 destroys previously-correct data. Once the
sequence is also destroyed at step 16, there is no recovery path
without `TRUNCATE` or re-creating sequences — but these are blocked.

### hard — performance diagnosis (score: 0.990, 6 steps)

Standard pattern. Uses `VACUUM FULL`.

### expert — backup & recovery (score: 0.990, 4 steps)

Same 4-step efficient pattern as Run 28:
LEFT JOIN anti-join → NOT IN → DROP + CREATE TABLE AS SELECT → UPDATE balance.

The balance UPDATE uses `c.balance = 0.00 AND bc.balance <> 0.00` —
same defensive variant.

### master — security audit (score: 0.990, 4 steps)

Standard 4-step sequence without inspection.
Password: `password123`.

---

## Behavioral insight: destructive spiral taxonomy

The medium catastrophe in this run follows a recognizable pattern:

1. **Trigger:** Column-name assumption fails (steps 2, 6, 7)
2. **Escalation:** Model attempts `DROP TABLE` to "start fresh" (step 9)
3. **Data loss:** Existing correct data is destroyed
4. **Recovery attempt:** Re-insertion hits data integrity issues
5. **Sequence corruption:** `DROP SEQUENCE CASCADE` destroys defaults
6. **Terminal loop:** Blocked by destructive action guard indefinitely

This pattern is unique to Llama-4-Scout — no other model attempts
`DROP TABLE` on medium. The environment's destructive action guard
(`_DESTRUCTIVE_PATTERNS`) correctly prevents further damage but cannot
undo the harm already caused.

### Question: Should `DROP TABLE` be considered destructive?

Currently `_DESTRUCTIVE_PATTERNS` blocks `TRUNCATE`, `DELETE FROM`,
`DROP DATABASE`, and `pg_terminate_backend(pg_backend_pid())`. It does
NOT block `DROP TABLE` or `DROP SEQUENCE`. This run suggests these
could be added — but `DROP TABLE IF EXISTS; CREATE TABLE AS SELECT *`
is a legitimate pattern used on expert. A potential heuristic: block
`DROP TABLE` only on tables the agent created (not backup tables).
This remains an open design question.

---

## Raw log output

```
[START] task=easy ... model=meta-llama/Llama-4-Scout-17B-16E-Instruct
[END] success=true steps=2 score=0.990
[START] task=medium ...
[STEP] step=9 (DROP + recreate tables) reward=0.79
[STEP] step=11 (INSERT + CREATE VIEW → reward DROPS to 0.65)
[STEP] step=16 (DROP SEQUENCE CASCADE → null id errors)
[STEP] step=17–25 (TRUNCATE/DELETE → destructive_action_blocked × 8)
[END] success=false steps=25 score=0.660
[START] task=hard ...
[END] success=true steps=6 score=0.990
[START] task=expert ...
[END] success=true steps=4 score=0.990
[START] task=master ...
[END] success=true steps=4 score=0.990
```
