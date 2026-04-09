"""Baseline LLM agent for the PostgreSQL DBA Gym (OpenEnv hackathon harness).

Runs five DBA tasks (easy / medium / hard / backup_recovery / security_audit)
end-to-end against an
OpenEnv-compliant server — either a fresh Docker container spun up via
``GenericEnvClient.from_docker_image(IMAGE_NAME)`` (the evaluator path) or
a pre-running server at ``ENV_URL`` (the local-dev path).

Environment variables
---------------------
``HF_TOKEN``      — OpenAI API key (the hackathon-mandated variable name).
``API_BASE_URL``  — OpenAI API base URL (default: ``https://api.openai.com/v1``).
``MODEL_NAME``    — OpenAI model id (default: ``gpt-4o-mini``).
``IMAGE_NAME``    — if set, ``GenericEnvClient.from_docker_image`` is used to
                    spin up a fresh container for the run.
``ENV_URL``       — fallback base URL when ``IMAGE_NAME`` is unset
                    (default: ``http://localhost:8000``).

Output format (one block per task)
----------------------------------
[START] task=<task_name> env=<benchmark> model=<model_name>
[STEP] step=<n> action=<action_str> reward=<0.00> done=<true|false> error=<msg|null>
...
[END] success=<true|false> steps=<n> score=<score> rewards=<r1,r2,...,rn>

- ``reward`` / ``rewards`` are formatted to 2 decimal places.
- ``score`` is formatted to 3 decimal places.
- ``done`` / ``success`` are lowercase ``true``/``false``.
- ``error`` is either the flattened error string or the literal ``null``.
- ``[END]`` is ALWAYS emitted, even if the episode throws.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from typing import Any, Dict, List, Optional

from openai import OpenAI
from openenv.core.generic_client import GenericEnvClient


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

ENV_NAME = "postgres_dba_gym"
TASK_ORDER: List[str] = [
    "easy",
    "medium",
    "hard",
    "backup_recovery",
    "security_audit",
]
DEFAULT_MAX_STEPS = 25
SUCCESS_THRESHOLD = 0.85

API_KEY = os.getenv("HF_TOKEN")
API_BASE_URL = os.getenv("API_BASE_URL") or "https://api.openai.com/v1"
MODEL_NAME = os.getenv("MODEL_NAME") or "gpt-4o-mini"
IMAGE_NAME = os.getenv("IMAGE_NAME")
ENV_URL = os.getenv("ENV_URL", "http://localhost:8000").rstrip("/")


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


# ---------------------------------------------------------------------------
# Log helpers — the EXACT format the judge parses.
# ---------------------------------------------------------------------------


def log_start(task: str, env: str, model: str) -> None:
    print(f"[START] task={task} env={env} model={model}", flush=True)


def log_step(
    step: int,
    action: str,
    reward: float,
    done: bool,
    error: Optional[str],
) -> None:
    error_val = _flatten(error, max_len=200) if error else "null"
    done_val = "true" if done else "false"
    action_str = _flatten(action, max_len=200)
    print(
        f"[STEP] step={step} action={action_str} "
        f"reward={reward:.2f} done={done_val} error={error_val}",
        flush=True,
    )


def log_end(
    success: bool,
    steps: int,
    score: float,
    rewards: List[float],
) -> None:
    rewards_str = ",".join(f"{r:.2f}" for r in rewards)
    success_val = "true" if success else "false"
    print(
        f"[END] success={success_val} steps={steps} "
        f"score={score:.3f} rewards={rewards_str}",
        flush=True,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _flatten(value: Any, max_len: int = 200) -> str:
    """Collapse a value to a single trimmed line (no newlines, no tabs)."""
    if value is None:
        return ""
    s = str(value).replace("\n", " ").replace("\r", " ").replace("\t", " ")
    s = re.sub(r"\s+", " ", s).strip()
    if len(s) > max_len:
        s = s[: max_len - 3] + "..."
    return s


_FENCE_RE = re.compile(r"```(?:json|sql)?\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)


def parse_action(content: str) -> Dict[str, Any]:
    """Coerce arbitrary LLM output into ``{"sql": ..., "done": ...}``."""
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
    for block in _FENCE_RE.findall(text):
        block = block.strip()
        try:
            obj = json.loads(block)
            if isinstance(obj, dict) and "sql" in obj:
                return {"sql": str(obj["sql"]), "done": bool(obj.get("done", False))}
        except json.JSONDecodeError:
            return {"sql": block, "done": False}

    # Strategy 3: raw content as SQL.
    return {"sql": text, "done": False}


# ---------------------------------------------------------------------------
# Per-task agent loop
# ---------------------------------------------------------------------------


async def run_task(
    env: GenericEnvClient,
    task_name: str,
    llm: OpenAI,
    model: str,
    max_steps: int = DEFAULT_MAX_STEPS,
) -> float:
    """Run one task end-to-end and emit the judge's exact [START]/[STEP]/[END]."""
    log_start(task_name, ENV_NAME, model)

    per_step_rewards: List[float] = []
    score: float = 0.0
    steps_taken: int = 0
    history: List[Dict[str, str]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    done: bool = False

    try:
        # Reset with the task kwarg — flows through ResetRequest extra="allow".
        result = await env.reset(task=task_name)
        obs: Dict[str, Any] = result.observation or {}
        task_description = obs.get("task_description") or obs.get("output", "")
        history.append({"role": "user", "content": task_description})
        score = float(result.reward or 0.0)
        done = bool(result.done)
        env_max = int(obs.get("max_steps") or max_steps)
        step_budget = min(max_steps, env_max)

        for n in range(1, step_budget + 1):
            if done:
                break

            # --- ask the model for the next action ---------------------------
            try:
                chat = llm.chat.completions.create(
                    model=model,
                    messages=history,
                    temperature=0.2,
                    max_tokens=600,
                )
                content = chat.choices[0].message.content or ""
            except Exception as exc:
                msg = f"llm error: {exc}"
                log_step(n, "", score, True, msg)
                per_step_rewards.append(score)
                steps_taken = n
                done = True
                break

            action = parse_action(content)
            action_sql = action.get("sql", "")

            # --- step the environment ----------------------------------------
            try:
                result = await env.step(
                    {"sql": action_sql, "done": bool(action.get("done"))}
                )
            except Exception as exc:
                msg = f"env step error: {exc}"
                log_step(n, action_sql, score, True, msg)
                per_step_rewards.append(score)
                steps_taken = n
                done = True
                break

            obs = result.observation or {}
            reward = float(result.reward or 0.0)
            done = bool(result.done)
            obs_err = obs.get("error")

            log_step(n, action_sql, reward, done, obs_err)
            per_step_rewards.append(reward)
            steps_taken = n
            score = reward

            # --- feed a compact observation back to the model ---------------
            history.append({"role": "assistant", "content": content})
            feedback = {
                "output": _flatten(obs.get("output", ""), max_len=600),
                "error": obs_err,
                "reward": reward,
                "grading_breakdown": obs.get("grading_breakdown"),
                "step_index": obs.get("step_index"),
                "max_steps": obs.get("max_steps"),
            }
            history.append(
                {"role": "user", "content": json.dumps(feedback, default=str)[:1500]}
            )
    except Exception as exc:  # noqa: BLE001
        # Any uncaught error still has to produce a valid [END] line.
        print(f"[DEBUG] run_task error: {exc}", flush=True)
    finally:
        success = score >= SUCCESS_THRESHOLD
        log_end(success=success, steps=steps_taken, score=score, rewards=per_step_rewards)

    return score


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


async def _open_env() -> GenericEnvClient:
    """Open an env client via Docker image (preferred) or live base URL."""
    if IMAGE_NAME:
        return await GenericEnvClient.from_docker_image(IMAGE_NAME)
    env = GenericEnvClient(base_url=ENV_URL)
    await env.connect()
    return env


async def main() -> int:
    if not API_KEY:
        raise ValueError(
            "HF_TOKEN environment variable is required. "
            "Set it to your OpenAI API key — the hackathon spec mandates the "
            "variable name `HF_TOKEN` and it is passed as the OpenAI client "
            "`api_key`."
        )

    llm = OpenAI(base_url=API_BASE_URL, api_key=API_KEY)
    env: Optional[GenericEnvClient] = None
    try:
        env = await _open_env()
        for task_name in TASK_ORDER:
            await run_task(
                env=env,
                task_name=task_name,
                llm=llm,
                model=MODEL_NAME,
                max_steps=DEFAULT_MAX_STEPS,
            )
    finally:
        if env is not None:
            try:
                await env.close()
            except Exception as e:  # noqa: BLE001
                print(f"[DEBUG] env.close() error: {e}", flush=True)

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
