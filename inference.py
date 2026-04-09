"""Baseline LLM agent for the PostgreSQL DBA Gym (OpenEnv hackathon harness).

Runs five DBA tasks (easy / medium / hard / expert / master)
end-to-end against an
OpenEnv-compliant server — either a fresh Docker container spun up via
``GenericEnvClient.from_docker_image(IMAGE_NAME)`` (the evaluator path) or
a pre-running server at ``ENV_URL`` (the local-dev path).

Environment variables
---------------------
``HF_TOKEN``      — OpenAI API key (the hackathon-mandated variable name; ``API_KEY`` also accepted).
``API_BASE_URL``  — OpenAI API base URL (default: ``https://api.openai.com/v1``).
``MODEL_NAME``    — OpenAI model id (default: ``gpt-4o-mini``).
``IMAGE_NAME``    — if set (or ``LOCAL_IMAGE_NAME``),
                    ``GenericEnvClient.from_docker_image`` is used to spin up
                    a fresh container for the run.
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
# Color helpers
#
# Colors are emitted only when stdout is a real TTY *or* FORCE_COLOR=1 is
# set.  The latter is the escape hatch for HuggingFace Spaces: the Spaces
# Logs tab renders ANSI escape codes, but isatty() returns False inside the
# container, so set FORCE_COLOR=1 as a Space secret to get colored output.
#
# When the evaluator pipes stdout to its parser, isatty() is False and
# FORCE_COLOR is unset, so no escape codes reach the judge.
# ---------------------------------------------------------------------------

_USE_COLOR: bool = sys.stdout.isatty() or os.getenv("FORCE_COLOR", "").lower() in (
    "1",
    "true",
    "yes",
)


class _C:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    CYAN = "\033[36m"
    MAGENTA = "\033[35m"
    BRIGHT_GREEN = "\033[92m"
    BRIGHT_YELLOW = "\033[93m"
    BRIGHT_RED = "\033[91m"
    BRIGHT_CYAN = "\033[96m"


def _c(text: str, *codes: str) -> str:
    """Wrap *text* in ANSI *codes* if color output is enabled."""
    if not _USE_COLOR:
        return text
    return "".join(codes) + text + _C.RESET


def _reward_color(reward: float) -> str:
    if reward >= SUCCESS_THRESHOLD:
        return _C.BRIGHT_GREEN
    if reward >= 0.5:
        return _C.BRIGHT_YELLOW
    return _C.BRIGHT_RED


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

ENV_NAME = "postgres_dba_gym"
TASK_ORDER: List[str] = [
    "easy",
    "medium",
    "hard",
    "expert",
    "master",
]
DEFAULT_MAX_STEPS = 25
SUCCESS_THRESHOLD = 0.85

_SCORE_EPS = 0.01


def _clamp_score(score: float) -> float:
    """Clamp a score into the open interval (0, 1).

    The hackathon validator rejects exact 0.0 and 1.0 — scores must be
    strictly between 0 and 1.
    """
    return max(_SCORE_EPS, min(1.0 - _SCORE_EPS, score))

API_KEY = os.getenv("HF_TOKEN") or os.getenv("API_KEY")
API_BASE_URL = os.getenv("API_BASE_URL") or "https://api.openai.com/v1"
MODEL_NAME = os.getenv("MODEL_NAME") or "gpt-4o-mini"
IMAGE_NAME = os.getenv("IMAGE_NAME") or os.getenv("LOCAL_IMAGE_NAME")
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
    line = f"[START] task={task} env={env} model={model}"
    print(
        _c("[START]", _C.BOLD, _C.BRIGHT_CYAN)
        + _c(f" task=", _C.DIM)
        + _c(task, _C.BOLD, _C.CYAN)
        + _c(f" env={env}", _C.DIM)
        + _c(f" model={model}", _C.DIM)
        if _USE_COLOR
        else line,
        flush=True,
    )


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
    line = (
        f"[STEP] step={step} action={action_str} "
        f"reward={reward:.2f} done={done_val} error={error_val}"
    )
    if _USE_COLOR:
        rc = _reward_color(reward)
        err_color = _C.BRIGHT_RED if error else _C.DIM
        print(
            _c("[STEP]", _C.BOLD, _C.MAGENTA)
            + _c(f" step={step}", _C.DIM)
            + f" action={_c(action_str, _C.DIM)}"
            + f" reward={_c(f'{reward:.2f}', rc, _C.BOLD)}"
            + f" done={_c(done_val, _C.CYAN)}"
            + f" error={_c(error_val, err_color)}",
            flush=True,
        )
    else:
        print(line, flush=True)


def log_end(
    success: bool,
    steps: int,
    score: float,
    rewards: List[float],
) -> None:
    rewards_str = ",".join(f"{r:.2f}" for r in rewards)
    success_val = "true" if success else "false"
    line = (
        f"[END] success={success_val} steps={steps} "
        f"score={score:.3f} rewards={rewards_str}"
    )
    if _USE_COLOR:
        end_color = _C.BRIGHT_GREEN if success else _C.BRIGHT_RED
        print(
            _c("[END]", _C.BOLD, end_color)
            + f" success={_c(success_val, end_color, _C.BOLD)}"
            + _c(f" steps={steps}", _C.DIM)
            + f" score={_c(f'{score:.3f}', _reward_color(score), _C.BOLD)}"
            + _c(f" rewards={rewards_str}", _C.DIM),
            flush=True,
        )
    else:
        print(line, flush=True)


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
                log_step(n, "", _clamp_score(score), True, msg)
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
                log_step(n, action_sql, _clamp_score(score), True, msg)
                per_step_rewards.append(score)
                steps_taken = n
                done = True
                break

            obs = result.observation or {}
            reward = float(result.reward or 0.0)
            done = bool(result.done)
            obs_err = obs.get("error")

            log_step(n, action_sql, _clamp_score(reward), done, obs_err)
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
        print(
            _c("[DEBUG]", _C.DIM) + _c(f" run_task error: {exc}", _C.DIM)
            if _USE_COLOR
            else f"[DEBUG] run_task error: {exc}",
            flush=True,
        )
    finally:
        clamped = _clamp_score(score)
        clamped_rewards = [_clamp_score(r) for r in per_step_rewards]
        success = score >= SUCCESS_THRESHOLD
        log_end(success=success, steps=steps_taken, score=clamped, rewards=clamped_rewards)

    return clamped


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


async def _open_env() -> GenericEnvClient:
    """Open an env client via Docker image (preferred) or live base URL.

    Falls back to the URL-based connection if Docker is unavailable
    (e.g. the evaluator already manages the container externally).
    """
    if IMAGE_NAME:
        try:
            return await GenericEnvClient.from_docker_image(IMAGE_NAME)
        except Exception as exc:
            msg = f"[DEBUG] from_docker_image failed ({exc!r}), falling back to ENV_URL={ENV_URL}"
            print(
                _c("[DEBUG]", _C.DIM) + _c(msg[7:], _C.DIM) if _USE_COLOR else msg,
                flush=True,
            )
    env = GenericEnvClient(base_url=ENV_URL)
    await env.connect()
    return env


async def main() -> int:
    if not API_KEY:
        print(
            _c("[ERROR]", _C.BOLD, _C.BRIGHT_RED)
            + _c(" HF_TOKEN (or API_KEY) environment variable is required.", _C.BRIGHT_RED)
            if _USE_COLOR
            else "[ERROR] HF_TOKEN (or API_KEY) environment variable is required.",
            flush=True,
        )
        return 1

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
    except Exception as exc:  # noqa: BLE001
        print(
            _c("[ERROR]", _C.BOLD, _C.BRIGHT_RED) + _c(f" fatal: {exc!r}", _C.BRIGHT_RED)
            if _USE_COLOR
            else f"[ERROR] fatal: {exc!r}",
            flush=True,
        )
        return 1
    finally:
        if env is not None:
            try:
                await env.close()
            except Exception as e:  # noqa: BLE001
                print(
                    _c("[DEBUG]", _C.DIM) + _c(f" env.close() error: {e}", _C.DIM)
                    if _USE_COLOR
                    else f"[DEBUG] env.close() error: {e}",
                    flush=True,
                )

    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except Exception as exc:  # noqa: BLE001
        print(
            _c("[ERROR]", _C.BOLD, _C.BRIGHT_RED) + _c(f" top-level: {exc!r}", _C.BRIGHT_RED)
            if _USE_COLOR
            else f"[ERROR] top-level: {exc!r}",
            flush=True,
        )
        sys.exit(1)
