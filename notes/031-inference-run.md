# Run 31 — DeepSeek-R1 via Novita (infrastructure timeout, inconclusive)

Date: 2026-04-09
Model: `deepseek-ai/DeepSeek-R1:novita`
Final scores: `{"easy": 0.990, "medium": 0.010, "hard": 0.010, "expert": 0.010, "master": 0.010}`
Aggregate: **1.030 / 5.0**

**Not a valid model evaluation.** Only the easy task completed before
the websocket connection to Novita's API died with
`keepalive ping timeout`. The remaining four tasks scored floor (0.010)
with zero steps executed. DeepSeek-R1 is a 671B MoE (~37B active) —
likely the inference latency exceeds the websocket keepalive window,
causing the connection to drop between LLM calls.

---

## Per-task analysis

### easy — index optimization (score: 0.990, 3 steps)

The one task that completed reveals a **unique approach**: inspect →
act → verify (IAV), the only model to follow this DBA workflow:

| Step | Action | Reward | Notes |
|------|--------|--------|-------|
| 1 | `SELECT * FROM pg_indexes WHERE schemaname='task_schema' AND tablename='orders'` | 0.05 | **Inspects existing indexes first** |
| 2 | `CREATE INDEX idx_orders_customer_status_date ON task_schema.orders (customer_id, status, order_date DESC)` | 0.50 | Creates the index |
| 3 | `EXPLAIN (ANALYZE, BUFFERS) SELECT * FROM task_schema.orders WHERE customer_id = 12345 AND status = 'pending' ORDER BY order_date DESC` | 0.99 | **Verifies the index works** |

Every other model runs `EXPLAIN ANALYZE` first (to diagnose), then
creates the index. DeepSeek-R1 checks what indexes exist, creates one,
then validates with `EXPLAIN ANALYZE`. This is closer to actual DBA
practice: you check what's there before adding something new.

### medium — schema migration (score: 0.010, 1 step) — TIMEOUT

```
step=1 action=SELECT column_name, data_type FROM information_schema.columns
       WHERE table_schema='task_schema' AND table_name='user_orders'
       ORDER BY ordinal_position;
```

The model's **first instinct** is to inspect the source table schema —
the exact step that every other model only discovers after 5–8 failed
column-name guesses. This suggests DeepSeek-R1 would likely avoid the
`customer_name` discovery problem entirely. But the step errors out
with `keepalive ping timeout` before the next LLM call can happen.

### hard, expert, master — all timeout (score: 0.010 each, 0 steps)

```
[DEBUG] run_task error: received 1011 (internal error) keepalive ping timeout
```

The websocket connection is dead by the time these tasks start. No
model output was generated.

---

## Infrastructure diagnosis

The `1011 (internal error) keepalive ping timeout` error indicates the
websocket between `inference.py` and the Novita API provider dropped.
Likely causes:

1. **Inference latency:** DeepSeek-R1's reasoning traces (chain-of-
   thought) can take 30–60+ seconds per response. If the websocket
   keepalive interval is shorter, the connection dies while waiting
   for the model to finish thinking.

2. **Provider instability:** Novita may have rate limits or connection
   duration caps for large models.

3. **Connection reuse:** The error cascades — once the websocket dies
   on medium step 1, all subsequent tasks fail immediately.

**To rerun:** Either increase the websocket timeout in the OpenRouter /
Novita client configuration, or switch to a provider with longer-lived
connections for reasoning models.

---

## What we can infer (limited)

Despite only one completed task, two behavioral signals stand out:

1. **Inspect-first methodology.** Both the easy task (pg_indexes before
   CREATE INDEX) and the medium task (information_schema before any
   INSERT) show the model's instinct to gather information before
   acting. No other model consistently does this from step 1.

2. **Verify-after methodology.** The easy task runs EXPLAIN ANALYZE
   *after* creating the index, not before. This is a validation step,
   not a diagnostic one — a subtle but meaningful difference in DBA
   reasoning.

If the infrastructure issues are resolved, DeepSeek-R1's inspect-first
approach could produce very efficient runs with fewer wasted steps on
column-name discovery. But this remains speculative.

---

## Updated model tier ranking

| Tier | Model | Params | Runs | Mean agg | Notes |
|------|-------|--------|------|----------|-------|
| S | gpt-4o-mini | — | 5 | 4.932 | |
| A | Gemma-3-27B-IT | 27B | 3 | 4.815 | |
| A | Llama-3.3-70B | 70B | 3 | 4.798 | |
| A | Llama-4-Scout | 17B MoE | 4 | 4.754 | |
| A | Qwen2.5-72B | 72B | 2* | 4.700 | |
| A- | gpt-3.5-turbo | — | 3 | 4.595 | |
| C | Llama-3.1-8B | 8B | 3 | 3.283 | |
| — | **DeepSeek-R1** | **671B MoE** | **1** | **1.030** | **Infrastructure failure; not scored** |

DeepSeek-R1 is excluded from ranking due to the infrastructure failure.
A valid evaluation requires resolving the websocket timeout issue and
rerunning.

---

## Raw log output

```
[START] task=easy env=postgres_dba_gym model=deepseek-ai/DeepSeek-R1:novita
[STEP] step=1 action=SELECT * FROM pg_indexes ... reward=0.05 done=false error=null
[STEP] step=2 action=CREATE INDEX idx_orders_customer_status_date ... reward=0.50 done=false error=null
[STEP] step=3 action=EXPLAIN (ANALYZE, BUFFERS) ... reward=0.99 done=true error=null
[END] success=true steps=3 score=0.990 rewards=0.05,0.50,0.99
[START] task=medium env=postgres_dba_gym model=deepseek-ai/DeepSeek-R1:novita
[STEP] step=1 action=SELECT column_name, data_type FROM information_schema.columns ... reward=0.01 done=true error=keepalive ping timeout
[END] success=false steps=1 score=0.010 rewards=0.01
[START] task=hard ... [DEBUG] run_task error: keepalive ping timeout
[END] success=false steps=0 score=0.010 rewards=
[START] task=expert ... [DEBUG] run_task error: keepalive ping timeout
[END] success=false steps=0 score=0.010 rewards=
[START] task=master ... [DEBUG] run_task error: keepalive ping timeout
[END] success=false steps=0 score=0.010 rewards=
```
