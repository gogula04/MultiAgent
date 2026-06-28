"""Poolside client helpers for the LLT verification runtime.

The runtime talks to Poolside over HTTP using a single configuration path.
No alternate providers or fallback vendor settings are supported here.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional
from urllib import error, request


def _normalize_poolside_chat_url(endpoint: str) -> str:
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
                        "provider": "poolside",
                        "status": parsed.get("status", "ok"),
                        "content": content,
                        "parsed_content": _maybe_parse_json(content),
                        "raw_response": parsed,
                    }

    if "content" in parsed and isinstance(parsed["content"], str):
        content = parsed["content"]
        return {
            "provider": "poolside",
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


def _load_text_if_exists(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        return path.read_text(errors="ignore").strip()
    except Exception:
        return ""


@dataclass
class PoolsideClient:
    """Poolside chat adapter."""

    endpoint: str
    api_key: Optional[str] = None
    model: Optional[str] = None
    agent_name: Optional[str] = None
    playbook_prompt: Optional[str] = None
    prompt_dir: Optional[Path] = None
    timeout: int = 30

    def _stage_prompt_path(self, stage: str) -> Optional[Path]:
        prompt_dir = self.prompt_dir or (Path(__file__).resolve().parents[1] / "references" / "poolside-prompts")
        if not prompt_dir.exists():
            return None
        stage_key = re.sub(r"[^a-z0-9]+", "-", stage.strip().lower()).strip("-")
        candidates = [
            prompt_dir / f"{stage_key}.md",
            prompt_dir / f"{stage_key}.txt",
        ]
        if stage_key.startswith("legacy-"):
            candidates.insert(0, prompt_dir / "requirement-extraction.md")
        if "requirement" in stage_key or "legacy" in stage_key:
            candidates.insert(0, prompt_dir / "requirement-extraction.md")
        if "analysis" in stage_key or "strategy" in stage_key or "evidence" in stage_key:
            candidates.insert(0, prompt_dir / "evidence-and-strategy.md")
        if "artifact" in stage_key or "direct" in stage_key or "hybrid" in stage_key:
            candidates.insert(0, prompt_dir / "artifact-generation.md")
        if "review" in stage_key or "proof" in stage_key:
            candidates.insert(0, prompt_dir / "review-and-proof.md")
        if "debug" in stage_key:
            candidates.insert(0, prompt_dir / "debug-and-repair.md")
        for path in candidates:
            if path.exists():
                return path
        return prompt_dir / "default.md" if (prompt_dir / "default.md").exists() else None

    def _load_stage_prompt(self, stage: str) -> str:
        path = self._stage_prompt_path(stage)
        if path is None:
            return ""
        return _load_text_if_exists(path)

    def complete(self, stage: str, payload: Dict[str, Any], instructions: Optional[str] = None) -> Dict[str, Any]:
        stage_prompt = self._load_stage_prompt(stage)
        prompt_parts = [
            part.strip()
            for part in [
                self.playbook_prompt or "",
                stage_prompt,
                instructions or "",
                "You are the planning and verification assistant for an LLT agent. Return concise, structured output when possible.",
            ]
            if part and part.strip()
        ]
        system_prompt = "\n\n---\n\n".join(prompt_parts)
        body = json.dumps(
            {
                "model": self.model or "laguna_m_fp8_fp8kv_re_04_2026",
                "messages": [
                    {
                        "role": "system",
                        "content": system_prompt,
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

        req = request.Request(
            _normalize_poolside_chat_url(self.endpoint),
            data=body,
            headers=headers,
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                parsed = _extract_chat_content(raw)
                if isinstance(parsed, dict):
                    parsed.setdefault("provider", "poolside")
                    parsed.setdefault("stage", stage)
                    parsed.setdefault("endpoint", _normalize_poolside_chat_url(self.endpoint))
                    if self.agent_name:
                        parsed.setdefault("agent_name", self.agent_name)
                    return parsed
                return {"provider": "poolside", "stage": stage, "status": "ok", "raw": raw}
        except error.HTTPError as exc:
            return {
                "provider": "poolside",
                "stage": stage,
                "status": "error",
                "error": f"HTTP {exc.code}: {exc.reason}",
            }
        except Exception as exc:
            return {
                "provider": "poolside",
                "stage": stage,
                "status": "error",
                "error": str(exc),
            }


def poolside_from_env() -> PoolsideClient:
    """Build a Poolside client from environment variables."""

    endpoint = os.getenv("POOLSIDE_BASE_URL", "").strip()
    if not endpoint:
        raise RuntimeError("POOLSIDE_BASE_URL environment variable must be set")
    api_key = os.getenv("POOLSIDE_API_KEY", "")
    model = os.getenv("POOLSIDE_AGENT_MODEL", "laguna_m_fp8_fp8kv_re_04_2026")
    agent_name = os.getenv("POOLSIDE_AGENT_NAME")
    playbook_path = Path(__file__).resolve().parents[1] / "references" / "poolside-verification-playbook.md"
    playbook_prompt = playbook_path.read_text(errors="ignore").strip() if playbook_path.exists() else ""
    prompt_dir = Path(__file__).resolve().parents[1] / "references" / "poolside-prompts"

    return PoolsideClient(
        endpoint=endpoint,
        api_key=api_key,
        model=model,
        agent_name=agent_name,
        playbook_prompt=playbook_prompt or None,
        prompt_dir=prompt_dir,
    )
