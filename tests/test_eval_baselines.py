"""Baselines, the LLM client and the eval runner. No real LLM is ever called."""

from __future__ import annotations

import http.server
import json
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from faultline.eval.baselines import (
    SYSTEM_PROMPT,
    RawLogLLM,
    baseline_dbt_tests,
    baseline_dbt_tests_guess,
    parse_answer,
    trim_log,
)
from faultline.eval.loader import Incident
from faultline.eval.run import run_eval
from faultline.eval.score import Location, Prediction
from faultline.llm.client import LLMConfig, LLMError, OpenAICompatibleClient, load_config
from tests.conftest import ROOT


def _incident(
    tmp_path: Path, results: list[dict[str, Any]] | None, manifest: dict[str, Any] | None = None
) -> Incident:
    if results is not None:
        (tmp_path / "run_results.json").write_text(json.dumps({"results": results}))
    (tmp_path / "manifest.json").write_text(
        json.dumps(manifest or {"nodes": {}, "sources": {}, "parent_map": {}})
    )
    return Incident("inc", "p", tmp_path)


def test_dbt_tests_detects_failures_and_dead_builds(tmp_path: Path) -> None:
    assert baseline_dbt_tests(
        _incident(tmp_path, [{"unique_id": "model.p.a", "status": "success"}])
    ) == Prediction(False)
    assert baseline_dbt_tests(
        _incident(tmp_path, [{"unique_id": "test.p.t", "status": "fail"}])
    ).detected
    assert baseline_dbt_tests(
        _incident(tmp_path, [{"unique_id": "test.p.t", "status": "warn"}])
    ).detected
    (tmp_path / "run_results.json").unlink()
    assert baseline_dbt_tests(_incident(tmp_path, None)).detected
    assert baseline_dbt_tests(_incident(tmp_path, None)).candidates == ()


def test_guess_orders_upstream_first(tmp_path: Path) -> None:
    manifest = {
        "nodes": {
            "test.p.t1": {"attached_node": "model.p.mart", "column_name": "total"},
            "test.p.t2": {"attached_node": "model.p.stg", "column_name": "id"},
        },
        "sources": {},
        "parent_map": {
            "model.p.mart": ["model.p.stg"],
            "model.p.stg": ["seed.p.raw"],
            "seed.p.raw": [],
        },
    }
    results = [
        {"unique_id": "test.p.t1", "status": "fail"},
        {"unique_id": "test.p.t2", "status": "fail"},
    ]
    pred = baseline_dbt_tests_guess(_incident(tmp_path, results, manifest))
    assert pred.candidates == (Location("model.p.stg", "id"), Location("model.p.mart", "total"))


def test_parse_answer_variants() -> None:
    ok = json.dumps(
        {
            "incident": True,
            "not_confirmed": False,
            "root_causes": [{"node": "model.p.a", "column": "x", "commit": None}],
        }
    )
    assert parse_answer("Sure! " + ok) == Prediction(True, (Location("model.p.a", "x", None),))
    assert parse_answer('{"incident": false}') == Prediction(False)
    assert parse_answer(
        '{"incident": true, "not_confirmed": true, "root_causes": []}'
    ) == Prediction(True)
    assert parse_answer("I think it is the orders table") == Prediction(True)  # unreadable: abstain
    many = {"incident": True, "root_causes": [{"node": f"model.p.{i}"} for i in range(6)]}
    assert len(parse_answer(json.dumps(many)).candidates) == 3


def test_trim_log_keeps_errors_within_budget() -> None:
    log = "\n".join(
        [f"12:00 [debug] noise {i}" for i in range(50)]
        + ["12:01 [info ] OK", "12:02 [error] Database Error in x"]
    )
    trimmed = trim_log(log, budget=40)
    assert "Database Error" in trimmed and "[debug]" not in trimmed


class FakeClient:
    model = "fake-model"

    def __init__(self, answer: str) -> None:
        self.answer = answer
        self.prompts: list[str] = []

    def complete(self, system: str, user: str) -> str:
        assert system == SYSTEM_PROMPT
        self.prompts.append(user)
        return self.answer


def test_raw_log_llm_keeps_raw_answers(tmp_path: Path) -> None:
    client = FakeClient('{"incident": false}')
    method = RawLogLLM(client)
    incident = _incident(
        tmp_path, [{"unique_id": "test.p.t", "status": "fail", "message": "Got 3 results"}]
    )
    assert method(incident) == Prediction(False)
    assert method.raw_answers == {"inc": '{"incident": false}'}
    assert "test.p.t: fail" in client.prompts[0]


@pytest.fixture
def fake_server() -> Iterator[tuple[str, list[dict[str, Any]]]]:
    received: list[dict[str, Any]] = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            received.append({"path": self.path, "body": body})
            out = json.dumps(
                {"choices": [{"message": {"content": '{"incident": false}'}}]}
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)

        def log_message(self, *args: object) -> None:
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}/v1", received
    server.shutdown()


def test_openai_client_payload(fake_server: tuple[str, list[dict[str, Any]]]) -> None:
    url, received = fake_server
    client = OpenAICompatibleClient(LLMConfig(base_url=url, model="qwen-test", seed=7))
    assert client.complete("sys", "user") == '{"incident": false}'
    req = received[0]
    assert req["path"] == "/v1/chat/completions"
    assert req["body"]["model"] == "qwen-test"
    assert req["body"]["temperature"] == 0.0 and req["body"]["seed"] == 7
    assert [m["role"] for m in req["body"]["messages"]] == ["system", "user"]


def test_unreachable_server_raises() -> None:
    client = OpenAICompatibleClient(
        LLMConfig(base_url="http://127.0.0.1:9/v1", model="m", timeout_s=2)
    )
    with pytest.raises(LLMError, match="cannot reach"):
        client.complete("s", "u")


def test_config_comes_from_toml(tmp_path: Path) -> None:
    (tmp_path / "f.toml").write_text('[llm]\nbase_url = "http://h:1/v1/"\nmodel = "m"\n')
    cfg = load_config(tmp_path / "f.toml")
    assert (cfg.base_url, cfg.model, cfg.temperature) == ("http://h:1/v1", "m", 0.0)
    (tmp_path / "g.toml").write_text('[llm]\nbase_url = ""\nmodel = ""\n')
    with pytest.raises(LLMError):
        load_config(tmp_path / "g.toml")
    assert load_config(ROOT / "faultline.toml").model


def _run(tmp_path: Path, baseline: str, client: Any = None) -> dict[str, Any]:
    return run_eval(
        "dev",
        baseline,
        benchmark_dir=ROOT / "benchmark",
        dist_dir=ROOT / "dist",
        runs_dir=ROOT / "build/eval",
        results_dir=tmp_path,
        client=client,
    )


def test_run_eval_writes_tables_and_is_deterministic(tmp_path: Path) -> None:
    doc = _run(tmp_path / "a", "dbt_tests_guess")
    again = _run(tmp_path / "b", "dbt_tests_guess")
    a = (tmp_path / "a" / "dev" / "dbt_tests_guess.json").read_bytes()
    assert a == (tmp_path / "b" / "dev" / "dbt_tests_guess.json").read_bytes()
    assert doc["config_hash"] == again["config_hash"]
    assert doc["metrics"]["faulted"]["n"] == 48 and doc["metrics"]["clean"]["n"] == 30
    md = (tmp_path / "a" / "dev" / "dbt_tests_guess.md").read_text()
    assert "| **all faulted** | 48 |" in md
    assert (tmp_path / "a" / "dev" / "dbt_tests_guess.run.json").is_file()


@pytest.mark.parametrize(
    ("split", "method"),
    [("dev", "dbt_tests"), ("dev", "dbt_tests_guess"), ("dev", "monitors"), ("train", "monitors")],
)
def test_committed_results_match_a_fresh_run(tmp_path: Path, split: str, method: str) -> None:
    """Committed results of every no-LLM method reproduce byte for byte."""
    run_eval(
        split,
        method,
        benchmark_dir=ROOT / "benchmark",
        dist_dir=ROOT / "dist",
        runs_dir=ROOT / "build/eval",
        results_dir=tmp_path,
        config_path=ROOT / "faultline.toml",
    )
    for ext in ("json", "md"):
        fresh = (tmp_path / split / f"{method}.{ext}").read_text()
        committed = (ROOT / "eval" / "results" / split / f"{method}.{ext}").read_text()
        assert fresh == committed, f"{split}/{method}.{ext} is stale: run `make eval-dev`"


def test_raw_log_llm_end_to_end_with_fake_client(tmp_path: Path) -> None:
    client = FakeClient('{"incident": true, "not_confirmed": true, "root_causes": []}')
    doc = _run(tmp_path, "raw_log_llm", client)
    assert doc["config"]["model"] == "fake-model"
    assert doc["metrics"]["faulted"]["not_confirmed"]["count"] == 48
    assert doc["metrics"]["clean"]["false_alarms"]["count"] == 30
    assert all("inject:" not in p for p in client.prompts)
    assert len(client.prompts) == 78
