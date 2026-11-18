"""Thin wrapper around the xAI (Grok) API with task-based model routing.

Every pipeline node calls `call(task, ...)` instead of hardcoding a model name,
so a model rename/retirement (xAI does this every few months -- see
IMPLEMENTATION_PLAN.md section 17) only ever requires editing config/models.yaml.
"""
import os
import time
from functools import lru_cache
from pathlib import Path

import yaml
from openai import OpenAI

_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "models.yaml"


@lru_cache(maxsize=1)
def _task_models() -> dict:
    with open(_CONFIG_PATH, "r") as f:
        return yaml.safe_load(f)["tasks"]


@lru_cache(maxsize=1)
def _client() -> OpenAI:
    return OpenAI(
        api_key=os.environ["XAI_API_KEY"],
        base_url=os.environ.get("XAI_BASE_URL", "https://api.x.ai/v1"),
    )


def call(task: str, messages: list[dict], response_format: dict | None = None, **kwargs) -> tuple:
    """Route a chat completion to the model configured for `task`.

    Returns (response, usage_dict). Caller persists usage_dict via usage_log.record
    so the per-case cost dashboard (IMPLEMENTATION_PLAN.md section 14) stays current.
    """
    model = _task_models()[task]["model"]
    start = time.monotonic()
    response = _client().chat.completions.create(
        model=model,
        messages=messages,
        response_format=response_format,
        **kwargs,
    )
    usage = response.usage
    return response, {
        "task": task,
        "model": model,
        "prompt_tokens": usage.prompt_tokens if usage else None,
        "completion_tokens": usage.completion_tokens if usage else None,
        "latency_ms": int((time.monotonic() - start) * 1000),
    }
