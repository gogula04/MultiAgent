"""Optional provider adapters for the LLT bot.

The bot works locally without a remote model. When you are ready, point one of
the HTTP-based providers at an OpenAI-compatible, Groq-compatible, or Poolside
agent endpoint through environment variables.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional
from urllib import error, request


class BotProvider:
    """Base provider interface."""

    name = "base"

    def complete(self, stage: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError


@dataclass
class LocalProvider(BotProvider):
    """Deterministic fallback provider that echoes metadata."""

    name: str = "local"

    def complete(self, stage: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "provider": self.name,
            "stage": stage,
            "status": "skipped",
            "reason": "No remote agent configured",
            "payload_keys": sorted(payload.keys()),
        }


def _normalize_openai_chat_url(endpoint: str) -> str:
    base = endpoint.rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    return f"{base}/chat/completions"


def _extract_chat_content(raw: str) -> Dict[str, Any]:
    try:
        parsed = json.loads(raw)
    except Exception:
        return {"raw": raw}

    if not isinstance(parsed, dict):
        return {"raw": raw}

    choices = parsed.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, dict):
            message = first.get("message")
            if isinstance(message, dict):
                content = message.get("content")
                if isinstance(content, str):
                    return {
                        "provider": parsed.get("provider", "openai-chat"),
                        "status": parsed.get("status", "ok"),
                        "content": content,
                        "parsed_content": _maybe_parse_json(content),
                        "raw_response": parsed,
                    }

    if "content" in parsed and isinstance(parsed["content"], str):
        content = parsed["content"]
        return {
            "provider": parsed.get("provider", "openai-chat"),
            "status": parsed.get("status", "ok"),
            "content": content,
            "parsed_content": _maybe_parse_json(content),
            "raw_response": parsed,
        }

    return parsed


def _maybe_parse_json(text: str) -> Any:
    try:
        return json.loads(text)
    except Exception:
        return text


@dataclass
class OpenAIChatProvider(BotProvider):
    """OpenAI-compatible chat adapter for Poolside or similar endpoints."""

    endpoint: str
    api_key: Optional[str] = None
    model: Optional[str] = None
    name: str = "openai-chat"
    timeout: int = 30

    def complete(self, stage: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        body = json.dumps(
            {
                "model": self.model or "unknown",
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are the planning and verification assistant for an LLT bot. "
                            "Return concise, structured output when possible."
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "stage": stage,
                                "payload": payload,
                            },
                            indent=2,
                            sort_keys=True,
                        ),
                    },
                ],
                "temperature": 0,
            }
        ).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        req = request.Request(_normalize_openai_chat_url(self.endpoint), data=body, headers=headers, method="POST")
        try:
            with request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                parsed = _extract_chat_content(raw)
                if isinstance(parsed, dict):
                    parsed.setdefault("provider", self.name)
                    parsed.setdefault("stage", stage)
                    parsed.setdefault("endpoint", _normalize_openai_chat_url(self.endpoint))
                    return parsed
                return {"provider": self.name, "stage": stage, "status": "ok", "raw": raw}
        except error.HTTPError as exc:
            return {
                "provider": self.name,
                "stage": stage,
                "status": "error",
                "error": f"HTTP {exc.code}: {exc.reason}",
            }
        except Exception as exc:
            return {
                "provider": self.name,
                "stage": stage,
                "status": "error",
                "error": str(exc),
            }


def provider_from_env() -> BotProvider:
    """Build a provider from environment variables.

    Supported configuration:
    - LLT_BOT_AGENT_URL: custom agent endpoint URL
    - LLT_BOT_PROVIDER: openai_compatible | groq_compatible | poolside | local
    - LLT_BOT_API_KEY: bearer token for HTTP providers
    - LLT_BOT_MODEL: model or routing label to send with the request
    - POOLSIDE_BASE_URL: Poolside agent endpoint URL
    - POOLSIDE_API_KEY: Poolside API key
    - POOLSIDE_AGENT_MODEL: Poolside model identifier
    - POOLSIDE_AGENT_NAME: optional logical agent name
    """

    provider_name = os.getenv("LLT_BOT_PROVIDER", "local").strip().lower()
    endpoint = (
        os.getenv("LLT_BOT_AGENT_URL")
        or os.getenv("LLT_BOT_ENDPOINT")
        or os.getenv("POOLSIDE_BASE_URL")
    )
    api_key = os.getenv("LLT_BOT_API_KEY") or os.getenv("POOLSIDE_API_KEY")
    model = os.getenv("LLT_BOT_MODEL") or os.getenv("POOLSIDE_AGENT_MODEL")
    agent_name = os.getenv("POOLSIDE_AGENT_NAME")

    if endpoint:
        if provider_name == "local":
            provider_name = "poolside" if agent_name or api_key or model else "http-json"
        return OpenAIChatProvider(
            endpoint=endpoint,
            api_key=api_key,
            model=model,
            name=agent_name or provider_name or "http-json",
        )

    return LocalProvider()
