"""The reference line: a hosted frontier model in faultline's two LLM slots.

CLAUDE.md principle 7. `faultline eval --reference` runs this client in the
raw-log baseline and the triage re-ranking step, with the same prompts and
inputs as the local model. It runs on benchmark data only, never on a user's
project. The API key is read from an environment variable when the client is
built and kept in memory only: it is never written to disk, logs or result
files. Results are labelled "reference", carry their token counts and cost per
incident, and are never mixed into the local model's tables.

A hard spending cap is checked before every call with a pessimistic estimate,
so a run stops before it can go over. `--dry-run` sends every prompt to the
free token-counting endpoint instead, and prints what the run would cost.
"""

from __future__ import annotations

import json
import os
import time
import tomllib
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from faultline.llm.client import LLMError

# (url, headers, body) -> (status, parsed JSON body)
Transport = Callable[[str, dict[str, str], dict[str, Any]], tuple[int, dict[str, Any]]]
CHARS_PER_TOKEN_FLOOR = 2.5  # pessimistic: real text runs about 3.5-4 characters per token
RETRY_STATUS = frozenset({429, 500, 502, 503, 529})
RETRY_WAIT_S = (5, 20, 60)
STUB_ANSWER = '{"order": [1], "summary": ""}'


class BudgetExceeded(LLMError):
    """The next call could take the run over its spending cap."""


@dataclass(frozen=True)
class ReferenceConfig:
    provider: str
    model: str
    base_url: str
    api_key_env: str
    anthropic_version: str
    input_usd_per_mtok: float
    output_usd_per_mtok: float
    prices_source: str
    prices_checked: str
    cap_usd: float
    max_tokens: int
    temperature: float | None
    timeout_s: int
    dry_run_output_tokens: int

    def public(self) -> dict[str, Any]:
        """What goes into result files. Names the key's variable, never the key."""
        return {
            "provider": self.provider,
            "model": self.model,
            "prices_usd_per_mtok": {
                "input": self.input_usd_per_mtok,
                "output": self.output_usd_per_mtok,
            },
            "prices_source": self.prices_source,
            "prices_checked": self.prices_checked,
            "cap_usd": self.cap_usd,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
        }


def load_reference_config(path: Path = Path("faultline.toml")) -> ReferenceConfig:
    raw = tomllib.loads(path.read_text()).get("reference")
    if not raw:
        raise LLMError(f"{path}: no [reference] section")
    if raw.get("provider") != "anthropic":
        raise LLMError(f"{path}: [reference] provider must be 'anthropic'")
    temperature = raw.get("temperature")
    return ReferenceConfig(
        provider="anthropic",
        model=str(raw["model"]),
        base_url=str(raw.get("base_url", "https://api.anthropic.com")).rstrip("/"),
        api_key_env=str(raw.get("api_key_env", "ANTHROPIC_API_KEY")),
        anthropic_version=str(raw.get("anthropic_version", "2023-06-01")),
        input_usd_per_mtok=float(raw["input_usd_per_mtok"]),
        output_usd_per_mtok=float(raw["output_usd_per_mtok"]),
        prices_source=str(raw["prices_source"]),
        prices_checked=str(raw["prices_checked"]),
        cap_usd=float(raw["cap_usd"]),
        max_tokens=int(raw.get("max_tokens", 1024)),
        temperature=None if temperature is None else float(temperature),
        timeout_s=int(raw.get("timeout_s", 300)),
        dry_run_output_tokens=int(raw.get("dry_run_output_tokens", 300)),
    )


def _urllib_transport(timeout_s: int) -> Transport:
    def send(url: str, headers: dict[str, str], body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        request = urllib.request.Request(
            url, data=json.dumps(body).encode(), headers=headers, method="POST"
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout_s) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as exc:
            try:
                detail = json.loads(exc.read())
            except (ValueError, OSError):
                detail = {}
            return exc.code, detail
        except OSError as exc:
            raise LLMError(f"cannot reach the reference API: {exc}") from exc

    return send


@dataclass
class AnthropicClient:
    """Claude through the Messages API, with plain HTTP. Same interface as LLMClient."""

    config: ReferenceConfig
    dry_run: bool = False
    transport: Transport | None = None
    sleep: Callable[[float], None] = time.sleep
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    _key: str = field(default="", repr=False)

    def __post_init__(self) -> None:
        key = os.environ.get(self.config.api_key_env, "")
        if not key:
            raise LLMError(f"set the {self.config.api_key_env} environment variable")
        self._key = key
        if self.transport is None:
            self.transport = _urllib_transport(self.config.timeout_s)

    @property
    def model(self) -> str:
        return self.config.model

    def _headers(self) -> dict[str, str]:
        return {
            "x-api-key": self._key,
            "anthropic-version": self.config.anthropic_version,
            "content-type": "application/json",
        }

    def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        assert self.transport is not None
        for attempt in range(len(RETRY_WAIT_S) + 1):
            status, doc = self.transport(f"{self.config.base_url}{path}", self._headers(), body)
            if status == 200:
                return doc
            if status in RETRY_STATUS and attempt < len(RETRY_WAIT_S):
                self.sleep(RETRY_WAIT_S[attempt])
                continue
            message = (doc.get("error") or {}).get("message", "") if isinstance(doc, dict) else ""
            raise LLMError(f"reference API answered {status}: {message}")
        raise LLMError("reference API kept failing")  # pragma: no cover

    def cost_usd(self, input_tokens: int, output_tokens: int) -> float:
        return (
            input_tokens * self.config.input_usd_per_mtok
            + output_tokens * self.config.output_usd_per_mtok
        ) / 1_000_000

    @property
    def spent_usd(self) -> float:
        return self.cost_usd(self.input_tokens, self.output_tokens)

    def complete(self, system: str, user: str) -> str:
        messages = [{"role": "user", "content": user}]
        if self.dry_run:
            doc = self._post(
                "/v1/messages/count_tokens",
                {"model": self.config.model, "system": system, "messages": messages},
            )
            self.calls += 1
            self.input_tokens += int(doc["input_tokens"])
            self.output_tokens += self.config.dry_run_output_tokens
            return STUB_ANSWER
        worst_in = int((len(system) + len(user)) / CHARS_PER_TOKEN_FLOOR) + 1
        worst = self.cost_usd(worst_in, self.config.max_tokens)
        if self.spent_usd + worst > self.config.cap_usd:
            raise BudgetExceeded(
                f"stopping before call {self.calls + 1}: spent ${self.spent_usd:.4f}, the next "
                f"call could cost up to ${worst:.4f}, cap ${self.config.cap_usd:.2f}"
            )
        body: dict[str, Any] = {
            "model": self.config.model,
            "max_tokens": self.config.max_tokens,
            "system": system,
            "messages": messages,
        }
        if self.config.temperature is not None:
            body["temperature"] = self.config.temperature
        doc = self._post("/v1/messages", body)
        usage = doc.get("usage") or {}
        self.calls += 1
        self.input_tokens += int(usage.get("input_tokens", 0))
        self.output_tokens += int(usage.get("output_tokens", 0))
        blocks = doc.get("content") or []
        return "".join(b.get("text", "") for b in blocks if b.get("type") == "text")

    def cost_summary(self, incidents: int) -> dict[str, Any]:
        total = self.spent_usd
        return {
            "estimate_only": self.dry_run,
            "calls": self.calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_usd": round(total, 4),
            "per_incident_usd": round(total / incidents, 5) if incidents else None,
            "incidents": incidents,
        }
