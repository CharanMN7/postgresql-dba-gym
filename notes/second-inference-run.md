# Second end-to-end `inference.py` run — annotated (gpt-4o-mini)

Date: 2026-04-08
Model: `gpt-4o-mini`
Final scores: `{"easy": 1.0, "medium": 1.0, "hard": 0.9167}`
Aggregate: **2.9167 / 3.0**

This is the second full run of the gym, this time driven by
`gpt-4o-mini`. Compared with the prior `gpt-4o` run (2.865/3.0),
mini *won* on aggregate — beating 4o on the medium task and losing
only a sliver of the hard task to a quirk of the auto-`done` logic.

---

## Headline

| Task   | gpt-4o    | gpt-4o-mini  | Δ        |
|--------|----------:|-------------:|---------:|
| easy   | 1.000     | 1.000        | =        |
| medium | 0.865     | **1.000**    | **+0.135** |
| hard   | **1.000** | 0.9167       | −0.0833 |
| total  | 2.865     | **2.9167**   | +0.0517  |

mini is *not* a worse agent than 4o on this benchmark. It's just
worse-shaped: it solved the medium task more carefully, but
self-terminated the hard task one GUC too early because it crossed
the 0.85 success threshold mid-fix.

---

## Task 1 — Index Optimization (easy) — 1.0

Identical strategy to the 4o run:

1. `EXPLAIN (ANALYZE, BUFFERS) …` — diagnostic, reward `0.05`.
   The `BUFFERS` flag is a nice touch mini added (4o didn't); it
   doesn't affect the grader, just gives the agent a fuller picture
   of what the planner is doing.
2. `CREATE INDEX … (customer_id, status, order_date DESC)` — reward
   `1.0`. Notes: `baseline=4.02ms current=0.07ms ratio=55.08x`.

The two runs measured slightly different baselines (3.73 vs 4.02 ms)
and ratios (52.86× vs 55.08×) — both small-table jitter, both well
above the 10× cap, both clamped to 1.0 by `min(1.0, …)`. The
optimal-index bonus fired in both cases.

**Verdict:** Easy is essentially a tied benchmark for any model that
knows what a composite index is.

---

## Task 2 — Schema Migration (medium) — 1.0

This is where mini *outperformed* 4o. mini's path was bumpier — it
made two column-name typos before discovering the schema — but the
end state was cleaner.

| # | Action                                                               | Reward    | Note                                                |
|---|----------------------------------------------------------------------|----------:|-----------------------------------------------------|
| 1 | `CREATE TABLE customers (… UNIQUE NOT NULL …)`                        | **0.3125**| Schema half + constraints                           |
| 2 | `CREATE TABLE orders (id SERIAL, customer_id INT REFERENCES customers, order_date **TIMESTAMP**, amount **DECIMAL**, status VARCHAR)` | **0.5000** | Schema complete                                |
| 3 | `INSERT INTO customers … SELECT name, email, address …`               | 0.5000    | **Errored**: column `name` doesn't exist (typo)     |
| 4 | `… SELECT user_name, user_email, user_address …`                      | 0.5000    | **Errored again**: column `user_name` doesn't exist |
| 5 | `SELECT * FROM task_schema.user_orders LIMIT 5`                       | 0.5000    | Discovery: actual columns are `customer_name`, `customer_email`, `customer_address` |
| 6 | `INSERT INTO customers … SELECT customer_name, …`                     | 0.5000    | 200 rows inserted                                   |
| 7 | `INSERT INTO orders … SELECT c.id, u.order_date, u.amount, u.status FROM user_orders u JOIN customers c ON u.customer_email=c.email` | **0.7500** | **Full data sub-rubric** — note observation has *no* data complaints, only the missing view |
| 8 | `CREATE VIEW user_orders_view AS …`                                   | **1.0000** | View complete                                       |

### Why mini scored higher than 4o on the data sub-rubric

This one is interesting and corrects a hypothesis from the first
run's note. I previously guessed 4o lost the spot-check because of
`SERIAL`-vs-`row_id` identity mismatch. That guess was almost
certainly **wrong**. Look at the two `CREATE TABLE orders` shapes:

| Run         | `order_date` type | `amount` type |
|-------------|-------------------|---------------|
| gpt-4o      | `DATE`            | `NUMERIC`     |
| gpt-4o-mini | `TIMESTAMP`       | `DECIMAL`     |

The seed `user_orders.order_date` is a *timestamp* (the seed file
generates values like `'2024-01-01 00:00:00+00' + (i * INTERVAL '1 minute')`,
so almost every row has a non-midnight time-of-day component).

- **4o cast it down to `DATE`**, truncating the time-of-day. The
  spot-check then compared `view.order_date` (a `DATE`) to
  `user_orders.order_date` (a `TIMESTAMP`) and got a mismatch on 9 of
  10 rows — only the lone `00:00:00` row matched. Hence "matched
  1/10 spot-check rows" → ~0.115 of 0.25 on the data sub-rubric →
  total 0.865.
- **mini kept it as `TIMESTAMP`**, so the spot-check compared apples
  to apples and matched all 10 rows → full 0.25 → total 1.0.

This is a *real* model-quality signal. mini happened to pick the more
information-preserving column type without being asked, and it paid
off by 0.135 reward. The grader is doing exactly what a good DBA
review would do — penalizing lossy migrations.

### What this means for the grader

The grader is fine — possibly *too* good, in the sense that mini
basically got rewarded for being lucky (or systematically careful)
about a type choice. If we wanted the medium task to be more about
*structural* migration quality and less about *typing nuance*, we
could weaken the spot-check to compare on a tuple of
`(customer_email, status, amount)` only. But honestly, "preserve the
types" *is* a real DBA skill, so I'd leave it.

### Observability win

Notice how gracefully mini recovered from its column-name typos: it
errored twice, then ran a single discovery query (`SELECT * … LIMIT 5`),
read the actual column names off the observation, and continued. This
is the "step never raises, errors come back as observations" design
working exactly as intended — the agent learned from the error text
the same way a human would.

---

## Task 3 — Performance Diagnosis (hard) — 0.9167

Same strategy as 4o on the first six steps, then a clever
multi-statement trick — and a self-induced premature termination.

| # | Action                                                          | Reward | Note                                                 |
|---|-----------------------------------------------------------------|-------:|------------------------------------------------------|
| 1 | `EXPLAIN ANALYZE SELECT * FROM events WHERE user_id = 42`       | 0.0000 | Discovery: Seq Scan on events, 17.5ms                |
| 2 | `CREATE INDEX idx_events_user_id …`                             | 0.1250 | indexes: half                                        |
| 3 | `CREATE INDEX idx_events_event_type …`                          | 0.2500 | indexes: full (0.25)                                 |
| 4 | `SELECT … FROM pg_stat_activity WHERE state='idle in transaction'` | 0.2500 | Discovery: blocker pid=1813                          |
| 5 | `SELECT pg_terminate_backend(1813)`                             | 0.5000 | blocker: full (0.25)                                 |
| 6 | `VACUUM FULL task_schema.bloated_logs`                          | 0.7500 | bloat: full (0.25, via size branch)                  |
| 7 | `ALTER SYSTEM SET work_mem = '4MB'; **SELECT pg_reload_conf()**` | **0.8333** | gucs: 1/3 (~0.0833) — multi-statement!              |
| 8 | `ALTER SYSTEM SET random_page_cost = '2.0'; SELECT pg_reload_conf()` | **0.9167** | gucs: 2/3 (~0.1667) — env auto-flips `done=true`     |

### Two important things happened on this task

**1. mini used the multi-statement path on its own.**
On steps 7 and 8, mini bundled `ALTER SYSTEM SET …; SELECT pg_reload_conf();`
into a single action. This exercises the `sqlparse.split` path we
added to fix Postgres's "ALTER SYSTEM cannot run inside a transaction
block" implicit-tx behavior. mini did this without prompting,
presumably because it knew empirically that `ALTER SYSTEM` without a
reload is a no-op. 4o never figured this out — it sent each ALTER as
a separate step and only reloaded once at the end. Mini's approach is
strictly more efficient (one round-trip per GUC instead of two).

**2. The 0.85 success threshold ate the third GUC.**
After step 8, the cumulative reward hit 0.9167, which is `>= 0.85`,
so `BaseTask.is_complete()` returned `true` and the env flipped
`DBAState.done = true` automatically. The harness saw `done=true` in
the response, broke out of the inner loop, printed `[END]`, and moved
on — even though there was still one GUC (`effective_cache_size`)
unset. mini never got the chance to fix the last 0.0833.

This is a *design tradeoff*, not a bug:

- **Pro:** Auto-done lets agents stop the moment they've genuinely
  succeeded, which keeps total step counts (and hence judge wall-time
  and token bills) down.
- **Con:** It clamps the upper-bound score at whatever threshold the
  agent first crosses, even if the agent had momentum to push higher.

For benchmark fairness, this is fine — every model is judged against
the same threshold. But if we wanted to reward models that *perfect*
each task, we could:

1. Only auto-done on `score == 1.0` instead of `score >= 0.85`, **or**
2. Have the harness ignore the env's `done` and run until either
   `MAX_STEPS` or the agent's own `action.done = true`, **or**
3. Lift `SUCCESS_THRESHOLD` closer to `1.0` for the hard task only.

I'd lean toward option 3 — bump hard's threshold to `0.95` so the
agent has to actually fix all four problems. Easy and medium can stay
at `0.85` since their scoring is shape-friendly. **No code changes
unless you want them.**

---

## Side-by-side: gpt-4o vs gpt-4o-mini

| Dimension                     | gpt-4o                              | gpt-4o-mini                              |
|-------------------------------|-------------------------------------|------------------------------------------|
| Aggregate                     | 2.865                               | **2.917**                                |
| Easy steps                    | 2                                   | 2                                        |
| Medium steps                  | 7                                   | 8 (two error-recovery steps)             |
| Hard steps                    | 10                                  | 8                                        |
| Used multi-statement?         | No                                  | **Yes** (steps 7–8 of hard)              |
| Picked lossless types in medium? | No (DATE for timestamp)         | **Yes** (TIMESTAMP)                      |
| Errored mid-task?             | No                                  | Yes (twice on medium, recovered)         |
| Discovery-step quality        | Good                                | Good (added `BUFFERS` to EXPLAIN)        |
| Auto-`done` cost the agent reward? | No                             | **Yes** (lost 0.0833 on hard)            |

### What this comparison validates about the env

1. **The grader is sensitive to real DBA skill, not just keyword
   matching.** mini's lossless type choice on medium was the deciding
   factor between 0.865 and 1.0. A keyword-match grader couldn't tell
   the difference.

2. **Error-as-observation is mission-critical.** mini failed twice
   on column names and recovered gracefully. If `step()` had raised
   instead of returning the error in `obs.error`, mini would have
   crashed the episode at step 3 and scored 0.5 for the whole task.

3. **Multi-statement execution is being used in the wild.** The
   `sqlparse.split` plumbing isn't dead code; mini exercised it on
   its own initiative.

4. **Auto-done is a real benchmark variable.** It can hand a smaller
   model a higher *aggregate* score against a larger model while
   simultaneously *capping* its hard-task score. If the hackathon
   judge cares about total reward (the most common case), this
   benefits agents that are quick to cross 0.85 and terminates them
   before they can over-step.

---

## What I'd change after seeing this

Nothing critical. Two cosmetic ideas:

1. **Bump the hard task `SUCCESS_THRESHOLD` to ~0.95.** Right now it
   penalizes models that *would have* gotten 1.0 if not for the
   auto-done. Hard is the showcase task; let it run.
2. **Add a one-line breadcrumb in the medium task description**
   nudging agents to think about column-type fidelity. Something like
   "match the original column types as faithfully as you can." This
   would let smaller-model runs have a fighting chance at the perfect
   1.0 without trivializing the task.

Neither is a blocker for submission. The fact that the same gym
produced two materially different score profiles for two related
models — and that *both score profiles are sensible* — is exactly
what you want from a benchmark.

---

## tl;dr

`gpt-4o-mini` actually beat `gpt-4o` on aggregate (2.917 vs 2.865).
It lost the perfect score on hard only because it crossed the 0.85
success threshold and the env auto-terminated mid-fix. It won the
medium task outright because it picked `TIMESTAMP` instead of `DATE`,
preserving the time-of-day component that the spot-check compared
against. Multi-statement SQL, error-recovery-from-observation, and
the type-fidelity-sensitive grader all proved their worth on this
run.
