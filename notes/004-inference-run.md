# Fourth end-to-end `inference.py` run — annotated (gpt-4o-mini, post threshold bump)

Date: 2026-04-08
Model: `gpt-4o-mini`
Final scores: `{"easy": 1.0, "medium": 0.920, "hard": 1.0}`
Aggregate: **2.920 / 3.0**

This is the fourth full run, the third one driven by `gpt-4o-mini`,
and the first one after bumping
`server/tasks/performance_diagnosis.py`'s `SUCCESS_THRESHOLD` from
`0.85` to `0.95`. The threshold change did exactly what it was
supposed to. The medium task did exactly the *thing we predicted it
would do*. And easy got even tighter.

---

## Headline — four runs side by side

| Task   | Run 1 (4o)       | Run 2 (mini)     | Run 3 (mini)     | **Run 4 (mini)**   |
|--------|-----------------:|-----------------:|-----------------:|-------------------:|
| easy   | 1.000 / 2 steps  | 1.000 / 2 steps  | 1.000 / 2 steps  | **1.000 / 1 step** |
| medium | 0.865 / 7 steps  | 1.000 / 8 steps  | 0.920 / 6 steps  | **0.920 / 6 steps** |
| hard   | 1.000 / 10 steps | 0.917 / 8 steps  | 0.917 / 8 steps  | **1.000 / 9 steps** |
| total  | 2.865            | **2.917**        | 2.837            | **2.920**          |

This is now the highest aggregate of any run, and the first time
mini has hit a perfect hard. It edges past run 2's 2.917 by a hair,
not because mini is doing anything new, but because the threshold
unlocked the score it was always *capable* of.

---

## Task 1 — Index Optimization (easy) — 1.0 in **one step**

| # | Action | Reward | Note |
|---|--------|-------:|------|
| 1 | `CREATE INDEX idx_customer_status_order_date ON task_schema.orders (customer_id, status, order_date DESC)` | **1.00** | First-try, no diagnostic |

Mini skipped the `EXPLAIN (ANALYZE, BUFFERS)` discovery step it had
done in runs 2 and 3 and went straight to the optimal composite
index. This is the cleanest possible easy run — one round trip,
1.0 reward, `done=true` immediately.

There's no model improvement here; mini is sampling differently. But
it's a useful confirmation that the easy task's success threshold and
shaped reward are *not* gating-on-discovery-step-required — a
zero-discovery solve is fully accepted.

---

## Task 2 — Schema Migration (medium) — 0.920

This run reproduces the exact failure mode from run 3, in the exact
same number of steps, with the exact same step-by-step rewards, with
the exact same root cause. This is the third datapoint we needed.

### Step-by-step

| # | Action | Reward | Note |
|---|--------|-------:|------|
| 1 | `CREATE TABLE customers (id SERIAL, name NOT NULL, email UNIQUE NOT NULL, address)` | 0.31 | Schema half + 3 of 4 constraints |
| 2 | `CREATE TABLE orders (id SERIAL, customer_id REFERENCES customers, order_date TIMESTAMP, amount DECIMAL, status VARCHAR)` | 0.50 | `TIMESTAMP` + `DECIMAL` again — lossless types preserved |
| 3 | `INSERT INTO customers (name, email, address) SELECT DISTINCT name, email, address FROM user_orders` | 0.50 | **Errored** — `column "name" does not exist`. Same typo as runs 2 and 3 |
| 4 | `… SELECT DISTINCT customer_name, customer_email, customer_address …` | 0.50 | Recovered |
| 5 | `INSERT INTO orders … SELECT c.id, u.order_date, u.amount, u.status … JOIN customers c ON u.customer_email = c.email` | 0.75 | +0.25 = full data sub-rubric |
| 6 | `CREATE VIEW user_orders_view AS SELECT c.name, c.email, c.address, o.order_date, o.amount, o.status FROM customers c JOIN orders o ON c.id = o.customer_id` | **0.92** | View +0.17 — **same column-alias miss as run 3** |

Reward sequence and final score are bit-for-bit identical to run 3.
Two consecutive runs of the same model on the same task have now hit
0.92 via the same view-aliasing failure. With three medium runs
total for mini, the count is now **2 × 0.92 vs 1 × 1.0** — the run
2 perfect score is starting to look like the outlier, not the steady
state.

### What this confirms

The "model output stochasticity" diagnosis from the run-3 note holds
up. Three observations:

1. **The view-alias bug is reproducible.** Two runs in a row,
   character-for-character the same `CREATE VIEW c.name, c.email,
   c.address …`. This is not random sampling — mini has a
   *systematic* preference for the un-prefixed names because the
   normalized table genuinely calls them `name`, `email`, `address`.
   Asking it to alias them on the way out of the view is fighting
   the natural shape of the schema it just created.

2. **Run 2 was the lucky one, not run 3.** I had it backwards in
   the run-3 note when I framed run 3 as a "regression". The
   *median* mini score on medium is 0.92, and run 2's 1.0 was the
   outlier where mini happened to alias correctly.

3. **The grader is doing exactly what it's designed to do.** Mini's
   migration is structurally fine — the data is normalized, the
   constraints are right, the spot-checks pass — but the
   backward-compat view is *not* backward-compatible. A real DBA
   review would flag the same thing. The grader is correctly
   refusing to give credit for "the view exists" while also failing
   "the view exposes the original column names."

### Why I'm *not* recommending a fix this time

Two pulls in two different directions:

- The run-3 note suggested adding a one-liner to the task
  description naming the required view columns. The user
  explicitly declined that change. Standing by that decision —
  if we hint the column names, we're handing the agent the
  answer to one of the four sub-rubrics.
- We could relax the grader to accept either `name` or
  `customer_name`. But "the migration must preserve the original
  table's column names in the backward-compat view" is a *real
  requirement* of a backward-compat migration, and weakening
  it would cheapen the task.

So the medium task stays exactly as it is, and mini's expected
score on it is ~0.92 ± noise. That's fine.

---

## Task 3 — Performance Diagnosis (hard) — **1.000** (the threshold bump worked)

This is the punchline. Same eight-step strategy mini has now
executed three times — and on the ninth step, with the threshold
raised from 0.85 to 0.95, mini got the chance it never had before
to land the third GUC.

| # | Action | Reward | Note |
|---|--------|-------:|------|
| 1 | `EXPLAIN ANALYZE SELECT * FROM events WHERE user_id = 42` | 0.00 | Discovery |
| 2 | `CREATE INDEX idx_events_user_id ON task_schema.events (user_id)` | 0.12 | indexes: half |
| 3 | `CREATE INDEX idx_events_event_type ON task_schema.events (event_type)` | 0.25 | indexes: full |
| 4 | `SELECT pid, application_name, state, query FROM pg_stat_activity WHERE state = 'idle in transaction'` | 0.25 | Discovery: blocker pid=93 |
| 5 | `SELECT pg_terminate_backend(93)` | 0.50 | blocker: full |
| 6 | `VACUUM FULL task_schema.bloated_logs` | 0.75 | bloat: full |
| 7 | `ALTER SYSTEM SET work_mem = '4MB'; SELECT pg_reload_conf()` | **0.83** | gucs 1/3 — multi-statement bundle |
| 8 | `ALTER SYSTEM SET random_page_cost = '2.0'; SELECT pg_reload_conf()` | **0.92** | gucs 2/3 — **previously this was the auto-done step** |
| 9 | `ALTER SYSTEM SET effective_cache_size = '512MB'; SELECT pg_reload_conf()` | **1.00** | gucs 3/3 — perfect |

Compare with runs 2 and 3:

- Steps 1–8 are **identical** to runs 2 and 3 in action shape and
  reward sequence (modulo the blocker pid changing per restart).
  This is a deterministic mini strategy.
- In runs 2 and 3, step 8 ended the episode because the cumulative
  reward (0.92) crossed the old `SUCCESS_THRESHOLD = 0.85` and the
  env auto-flipped `done=true`.
- In run 4, step 8's reward is still 0.92, but now `0.92 < 0.95`,
  so `BaseTask.is_complete()` returns `false` and the loop
  continues. Mini takes its ninth step, sets the third GUC, reloads,
  hits 1.0 exactly, and the env flips `done=true` on score-max.

### What this proves about the threshold change

1. **The bump did exactly the thing it was supposed to do** —
   nothing more, nothing less. Mini's strategy is unchanged.
   It's just no longer being interrupted mid-fix. Easy and medium
   are unaffected (their thresholds stayed at 0.85, and neither
   has a "ceiling" problem in the first place).
2. **No regressions.** I was mildly worried that raising the
   threshold could push mini into wandering behavior on the gap
   between 0.92 and 0.95 — looking for *some* extra reward to
   close the gap. It didn't. Mini knew the next thing to do was
   the third GUC, did it, and stopped. The agent's stop condition
   here is *score == 1.0*, not threshold-crossing.
3. **The auto-done logic is still useful.** The episode still
   ends on the correct step (step 9, `done=true`), so the harness
   doesn't waste tokens on a wasted final step. The threshold
   isn't disabled — it's just been moved to where it doesn't
   *prematurely* end a run that could go higher.

If anything, this validates that the auto-done design is
*correct* — it works as a "stop when done" mechanism with the
right threshold, and the right threshold was 0.95 not 0.85.

---

## Run-over-run variance (updated)

| Source of variance              | Easy                | Medium                                | Hard                              |
|---------------------------------|---------------------|---------------------------------------|-----------------------------------|
| Grader RNG                      | none                | none                                  | none                              |
| Timing jitter (shaped reward)   | n/a (no diag step this run) | none on final score          | none on final score               |
| Model output stochasticity      | **±1 step** (skipped diagnostic) | **±0.08** (2/3 runs missed view alias, 1/3 hit it) | **none** across 3 mini runs |
| Auto-done ceiling               | n/a                 | n/a                                   | **resolved by threshold bump**    |

Updates from the run-3 note:

- **Hard variance is now zero.** Three mini runs in a row used
  the same eight steps with the same rewards through step 8. Run 4
  added a single step that was unblocked by the threshold change.
  Mini's hard-task strategy is the most reproducible thing in this
  benchmark.
- **Medium variance is now empirically two-thirds 0.92, one-third
  1.0.** Mini's expected medium score is closer to ~0.95 than to
  either 0.92 or 1.0. With three trials I won't pretend that's a
  precise estimate, but the point is that "mini scores 1.0 on
  medium" was a per-trial accident, not a model property.
- **Easy variance is now ±1 step on the path, but ±0 on the
  score.** Mini sometimes diagnoses, sometimes doesn't, always
  picks the right index, always lands 1.0.

---

## What this run proves about the benchmark itself

1. **The threshold bump is correct.** It's the kind of change you
   only know is right after seeing it work, and it worked exactly
   as predicted. The hard task's ceiling wasn't a model limitation,
   it was an env configuration choice that happened to coincide
   with mini's natural stopping point. Lifting the configuration
   freed the score that was already there.
2. **gpt-4o-mini's *real* aggregate ceiling on this benchmark is
   ≈2.92, not 2.917.** With easy=1.0 (deterministic),
   medium≈0.95 (stochastic, occasionally 1.0), and hard=1.0 now
   reachable, the post-fix expected aggregate over many trials is
   somewhere in the 2.92–2.95 range. Run 4 is at the *low end* of
   that band — if mini had aliased the view correctly, it would
   have been 3.000.
3. **A 3.0 / 3.0 run is now possible from gpt-4o-mini.** Before
   the threshold bump, mini was structurally locked out of a
   perfect aggregate (best case: easy 1.0 + medium 1.0 + hard
   0.917 = 2.917). After the bump, the only thing standing
   between mini and a perfect 3.0 is the medium-task view-alias
   stochasticity — i.e., one round of Russian roulette with the
   `CREATE VIEW` column names. This is an interesting property
   to advertise about the benchmark: it's now beatable, but only
   by a model that gets *every* sub-rubric right *every* time.
4. **The four runs now form a useful sanity baseline.** Easy
   should always be 1.0. Hard for mini should now always be 1.0
   (with the threshold fix) in ≤9 steps. Medium for mini is the
   stochastic line item to watch — anything significantly under
   0.92 is a regression, anything at 1.0 is a lucky alias.

---

## Code changes in this run

None. The threshold bump from the run-3 note is what *enabled*
this run's hard-task perfect, but the change itself was applied
before the run, not during analysis. No further code changes are
needed off the back of this run.

---

## tl;dr

`gpt-4o-mini` ran the gym a third time and scored **2.920 / 3.0**,
the highest aggregate of any run so far and the first time mini
has hit a perfect hard task. The hard improvement (0.917 → 1.000)
is entirely the result of bumping
`server/tasks/performance_diagnosis.py:133`'s `SUCCESS_THRESHOLD`
from `0.85` to `0.95`, which let mini take a ninth step and set
the third GUC instead of being auto-terminated at 0.92. The
medium task hit 0.92 again with the **exact same view-aliasing
failure** as run 3 — `c.name, c.email, c.address` instead of
`customer_name, customer_email, customer_address` — confirming
that the view-alias miss is the steady state for mini and run 2's
1.0 was the outlier. Easy got even tighter at one step
(no diagnostic). The benchmark is now beatable end-to-end by an
LLM — mini's only remaining gap to 3.0 is a single `CREATE VIEW`
line that it gets right ~1 in 3 times. No further code changes.
