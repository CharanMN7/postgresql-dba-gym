"""Demo — PostgreSQL DBA Gym end-to-end, no LLM required.

Walks through all three tasks (easy / medium / hard) with hand-crafted SQL
actions that are known to score 1.0, so a reviewer can see the env work in
about 30 seconds without needing an API key.

Usage
-----
    # Terminal 1: start the environment
    docker run --rm -p 8000:8000 pg-dba-gym

    # Terminal 2: run this demo
    python demo.py

    # Optional: point at a remote Space
    ENV_URL=https://your-space.hf.space python demo.py

What this script does NOT use: no LLM, no HF_TOKEN, no OpenAI client.
Just plain HTTP + hand-written SQL that the deterministic graders accept.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict

import requests

ENV_URL = os.getenv("ENV_URL", "http://localhost:8000").rstrip("/")
TIMEOUT = 120.0


def _h(title: str) -> None:
    print(f"\n=== {title} ===", flush=True)


def _post(path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    r = requests.post(f"{ENV_URL}{path}", json=payload, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def _get(path: str) -> Dict[str, Any]:
    r = requests.get(f"{ENV_URL}{path}", timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def _show_step(result: Dict[str, Any]) -> None:
    obs = result.get("observation", {}) or {}
    reward = result.get("reward")
    done = result.get("done")
    breakdown = obs.get("grading_breakdown")
    err = obs.get("error")
    out = (obs.get("output") or "").strip().replace("\n", " ")
    if len(out) > 200:
        out = out[:197] + "..."
    print(f"  output    : {out}")
    if err:
        print(f"  error     : {err}")
    print(f"  reward    : {reward}")
    print(f"  done      : {done}")
    if breakdown:
        print(f"  breakdown : {json.dumps(breakdown)}")


def _run_task(task_id: str, actions: list[Dict[str, Any]]) -> float:
    _h(f"Task: {task_id}")
    reset_resp = _post("/reset", {"task": task_id})
    obs = reset_resp.get("observation", {}) or {}
    desc = (obs.get("task_description") or obs.get("output") or "").strip()
    first_line = desc.split("\n", 1)[0] if desc else ""
    print(f"  description: {first_line}")

    last_reward = reset_resp.get("reward") or 0.0
    for i, action in enumerate(actions, start=1):
        sql_preview = action["sql"].strip().replace("\n", " ")
        if len(sql_preview) > 120:
            sql_preview = sql_preview[:117] + "..."
        print(f"\n  step {i}: {sql_preview}")
        result = _post("/step", {"action": action})
        _show_step(result)
        last_reward = result.get("reward") or last_reward
        if result.get("done"):
            break
    return float(last_reward or 0.0)


# ---------------------------------------------------------------------------
# Hand-crafted winning actions for each task
# ---------------------------------------------------------------------------

EASY_ACTIONS = [
    {
        "sql": (
            "CREATE INDEX idx_orders_cust_status_date "
            "ON task_schema.orders (customer_id, status, order_date DESC);"
        ),
        "done": True,
    },
]

MEDIUM_ACTIONS = [
    {
        "sql": (
            "CREATE TABLE task_schema.customers ("
            " id SERIAL PRIMARY KEY,"
            " name VARCHAR NOT NULL,"
            " email VARCHAR UNIQUE NOT NULL,"
            " address VARCHAR"
            ");"
        ),
        "done": False,
    },
    {
        "sql": (
            "CREATE TABLE task_schema.orders ("
            " id SERIAL PRIMARY KEY,"
            " customer_id INT REFERENCES task_schema.customers(id),"
            " order_date TIMESTAMP,"
            " amount NUMERIC,"
            " status VARCHAR"
            ");"
        ),
        "done": False,
    },
    {
        "sql": (
            "INSERT INTO task_schema.customers (name, email, address) "
            "SELECT DISTINCT customer_name, customer_email, customer_address "
            "FROM task_schema.user_orders;"
        ),
        "done": False,
    },
    {
        "sql": (
            "INSERT INTO task_schema.orders (customer_id, order_date, amount, status) "
            "SELECT c.id, u.order_date, u.amount, u.status "
            "FROM task_schema.user_orders u "
            "JOIN task_schema.customers c ON u.customer_email = c.email;"
        ),
        "done": False,
    },
    {
        "sql": (
            "CREATE VIEW task_schema.user_orders_view AS "
            "SELECT c.name AS customer_name, c.email AS customer_email, "
            "       c.address AS customer_address, "
            "       o.order_date, o.amount, o.status "
            "FROM task_schema.customers c "
            "JOIN task_schema.orders o ON o.customer_id = c.id;"
        ),
        "done": True,
    },
]

HARD_ACTIONS = [
    {
        "sql": (
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE application_name='dba_gym_blocker';"
        ),
        "done": False,
    },
    {
        "sql": "CREATE INDEX ON task_schema.events (user_id, event_type);",
        "done": False,
    },
    {"sql": "VACUUM FULL task_schema.bloated_logs;", "done": False},
    {
        "sql": (
            "ALTER SYSTEM SET work_mem='4MB'; "
            "ALTER SYSTEM SET random_page_cost=1.1; "
            "ALTER SYSTEM SET effective_cache_size='1GB'; "
            "SELECT pg_reload_conf();"
        ),
        "done": True,
    },
]


def main() -> int:
    _h("Environment health")
    try:
        print(" ", _get("/health"))
    except requests.RequestException as exc:
        print(f"ERROR: cannot reach {ENV_URL}/health: {exc}", file=sys.stderr)
        print(
            "Start the environment first:\n"
            "    docker run --rm -p 8000:8000 pg-dba-gym",
            file=sys.stderr,
        )
        return 1

    _h("Available tasks")
    for t in _get("/tasks").get("tasks", []):
        print(f"  - {t['id']:<8} {t['name']} ({t['difficulty']})")

    rewards = {
        "easy": _run_task("easy", EASY_ACTIONS),
        "medium": _run_task("medium", MEDIUM_ACTIONS),
        "hard": _run_task("hard", HARD_ACTIONS),
    }

    _h("Demo complete")
    total = sum(rewards.values())
    for k, v in rewards.items():
        print(f"  {k:<8} {v:.3f}")
    print(f"  total    {total:.3f} / 3.000")
    return 0


if __name__ == "__main__":
    sys.exit(main())
