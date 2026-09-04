from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from ..config import LLM_MODEL, MLX_BASE_URL


class LLMUnavailable(RuntimeError):
    pass


SYSTEM_PROMPT = """You are Codebase AI, a local repository-understanding assistant.
You must ground repository-specific claims in the supplied SOURCE blocks. Do not invent files, symbols, calls, endpoints, or behavior.
When evidence is incomplete, say what is confirmed and what is inferred.
For file references, use the exact form `relative/path.ext:START-END` from the supplied source headers.
For flow questions, explain the sequence from entry point to downstream calls.
For change-impact questions, separate: confirmed required changes, likely changes, and tests/validation to inspect.
Keep answers practical and repository-specific. Never claim you modified files; this application is read-only.
"""


@dataclass
class LLMClient:
    base_url: str = MLX_BASE_URL
    model: str = LLM_MODEL
    timeout: int = 900

    def health(self) -> tuple[bool, str]:
        try:
            with urllib.request.urlopen(f"{self.base_url}/v1/models", timeout=3) as r:
                _ = json.load(r)
            return True, "ready"
        except Exception as e:
            return False, f"MLX model server unavailable: {e}"

    def chat(self, messages: list[dict[str, str]], temperature: float = 0.15, max_tokens: int = 3200) -> str:
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": SYSTEM_PROMPT}, *messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        req = urllib.request.Request(
            f"{self.base_url}/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                data = json.load(r)
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise LLMUnavailable(str(e)) from e
        try:
            message = data["choices"][0]["message"]
            # mlx-lm historically returned the message as a plain string, while newer
            # OpenAI-compatible variants may return {"role": ..., "content": ...}.
            content = message.get("content") if isinstance(message, dict) else message
        except Exception as e:
            raise LLMUnavailable(f"Unexpected MLX response: {data}") from e
        if not isinstance(content, str) or not content.strip():
            raise LLMUnavailable("MLX returned an empty response")
        return content.strip()
