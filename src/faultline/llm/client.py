"""The one door to a language model.

Every LLM call in faultline goes through an `LLMClient`. The product uses a
local OpenAI-compatible server (Ollama or similar); its URL and model name
live in faultline.toml, never in code. Tests use a fake client.
"""

from __future__ import annotations

import json
import tomllib
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


class LLMError(RuntimeError):
    """The model server is unreachable, misconfigured or answered badly."""


class LLMClient(Protocol):
    @property
    def model(self) -> str: ...

    def complete(self, system: str, user: str) -> str: ...


@dataclass(frozen=True)
class LLMConfig:
    base_url: str
    model: str
    temperature: float = 0.0
    seed: int = 0
    timeout_s: int = 600


def load_config(path: Path = Path("faultline.toml")) -> LLMConfig:
    raw = tomllib.loads(path.read_text()).get("llm", {})
    base_url, model = str(raw.get("base_url", "")), str(raw.get("model", ""))
    if not base_url or not model:
        raise LLMError(f"{path}: set [llm] base_url and model")
    return LLMConfig(
        base_url=base_url.rstrip("/"),
        model=model,
        temperature=float(raw.get("temperature", 0.0)),
        seed=int(raw.get("seed", 0)),
        timeout_s=int(raw.get("timeout_s", 600)),
    )


@dataclass(frozen=True)
class OpenAICompatibleClient:
    config: LLMConfig

    @property
    def model(self) -> str:
        return self.config.model

    def payload(self, system: str, user: str) -> dict[str, Any]:
        return {
            "model": self.config.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": self.config.temperature,
            "seed": self.config.seed,
            "stream": False,
        }

    def complete(self, system: str, user: str) -> str:
        request = urllib.request.Request(
            f"{self.config.base_url}/chat/completions",
            data=json.dumps(self.payload(system, user)).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout_s) as response:
                body = json.loads(response.read())
        except OSError as exc:
            raise LLMError(f"cannot reach {self.config.base_url}: {exc}") from exc
        try:
            return str(body["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"unexpected response from {self.config.base_url}") from exc
