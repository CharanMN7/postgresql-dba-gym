---
title: PostgreSQL DBA Gym
emoji: 🐘
colorFrom: indigo
colorTo: blue
sdk: docker
app_port: 8000
pinned: false
license: mit
tags:
  - openenv
  - postgres
  - dba
  - sql
  - tool-use
---

# PostgreSQL DBA Gym

A live PostgreSQL 16 training environment for AI agents — built on
[OpenEnv](https://github.com/meta-pytorch/openenv) and packaged for Hugging
Face Spaces. Agents practice three real database administration tasks
against a real Postgres instance running inside the same container, and
every reward is computed deterministically by inspecting `pg_catalog`,
`information_schema`, and `pg_stat_*`. There is **zero LLM-as-judge**.

## Why DBA?

Most agentic SQL benchmarks stop at "write a SELECT". Real database
work — the work that pages humans at 3am — looks nothing like that. It
looks like:

- "This query was 50ms yesterday and is 8 seconds today. Find out why."
- "We're moving from a denormalized blob to a real schema without
  breaking the read path."
- "The cluster is on fire. There are four things wrong simultaneously.
  Triage and fix in any order."

Those are exactly the three tasks in this environment, and they all
require the agent to *read database state*, decide what to do, *issue
SQL*, and *verify the fix worked* — the full DBA loop, against ground
truth, with zero rubric handwaving.

## Tasks

| ID | Name | Skills exercised |
|---|---|---|
| `easy` | Index Optimization | EXPLAIN ANALYZE reading, composite-index design, verifying speedup |
| `medium` | Schema Migration | Normalization, FK/unique/NOT NULL constraints, backward-compatible views |
| `hard` | Performance Diagnosis | Multi-symptom triage: missing indexes, bloat (VACUUM FULL), GUC tuning (`ALTER SYSTEM`), `pg_terminate_backend` on a stuck blocker |

Each task ships with a deterministic seed, a per-step grader, and a
sub-rubric `grading_breakdown` so the agent can see exactly which slice
of the task is still 0 and target it.

## Architecture

Single Docker container based on `python:3.11-slim`:

```
┌──────────────────────────── container ────────────────────────────┐
│  PostgreSQL 16 (apt.postgresql.org)        FastAPI on uvicorn      │
│        listening on 127.0.0.1:5432  ◄─────  server.app:app         │
│                                              │                     │
│                                              ▼                     │
│           ┌─── PostgresDBAEnvironment (singleton) ───┐             │
│           │  • ThreadedConnectionPool  (psycopg2)    │             │
│           │  • current_task ∈ {easy, medium, hard}   │             │
│           │  • DBAState.task_data scratch            │             │
│           └──────────────────────────────────────────┘             │
└────────────────────────────────────────────────────────────────────┘
                              ▲
                              │ HTTP (port 8000)
                              ▼
                  Agent (e.g. inference.py)
```

A single uvicorn worker is **mandatory** — the env is a singleton with
in-process state (the connection pool, the current task, and the Task 3
idle-blocker thread).

### Key files

```
models.py                             Pydantic DBAAction / DBAObservation / DBAState
client.py                             Typed EnvClient subclass (optional)
pyproject.toml                        Project metadata + dependencies (uv-compatible)
openenv.yaml                          Minimal OpenEnv spec (6 keys)
server/app.py                         create_app(...) wiring + /tasks and /grade extras
server/postgres_dba_gym_environment.py  PostgresDBAEnvironment class
server/db.py                          Connection pool + psql meta-command translator
server/tasks/base.py                  BaseTask ABC + GradingResult
server/tasks/index_optimization.py    Task 1 grader
server/tasks/schema_migration.py      Task 2 grader
server/tasks/performance_diagnosis.py Task 3 grader (with idle-blocker thread)
server/Dockerfile                     python:3.11-slim + Postgres 16, runs as UID 1000
sql/seed_*.sql                        Deterministic per-task seeds
scripts/start.sh                      Container entrypoint: pg_ctl → bootstrap → uvicorn
inference.py                          Hackathon judge harness (OpenAI-compatible)
demo.py                               Hand-crafted scripted demo (no LLM)
```

## HTTP API

Standard OpenEnv routes (auto-registered by `openenv-core`'s
`create_app`):

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/reset` | Reset to a fresh episode. JSON body: `{"task": "easy"}`. |
| `POST` | `/step` | Execute one action. JSON body: `{"action": {"sql": "...", "done": false}}`. |
| `GET`  | `/state` | Inspect the current `DBAState`. |
| `GET`  | `/health` | Liveness probe (used by Docker `HEALTHCHECK`). |
| `GET`  | `/schema` | Pydantic schemas for action/observation/state. |
| `GET`  | `/docs` | FastAPI auto-generated OpenAPI docs. |

Plus two convenience routes:

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/tasks` | List all registered tasks with descriptors. |
| `GET` | `/grade/{task_id}` | Re-run the active task's grader on demand. |

## How to run

### Prerequisites

- **Docker** — required for the recommended path and for Hugging Face Space parity.
- **Python 3.11+** — required for local development outside Docker.
- **[`uv`](https://docs.astral.sh/uv/)** (recommended) or `pip` — for dependency management.
- **OpenAI API key** — only required for running the baseline agent (`inference.py`).
  The hackathon spec re-uses the env var `HF_TOKEN` to carry the OpenAI key.

### Local development (Docker Compose — recommended)

No Postgres or Python needed on the host. Everything — server, demo,
inference, smoke tests — runs inside the container. Env vars are
loaded from `.env` by `docker compose`, nothing is baked into the image.

```bash
# 1. Configure
cp .env.example .env
# edit .env: set HF_TOKEN to your OpenAI API key

# 2. Build & start
make build
make up

# 3. Verify
make smoke         # curl-based health check
make logs          # follow server logs

# 4. Run things
make demo          # hand-crafted winning solution, no LLM
make inference     # baseline OpenAI agent on all 3 tasks
make shell         # drop into the container

# 5. Tear down
make down
```

Run `make help` for the full target list (build, up, down, restart,
logs, shell, demo, inference, smoke, validate, clean).

### Advanced: raw `docker build` / `docker run`

If you don't want Compose, you can drive the same image directly. This
is the exact path Hugging Face Spaces uses.

```bash
# Build the image (repo root is the build context)
docker build -f server/Dockerfile -t pg-dba-gym .

# Run it
docker run --rm -p 8000:8000 --env-file .env pg-dba-gym
```

The container bundles PostgreSQL 16 and runs as UID 1000. First-time
boot takes 3-5 seconds while `start.sh` brings up Postgres and
bootstraps the `dba_gym` database.

### Running the baseline agent

`inference.py` drives the environment with an OpenAI-compatible LLM
and emits a structured log block per task that matches the hackathon
judge's parser.

```bash
# 1. Copy the env template and fill it in
cp .env.example .env
# edit .env to set HF_TOKEN=sk-...   (your OpenAI API key)

# 2. Export the required variables
export $(grep -v '^#' .env | xargs)
export ENV_URL=http://localhost:8000

# 3. Run against a server you've already started
python inference.py
```

Required environment variables:

| Variable        | Example                        | Purpose                                  |
|-----------------|--------------------------------|------------------------------------------|
| `HF_TOKEN`      | `sk-...`                       | OpenAI API key (name mandated by hackathon spec) |
| `MODEL_NAME`    | `gpt-4o-mini`                  | LLM identifier                           |
| `API_BASE_URL`  | `https://api.openai.com/v1`    | OpenAI-compatible base URL               |
| `ENV_URL`       | `http://localhost:8000`        | Running environment server URL           |

For the judge path, set `IMAGE_NAME=pg-dba-gym` instead of `ENV_URL` —
`inference.py` will spin up a fresh container via
`GenericEnvClient.from_docker_image(IMAGE_NAME)`.

### Running the hand-crafted demo

`demo.py` runs a scripted solution through the same environment with
no LLM involved. Useful to sanity-check a fresh build.

```bash
export ENV_URL=http://localhost:8000
python demo.py
```

### Deployment to Hugging Face Spaces

Two supported paths:

**(a) Official OpenEnv push (recommended):**

Requires the `openenv` CLI on the host — install it once with
`pipx install "openenv-core[core]"` (or `uv tool install "openenv-core[core]"`
if you already use `uv`). `make validate` runs the same check inside
the container if you'd rather not install anything on the host.

```bash
# Validate layout first
openenv validate

# Push to a Space (creates it if missing)
openenv push --repo-id your-username/postgres-dba-gym
```

**(b) `huggingface-cli` fallback via `deploy.sh`:**

```bash
export HF_TOKEN=hf_...              # a Hugging Face write token
export HF_SPACE=your-username/postgres-dba-gym
./deploy.sh
```

Both paths upload the repo as a Docker-SDK Space; `scripts/start.sh`
brings up Postgres and uvicorn on port 8000 inside the Space.

Once deployed, run the baseline agent against it:

```bash
export API_BASE_URL=https://api.openai.com/v1
export MODEL_NAME=gpt-4o-mini
export HF_TOKEN=sk-...
export ENV_URL=https://your-username-postgres-dba-gym.hf.space
python inference.py
```

### Log output format

`inference.py` emits a structured log block per task that matches the
hackathon judge's parser exactly:

```
[START] task=easy env=postgres_dba_gym model=gpt-4o-mini
[STEP] step=1 action=SELECT version(); reward=0.00 done=false error=null
[STEP] step=2 action=CREATE INDEX ... reward=1.00 done=true error=null
[END] success=true steps=2 score=1.000 rewards=0.00,1.00
```

- `reward` and the entries in `rewards` are formatted to 2 decimals.
- `score` is formatted to 3 decimals.
- `done` and `success` are lowercase `true`/`false`.
- `error` is either the flattened error string or the literal `null`.
- `[END]` is always emitted, even if the episode throws mid-run.

## Determinism

All seeds are written without `random()` — row values are derived from
deterministic integer hashes (e.g. `((i * 2654435761) % 50000) + 1`)
and timestamps are anchored at fixed wall-clock origins. This means:

- Two `/reset` calls with the same task produce byte-identical state.
- `baseline_ms` measurements use a discard-then-median strategy and are
  cached on `DBAState.task_data` so re-grading uses the same baseline.
- A given fix produces the same final reward across runs (within
  measurement noise on Task 1's speedup ratio).

## Grading

Every task returns a `GradingResult` with:

- **`score`** in `[0.0, 1.0]` — the headline reward.
- **`breakdown`** — a dict of sub-rubric scores so the agent can see
  what's still missing.
- **`notes`** — optional human-readable hints (shown after the SQL output
  when grading completes).

Sub-rubrics are weighted to keep the overall scale at 1.0. Tasks 2 and 3
use four equal-weighted sub-rubrics (0.25 each); Task 1 combines a
multiplicative speedup score with optional optimal-index bonuses.

The `SUCCESS_THRESHOLD` (default `0.85`) defines when the env auto-flips
`done=true`. Agents may also self-declare done by setting
`action.done = true`.

## Safety & isolation

- The agent talks to a `dba` superuser, but the schema is wiped and
  recreated on every `/reset`, so there is nothing to leak between
  episodes.
- `ALTER SYSTEM RESET ALL; SELECT pg_reload_conf();` runs on every
  reset to undo any GUC tweaks from the previous episode.
- Task 3's idle blocker runs on a *non-pool* connection and is
  forcibly terminated in `teardown()`.
- Each step runs with `statement_timeout = 15s` so a runaway query
  cannot hang the episode.
- `step()` never raises — psycopg2 errors are captured and returned in
  the observation's `error` field, so the agent learns to fix typos
  rather than crash the server.

## Baseline scores

Both runs used `inference.py` with temperature 0.2 and default
`max_steps = 25`. Scores are per-task reward in `[0, 1]` at
episode end.

| Model         | easy | medium | hard   | aggregate |
|---------------|-----:|-------:|-------:|----------:|
| `gpt-4o`      | 1.00 | 0.865  | 1.000  | 2.865 / 3.0 |
| `gpt-4o-mini` | 1.00 | 1.000  | 0.9167 | 2.917 / 3.0 |

Notes:

- `gpt-4o-mini` outperformed `gpt-4o` on aggregate. The margin came
  entirely from the medium task, where `gpt-4o` picked `DATE` for the
  `order_date` column (truncating the time component) while `gpt-4o-mini`
  picked `TIMESTAMP`. The grader's spot-check compares against the
  original timestamps, so lossy type choices are penalized.
- `gpt-4o-mini` lost 0.0833 on the hard task because it crossed the
  0.85 auto-`done` threshold mid-fix (after setting 2 of 3 GUCs) and
  the env terminated the episode before it could apply
  `effective_cache_size`.
- Both runs validated: deterministic seeds, `sqlparse`-based
  multi-statement execution, error-as-observation recovery, and
  grading sub-rubric visibility via `grading_breakdown`.

Per-run annotated traces are in `notes/first-inference-run.md` and
`notes/second-inference-run.md`.

## Requirements

```
openenv-core>=0.2.3
fastapi>=0.115.0
uvicorn[standard]>=0.27.0
psycopg2-binary>=2.9.9
pydantic>=2.7.0
openai>=1.30.0
requests>=2.31.0
sqlparse>=0.5.0
```

## License

MIT.
