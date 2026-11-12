"""Client for any OpenAI-compatible chat endpoint, set by LLM_BASE_URL, LLM_MODEL and LLM_API_KEY."""
import os
import re
import time
from dataclasses import dataclass
from functools import lru_cache

import httpx
from pydantic import BaseModel, ValidationError

from app.models import LLMUsage

_THINKING = re.compile(r"^\s*<think>.*?</think>\s*", re.S)


class LLMUnavailable(Exception):
    pass


@dataclass
class LLMCall:
    input_tokens: int
    output_tokens: int
    latency_ms: int


def usage_rows(
    purpose: str,
    model: str,
    calls: list[LLMCall],
    lesson_id: int | None,
    user_id: int | None = None,
) -> list[LLMUsage]:
    return [
        LLMUsage(
            purpose=purpose,
            model=model,
            input_tokens=call.input_tokens,
            output_tokens=call.output_tokens,
            latency_ms=call.latency_ms,
            lesson_id=lesson_id,
            user_id=user_id,
        )
        for call in calls
    ]


class GLMClient:
    def __init__(self) -> None:
        api_key = os.environ.get("LLM_API_KEY", "")
        self.model = os.environ.get("LLM_MODEL", "GLM-5.2")
        self.http = httpx.Client(
            base_url=os.environ["LLM_BASE_URL"].rstrip("/") + "/",
            timeout=float(os.environ.get("LLM_TIMEOUT_S", "30")),
            headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
            trust_env=False,
        )

    def chat(
        self,
        messages: list[dict],
        max_tokens: int = 512,
        schema: dict | None = None,
        calls: list[LLMCall] | None = None,
    ) -> str:
        body = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "temperature": 0,
            "max_tokens": max_tokens,
            "chat_template_kwargs": {"enable_thinking": False},
        }
        if schema is not None:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": schema.get("title", "reply"), "schema": schema},
            }
        started = time.monotonic()
        try:
            response = self.http.post("chat/completions", json=body)
            response.raise_for_status()
            reply = response.json()
            content = reply["choices"][0]["message"]["content"] or ""
        except httpx.HTTPError as exc:
            raise LLMUnavailable(type(exc).__name__) from exc
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise LLMUnavailable("bad_response") from exc
        if calls is not None:
            usage = reply.get("usage") or {}
            calls.append(
                LLMCall(
                    usage.get("prompt_tokens", sum(len(m["content"]) for m in messages) // 4),
                    usage.get("completion_tokens", len(content) // 4),
                    int((time.monotonic() - started) * 1000),
                )
            )
        return _THINKING.sub("", content)

    def complete_json[S: BaseModel](
        self,
        system: str,
        user: str,
        schema: type[S],
        max_tokens: int = 512,
        calls: list[LLMCall] | None = None,
    ) -> S | None:
        fmt = schema.model_json_schema()
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        try:
            return schema.model_validate_json(self.chat(messages, max_tokens, fmt, calls))
        except ValidationError as error:
            messages[-1]["content"] = (
                f"{user}\n\nYour previous reply was invalid ({error.error_count()} errors). "
                "Reply again with JSON matching the schema."
            )
        try:
            return schema.model_validate_json(self.chat(messages, max_tokens, fmt, calls))
        except ValidationError:
            return None


@lru_cache
def get_llm() -> GLMClient:
    return GLMClient()
