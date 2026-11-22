"""M6: model profiles, the hosted reference client, and fine-tuning labels.

No test calls a real model or a real API: the reference client gets a fake
transport, and the end-to-end run checks that the API key never reaches a file.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from faultline.eval.run import run_eval
from faultline.eval.score import Truth
from faultline.llm.client import LLMError, load_config
from faultline.llm.finetune import export, is_valid, ranker_answer, ranker_examples
from faultline.llm.reference import (
    AnthropicClient,
    BudgetExceeded,
    ReferenceConfig,
    load_reference_config,
)
from faultline.monitors.core import MonitorConfig
from tests.conftest import ROOT
from tests.test_triage import RAW, _profile, _triage

KEY = "sk-test-not-a-real-key-7f3a"


def _cfg(**over: Any) -> ReferenceConfig:
    base = load_reference_config(ROOT / "faultline.toml")
    return ReferenceConfig(**{**base.__dict__, **over})


class FakeAPI:
    def __init__(self, statuses: list[int] | None = None, out_tokens: int = 40) -> None:
        self.requests: list[tuple[str, dict[str, str], dict[str, Any]]] = []
        self.statuses = list(statuses or [])
        self.out_tokens = out_tokens

    def __call__(
        self, url: str, headers: dict[str, str], body: dict[str, Any]
    ) -> tuple[int, dict[str, Any]]:
        self.requests.append((url, headers, body))
        if self.statuses:
            status = self.statuses.pop(0)
            if status != 200:
                return status, {"error": {"message": "overloaded"}}
        chars = len(body.get("system", "")) + sum(len(m["content"]) for m in body["messages"])
        if url.endswith("/count_tokens"):
            return 200, {"input_tokens": chars // 4}
        answer = '{"order": [1], "summary": "fake"}'
        if "dbt log" in body["messages"][0]["content"]:
            answer = '{"incident": false, "not_confirmed": false, "root_causes": []}'
        return 200, {
            "content": [{"type": "text", "text": answer}],
            "usage": {"input_tokens": chars // 4, "output_tokens": self.out_tokens},
        }


@pytest.fixture
def key(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv("ANTHROPIC_API_KEY", KEY)
    return KEY


# --- profiles ------------------------------------------------------------------


def test_profile_overlays_llm_section() -> None:
    base = load_config(ROOT / "faultline.toml")
    tuned = load_config(ROOT / "faultline.toml", "mlx_ranker")
    assert base.base_url.endswith(":11434/v1") and base.adapter is None
    assert tuned.base_url == "http://localhost:8080/v1"
    assert tuned.adapter == "build/adapters/ranker" and tuned.profile == "mlx_ranker"
    assert tuned.temperature == base.temperature == 0.0
    with pytest.raises(LLMError, match=r"no \[llm.profiles.nope\]"):
        load_config(ROOT / "faultline.toml", "nope")


# --- the reference client ------------------------------------------------------


def test_reference_needs_the_key_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(LLMError, match="ANTHROPIC_API_KEY"):
        AnthropicClient(_cfg())


def test_reference_sends_the_key_only_in_the_header(key: str) -> None:
    api = FakeAPI()
    client = AnthropicClient(_cfg(), transport=api)
    assert client.complete("sys", "hello") == '{"order": [1], "summary": "fake"}'
    url, headers, body = api.requests[0]
    assert url == "https://api.anthropic.com/v1/messages"
    assert headers["x-api-key"] == key and key not in json.dumps(body)
    assert body["model"] == "claude-opus-5-5" and "temperature" not in body
    assert key not in repr(client) and key not in json.dumps(client.config.public())
    assert key not in json.dumps(client.cost_summary(1))


def test_temperature_is_sent_only_when_set(key: str) -> None:
    api = FakeAPI()
    AnthropicClient(_cfg(temperature=0.0), transport=api).complete("s", "u")
    assert api.requests[0][2]["temperature"] == 0.0


def test_reference_cost_is_counted_from_usage(key: str) -> None:
    client = AnthropicClient(_cfg(), transport=FakeAPI(out_tokens=100))
    client.complete("s" * 400, "u" * 3600)  # 1000 input tokens in the fake
    assert (client.input_tokens, client.output_tokens) == (1000, 100)
    assert client.spent_usd == pytest.approx((1000 * 4 + 100 * 20) / 1e6)
    assert client.cost_summary(2)["per_incident_usd"] == pytest.approx(0.003)


def test_reference_stops_before_the_cap(key: str) -> None:
    api = FakeAPI()
    client = AnthropicClient(_cfg(cap_usd=0.05), transport=api)
    client.complete("s", "u" * 4000)
    with pytest.raises(BudgetExceeded, match=r"cap \$0.05"):
        for _ in range(100):
            client.complete("s", "u" * 20000)
    assert client.spent_usd <= 0.05  # never went over


def test_reference_retries_overload_then_gives_up(key: str) -> None:
    waits: list[float] = []
    ok = AnthropicClient(_cfg(), transport=FakeAPI(statuses=[529, 429]), sleep=waits.append)
    ok.complete("s", "u")
    assert waits == [5, 20] and ok.calls == 1
    bad = AnthropicClient(_cfg(), transport=FakeAPI(statuses=[400]), sleep=waits.append)
    with pytest.raises(LLMError, match="answered 400"):
        bad.complete("s", "u")


def test_dry_run_counts_tokens_and_bills_nothing(key: str) -> None:
    api = FakeAPI()
    client = AnthropicClient(_cfg(), dry_run=True, transport=api)
    client.complete("s" * 100, "u" * 300)
    assert all(url.endswith("/v1/messages/count_tokens") for url, _, _ in api.requests)
    assert client.input_tokens == 100 and client.output_tokens == 300  # assumed output
    assert client.cost_summary(1)["estimate_only"] is True


def test_reference_run_is_labelled_and_leaves_no_key(key: str, tmp_path: Path) -> None:
    client = AnthropicClient(_cfg(), transport=FakeAPI())
    doc = run_eval(
        "dev",
        "raw_log_llm",
        benchmark_dir=ROOT / "benchmark",
        dist_dir=ROOT / "dist",
        runs_dir=ROOT / "build/eval",
        results_dir=tmp_path,
        client=client,
        variant="reference",
    )
    out = tmp_path / "dev"
    assert doc["baseline"] == "raw_log_llm.reference"
    assert doc["config"]["reference_line"]["model"] == "claude-opus-5-5"
    assert doc["cost"]["calls"] == 78 and doc["cost"]["per_incident_usd"] > 0
    for f in out.iterdir():
        assert key not in f.read_text(), f.name
    slots = (out / "llm_slots.md").read_text()
    local, _, reference = slots.partition("## raw-log baseline")[2].partition("Reference line")
    assert "raw_log_llm.reference.md" in reference and "raw_log_llm.reference" not in local


def test_dry_run_writes_nothing(key: str, tmp_path: Path) -> None:
    client = AnthropicClient(_cfg(), dry_run=True, transport=FakeAPI())
    doc = run_eval(
        "dev",
        "raw_log_llm",
        benchmark_dir=ROOT / "benchmark",
        dist_dir=ROOT / "dist",
        runs_dir=ROOT / "build/eval",
        results_dir=tmp_path,
        client=client,
        variant="reference",
        write=False,
    )
    assert doc["cost"]["estimate_only"] and not (tmp_path / "dev").exists()


def test_variant_needs_an_llm_method() -> None:
    with pytest.raises(ValueError, match="model variant"):
        run_eval("dev", "monitors", variant="reference")


# --- fine-tuning labels --------------------------------------------------------


def _truth(node: str | None, column: str | None = None, commit: str | None = None) -> Truth:
    ft = None if node is None else "null_spike"
    return Truth("run", "p", ft, "data" if ft else None, node, None, column, commit)


def test_finetune_reads_train_only(tmp_path: Path) -> None:
    for split in ("dev", "heldout"):
        with pytest.raises(ValueError, match="train only"):
            export("ranker", tmp_path, MonitorConfig(), split=split)
    assert not any(tmp_path.iterdir())


def test_ranker_answer_puts_the_truth_first() -> None:
    causes = [
        {"node": "a", "column": "x", "commit": None, "description": "A", "explains": [1]},
        {"node": "b", "column": "y", "commit": None, "description": "B", "explains": [1, 2]},
    ]
    answer = json.loads(ranker_answer(causes, _truth("b", "y")) or "{}")
    assert answer["order"] == [2, 1]
    assert answer["summary"].startswith("Most likely: B.") and "2 of" in answer["summary"]
    assert ranker_answer(causes, _truth("c")) is None


def test_ranker_examples_cover_shuffled_orders() -> None:
    t = _triage(_profile(rows=120, distinct_ids=100))  # two or more survivors
    examples = list(ranker_examples(t, _truth(RAW, "id")))
    assert len(examples) >= 2 and len({e.user for e in examples}) == len(examples)
    for e in examples:
        first = json.loads(e.answer)["order"][0]
        line = next(ln for ln in e.user.splitlines() if ln.startswith(f"{first}. "))
        assert "seed.p.raw.id" in line or "seed.p.raw (key id)" in line  # both match the truth


def test_validation_share_is_stable() -> None:
    ids = [f"inc_x_train_{i:03d}" for i in range(400)]
    share = sum(map(is_valid, ids)) / len(ids)
    assert 0.05 < share < 0.15 and is_valid(ids[0]) == is_valid(ids[0])


def test_failed_rerank_calls_mark_the_run_incomplete(key: str, tmp_path: Path) -> None:
    api = FakeAPI(statuses=[200] * 5 + [400] * 500)
    client = AnthropicClient(_cfg(), transport=api, sleep=lambda _s: None)
    doc = run_eval(
        "dev",
        "triage_llm",
        benchmark_dir=ROOT / "benchmark",
        dist_dir=ROOT / "dist",
        runs_dir=ROOT / "build/eval",
        results_dir=tmp_path,
        client=client,
        variant="reference",
    )
    assert doc["incomplete"]["failed_llm_calls"] > 0
    md = (tmp_path / "dev" / "triage_llm.reference.md").read_text()
    assert "Incomplete:" in md
    slots = (tmp_path / "dev" / "llm_slots.md").read_text()
    assert "incomplete:" in slots and "not a result" in slots
