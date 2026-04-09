# Run 28 — Llama-4-Scout (4-step expert, cautious master)

Date: 2026-04-09
Model: `meta-llama/Llama-4-Scout-17B-16E-Instruct`
Final scores: `{"easy": 0.990, "medium": 0.865, "hard": 0.990, "expert": 0.990, "master": 0.990}`
Aggregate: **4.825 / 5.0**

All five tasks pass. Medium succeeds with `o.id` (no alias needed — the
model uses a different view strategy). Expert solved in only **4 steps**
— the most efficient expert solve of any model across all runs. Master
takes 9 steps due to 5 preliminary inspection queries.

---

## Per-task analysis

### easy — index optimization (score: 0.990, 2 steps)

Standard. Different index from most models:
`CREATE INDEX idx_orders_customer_id_status ON task_schema.orders (customer_id, status)` — omits `order_date DESC`. Still scores 0.99.

### medium — schema migration (score: 0.865, 13 steps) — SUCCESS

Despite JSON format issues (steps 2–3, 8–9) and column-name errors,
the model recovers and creates a correct view:

| Step | Action | Reward | Notes |
|------|--------|--------|-------|
| 1 | CREATE TABLE customers | 0.31 | |
| 2–3 | JSON-wrapped SQL | 0.31 | Format errors |
| 4–5 | Column name errors | 0.31 | |
| 6–7 | `information_schema` (SELECT *, then SELECT column_name) | 0.31 | Two introspection queries |
| 8 | INSERT customers (correct) | 0.31 | |
| 9 | INSERT INTO orders → table doesn't exist | 0.31 | |
| 10 | CREATE TABLE orders | 0.50 | |
| 11 | INSERT INTO orders | 0.61 | |
| 12 | `CREATE VIEW … o.id, c.name, c.email, c.address …` | 0.79 | No aliases — step needed |
| 13 | `DROP VIEW; CREATE VIEW … o.id, c.name AS customer_name, c.email AS customer_email, c.address AS customer_address …` | **0.86** | Corrects aliases |

The model creates the view without aliases first (step 12, 0.79), sees
the grading_breakdown still shows work needed, then recreates it with
proper aliases (step 13, 0.86). This self-correction loop is effective.

### hard — performance diagnosis (score: 0.990, 6 steps)

Different ordering again: indexes → GUCs → blocker → VACUUM.

Step 3 sets all three GUCs in one statement (unlike the step 7 pattern
in Run 27). Step 6 uses `CHECKPOINT; VACUUM task_schema.bloated_logs`
instead of the more common `VACUUM FULL` — both achieve 0.99.

### expert — backup & recovery (score: 0.990, 4 steps) — RECORD

**Most efficient expert solve of any model:**

| Step | Action | Reward |
|------|--------|--------|
| 1 | `INSERT INTO customers SELECT bc.* FROM backup_customers bc LEFT JOIN customers c ON bc.id = c.id WHERE c.id IS NULL` | 0.46 |
| 2 | `INSERT INTO orders SELECT bo.* FROM backup_orders bo WHERE bo.id NOT IN (SELECT id FROM orders)` | 0.71 |
| 3 | `DROP TABLE IF EXISTS audit_log; CREATE TABLE audit_log AS SELECT * FROM backup_audit_log` | 0.96 |
| 4 | `UPDATE customers c SET balance = bc.balance FROM backup_customers bc WHERE c.id = bc.id AND c.balance = 0.00 AND bc.balance <> 0.00` | 0.99 |

**Why only 4 steps when Run 27 needed 8:** The model skips the
hallucinated-schema attempts and goes directly to
`CREATE TABLE AS SELECT *` for `audit_log` (step 3). The balance UPDATE
adds an extra condition (`AND bc.balance <> 0.00`) — more defensive.

Note: step 2 uses `NOT IN` instead of the LEFT JOIN pattern from step 1.
The model mixes strategies within the same run.

### master — security audit (score: 0.990, 9 steps) — INSPECTION-HEAVY

**5 inspection queries before any action:**

| Step | Action | Reward |
|------|--------|--------|
| 1 | `SELECT rolname, rolsuper FROM pg_roles WHERE rolname='analytics_user'` | 0.01 |
| 2 | `SELECT rolname, rolsuper FROM pg_roles WHERE rolname='analytics_user'` | 0.01 |
| 3 | `SELECT grantee, privilege_type FROM information_schema.role_table_grants WHERE table_name='salaries'` | 0.01 |
| 4 | `SELECT nspname, nspacl FROM pg_namespace WHERE nspname='public'` | 0.01 |
| 5 | `SELECT rolname, rolpassword IS NOT NULL FROM pg_authid WHERE rolname='intern_user'` | 0.01 |
| 6–9 | Standard 4 security actions | 0.25→0.99 |

The model inspects every aspect of the security configuration before
making changes. This is methodical DBA practice but costs 5 extra steps.
Password: `my_secure_password123!` (includes special characters).

---

## Key findings: expert efficiency comparison

| Model | Best expert steps | Strategy |
|-------|------------------|----------|
| **Llama-4-Scout (Run 28)** | **4** | LEFT JOIN + NOT IN + CREATE AS + UPDATE |
| Gemma-3-27B-IT (Run 17) | 5 | NOT EXISTS + CREATE LIKE + INSERT SELECT |
| Qwen2.5-72B-Instruct (Runs 25–26) | 5 | EXCEPT + NOT IN + CREATE AS + UPDATE |
| gpt-4o-mini (Run 7) | 4 | ON CONFLICT + CREATE AS + UPDATE |

---

## Raw log output

```
[START] task=easy ... model=meta-llama/Llama-4-Scout-17B-16E-Instruct
[END] success=true steps=2 score=0.990
[START] task=medium ...
[STEP] step=1–9 (tables + format errors + column errors + introspection) reward=0.31
[STEP] step=10–11 (CREATE TABLE orders + INSERT orders) reward=0.50→0.61
[STEP] step=12 (CREATE VIEW, no aliases) reward=0.79
[STEP] step=13 (DROP + CREATE VIEW with aliases) reward=0.86
[END] success=true steps=13 score=0.865
[START] task=hard ...
[END] success=true steps=6 score=0.990
[START] task=expert ...
[END] success=true steps=4 score=0.990
[START] task=master ...
[STEP] step=1–5 (inspection) reward=0.01
[STEP] step=6–9 (actions) reward=0.25→0.99
[END] success=true steps=9 score=0.990
```
