"""Thin wrapper around Groq Cloud's API (api.groq.com) with task-based model routing.

NOT xAI/Grok -- Groq Cloud is a different company hosting open-weight models
(gpt-oss, qwen, etc.) on custom inference chips. See grok_client.py (dormant)
for the original xAI-based design this project started from.

Groq's free tier has tight per-key rate limits, so this rotates across
GROQ_API_KEY / GROQ_API_KEY2 / GROQ_API_KEY3 on a 429 rather than failing the call outright.
"""
import os
import time
from functools import lru_cache
from pathlib import Path

import yaml
from openai import OpenAI, RateLimitError

_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "models.yaml"


@lru_cache(maxsize=1)
def _task_models() -> dict:
    with open(_CONFIG_PATH, "r") as f:
        return yaml.safe_load(f)["tasks"]


def _api_keys() -> list[str]:
    keys = [
        os.environ.get("GROQ_API_KEY"),
        os.environ.get("GROQ_API_KEY2"),
        os.environ.get("GROQ_API_KEY3"),
    ]
    return [k for k in keys if k]


@lru_cache(maxsize=4)
def _client(api_key: str) -> OpenAI:
    return OpenAI(api_key=api_key, base_url=os.environ.get("GROQ_BASE_URL", "https://api.groq.com/openai/v1"))


def call(task: str, messages: list[dict], response_format: dict | None = None, **kwargs) -> tuple:
    """Route a chat completion to the model configured for `task`, rotating
    across available API keys if one is rate-limited.

    Returns (response, usage_dict). Caller persists usage_dict via usage_log.record.
    """
    model = _task_models()[task]["model"]
    keys = _api_keys()
    if not keys:
        raise RuntimeError("No GROQ_API_KEY/GROQ_API_KEY2/GROQ_API_KEY3 set in the environment")

    last_error: Exception | None = None
    for key in keys:
        start = time.monotonic()
        try:
            response = _client(key).chat.completions.create(
                model=model,
                messages=messages,
                response_format=response_format,
                **kwargs,
            )
        except RateLimitError as exc:
            last_error = exc
            continue
        usage = response.usage
        return response, {
            "task": task,
            "model": model,
            "prompt_tokens": usage.prompt_tokens if usage else None,
            "completion_tokens": usage.completion_tokens if usage else None,
            "latency_ms": int((time.monotonic() - start) * 1000),
        }
    raise RuntimeError(f"All Groq API keys rate-limited for task={task!r}") from last_error
