"""Baseline LLM agent for the PostgreSQL DBA Gym (hackathon judge harness).

The hackathon judge runs this script with the following environment variables:

* ``API_BASE_URL`` — OpenAI-compatible chat completions endpoint
* ``MODEL_NAME``   — model id to pass to ``client.chat.completions.create``
* ``HF_TOKEN``     — bearer token (used as the OpenAI ``api_key``)

It also assumes a running ``postgres_dba_gym`` env at ``ENV_URL``
(defaults to ``http://localhost:8000``).

Output format
-------------
Per-task block, in this exact form (deviation = disqualification):

    [START]
    [STEP] action: <action> | observation: <obs> | reward: <reward>
    [STEP] action: <action> | observation: <obs> | reward: <reward>
    ...
    [END] total_reward: <reward>

After all three tasks finish, an aggregate ``FINAL REWARDS:`` JSON line is
printed. The aggregate is supplemental and does not break the per-task
contract — judges grep for the per-task ``[START]/[STEP]/[END]`` blocks.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from typing import Any, Dict, List, Optional

import requests
from openai import OpenAI


SYSTEM_PROMPT = """You are an expert PostgreSQL Database Administrator working in a sandboxed
training environment. You will be given DBA tasks against a live PostgreSQL 16
instance and must solve them by issuing SQL.

How to interact:
- Reply with a JSON object: {"sql": "<your SQL>", "done": <true|false>}
- Multiple semicolon-separated statements in one action are allowed and run
  one statement at a time (so ALTER SYSTEM and VACUUM FULL work fine).
- Set done=true ONLY when you believe the task is fully complete.
- The environment returns rows, errors, your current reward in [0,1], and a
  grading_breakdown that shows which sub-rubrics still need work — use it!

Useful inspection queries:
- EXPLAIN (ANALYZE, BUFFERS) <query>
- SELECT * FROM pg_indexes WHERE schemaname='task_schema'
- SELECT * FROM information_schema.columns WHERE table_schema='task_schema'
- SELECT * FROM pg_stat_user_tables WHERE schemaname='task_schema'
- SELECT name, setting, unit FROM pg_settings WHERE name IN (...)
- SELECT pid, application_name, state, query FROM pg_stat_activity WHERE state='idle in transaction'

Be decisive. Read the grading_breakdown after every step and target whichever
sub-rubric is still 0. Stop when reward >= success threshold.
"""

# Tasks are run in this order. Names match the env's task ids.
TASK_ORDER: List[str] = ["easy", "medium", "hard"]

# Per-task max_steps cap on the agent loop. The env enforces its own
# MAX_STEPS as well; whichever fires first ends the episode.
DEFAULT_MAX_STEPS = 25


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


def _post_json(url: str, payload: Dict[str, Any], timeout: float = 120.0) -> Dict[str, Any]:
    """POST JSON and raise on non-2xx. Bubbles up the body on errors."""
    r = requests.post(url, json=payload, timeout=timeout)
    if not r.ok:
        raise RuntimeError(f"POST {url} -> {r.status_code}: {r.text[:500]}")
    return r.json()


def _get_json(url: str, timeout: float = 30.0) -> Dict[str, Any]:
    r = requests.get(url, timeout=timeout)
    if not r.ok:
        raise RuntimeError(f"GET {url} -> {r.status_code}: {r.text[:500]}")
    return r.json()


# ---------------------------------------------------------------------------
# LLM action parsing
# ---------------------------------------------------------------------------


_FENCE_RE = re.compile(r"```(?:json|sql)?\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)


def parse_action(content: str) -> Dict[str, Any]:
    """Coerce arbitrary LLM output into a ``{"sql": ..., "done": ...}`` dict.

    Strategy:
      1. Try to ``json.loads`` the entire content.
      2. Try to extract a fenced ``json``/``sql`` code block and parse that.
      3. Fall back to using the raw content as a SQL string with done=False.
    """
    if content is None:
        return {"sql": "", "done": False}

    text = content.strip()

    # Strategy 1: whole content is JSON.
    try:
        obj = json.loads(text)
        if isinstance(obj, dict) and "sql" in obj:
            return {"sql": str(obj["sql"]), "done": bool(obj.get("done", False))}
    except json.JSONDecodeError:
        pass

    # Strategy 2: fenced code block.
    fences = _FENCE_RE.findall(text)
    for block in fences:
        block = block.strip()
        try:
            obj = json.loads(block)
            if isinstance(obj, dict) and "sql" in obj:
                return {"sql": str(obj["sql"]), "done": bool(obj.get("done", False))}
        except json.JSONDecodeError:
            # Treat the fenced block as raw SQL.
            return {"sql": block, "done": False}

    # Strategy 3: raw content as SQL.
    return {"sql": text, "done": False}


# ---------------------------------------------------------------------------
# Single-line formatters for the [STEP] log line
# ---------------------------------------------------------------------------


def _flatten(value: Any, max_len: int = 200) -> str:
    """Collapse a value into a single trimmed line for the log format."""
    if value is None:
        return ""
    s = str(value)
    s = s.replace("\n", " ").replace("\r", " ").replace("\t", " ")
    s = re.sub(r"\s+", " ", s).strip()
    if len(s) > max_len:
        s = s[: max_len - 3] + "..."
    return s


def _build_observation_text(obs: Dict[str, Any]) -> str:
    """Pick the most informative observation field for the [STEP] line."""
    error = obs.get("error")
    output = obs.get("output")
    if error:
        return f"ERROR: {error}"
    return output or ""


# ---------------------------------------------------------------------------
# Per-task agent loop
# ---------------------------------------------------------------------------


def run_task(
    env_url: str,
    task_name: str,
    client: OpenAI,
    model: str,
    max_steps: int = DEFAULT_MAX_STEPS,
) -> float:
    """Run one task end-to-end and emit the judge's exact log block.

    Returns the final reward observed for this task.
    """
    print("[START]", flush=True)

    reset_resp = _post_json(f"{env_url}/reset", {"task": task_name})
    obs = reset_resp.get("observation", {}) or {}
    task_description = obs.get("task_description") or obs.get("output", "")

    history: List[Dict[str, str]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": task_description},
    ]

    total_reward: float = float(reset_resp.get("reward") or 0.0)
    done = bool(reset_resp.get("done"))

    # The env reports its own MAX_STEPS in the observation; honour the
    # smaller of (env, agent) so the loop never runs longer than either.
    env_max_steps = int(obs.get("max_steps") or max_steps)
    step_budget = min(max_steps, env_max_steps)

    for _ in range(step_budget):
        if done:
            break

        # Ask the model for the next action.
        try:
            chat = client.chat.completions.create(
                model=model,
                messages=history,
                temperature=0.2,
                max_tokens=600,
            )
            content = chat.choices[0].message.content or ""
        except Exception as exc:
            # Don't crash on a transient API hiccup — log and bail out
            # of this task with the last reward intact.
            print(
                f"[STEP] action: <llm error: {_flatten(exc, 80)}> | "
                f"observation: <skipped> | reward: {total_reward}",
                flush=True,
            )
            break

        action = parse_action(content)
        action_str = _flatten(action.get("sql", ""), max_len=200)

        try:
            step_resp = _post_json(
                f"{env_url}/step",
                {"action": {"sql": action["sql"], "done": bool(action.get("done"))}},
            )
        except Exception as exc:
            print(
                f"[STEP] action: {action_str} | "
                f"observation: <env error: {_flatten(exc, 120)}> | "
                f"reward: {total_reward}",
                flush=True,
            )
            break

        obs = step_resp.get("observation", {}) or {}
        reward = float(step_resp.get("reward") or 0.0)
        done = bool(step_resp.get("done"))
        obs_text = _flatten(_build_observation_text(obs), max_len=200)

        print(
            f"[STEP] action: {action_str} | "
            f"observation: {obs_text} | "
            f"reward: {reward}",
            flush=True,
        )

        total_reward = reward

        # Feed back a compact JSON snapshot to the model so it can
        # reason about the grading_breakdown without us flooding the
        # context with full result sets.
        history.append({"role": "assistant", "content": content})
        feedback = {
            "output": _flatten(obs.get("output", ""), max_len=600),
            "error": obs.get("error"),
            "reward": reward,
            "grading_breakdown": obs.get("grading_breakdown"),
            "step_index": obs.get("step_index"),
            "max_steps": obs.get("max_steps"),
        }
        history.append(
            {"role": "user", "content": json.dumps(feedback, default=str)[:1500]}
        )

    print(f"[END] total_reward: {total_reward}", flush=True)
    return total_reward


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


def _wait_for_env(env_url: str, timeout_s: float = 60.0) -> None:
    """Poll ``/health`` until the env answers (or give up)."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            r = requests.get(f"{env_url}/health", timeout=2.0)
            if r.ok:
                return
        except requests.RequestException:
            pass
        time.sleep(1.0)
    raise RuntimeError(f"environment at {env_url} did not become healthy in {timeout_s}s")


def main() -> int:
    api_base_url = os.environ.get("API_BASE_URL")
    model = os.environ.get("MODEL_NAME")
    hf_token = os.environ.get("HF_TOKEN")
    env_url = os.environ.get("ENV_URL", "http://localhost:8000").rstrip("/")
    max_steps = int(os.environ.get("DBA_GYM_MAX_STEPS", str(DEFAULT_MAX_STEPS)))

    missing = [
        name
        for name, val in [
            ("API_BASE_URL", api_base_url),
            ("MODEL_NAME", model),
            ("HF_TOKEN", hf_token),
        ]
        if not val
    ]
    if missing:
        print(
            f"ERROR: missing required environment variables: {', '.join(missing)}",
            file=sys.stderr,
        )
        return 2

    client = OpenAI(base_url=api_base_url, api_key=hf_token)
    _wait_for_env(env_url)

    rewards: Dict[str, float] = {}
    for task_name in TASK_ORDER:
        rewards[task_name] = run_task(
            env_url=env_url,
            task_name=task_name,
            client=client,
            model=model,
            max_steps=max_steps,
        )

    # Aggregate line for human readers / scoreboards.
    print(f"FINAL REWARDS: {json.dumps(rewards)}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
