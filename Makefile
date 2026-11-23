.PHONY: setup build-projects check lint typecheck test clean benchmark fetch-benchmark eval-dev eval-dev-llm eval-dev-triage-llm setup-mlx finetune-data finetune-ranker finetune-raw-log serve-mlx-base serve-mlx-ranker serve-mlx-raw-log eval-dev-mlx-base eval-dev-mlx-ranker eval-dev-mlx-raw-log reference-dry-run eval-dev-reference eval-dev-fixes eval-dev-testgen final-scoring repro

PROJECTS := jaffle_shop stripe court_cases jira
UV := uv
export DBT_SEND_ANONYMOUS_USAGE_STATS := false

setup:
	$(UV) sync --frozen
	$(MAKE) build-projects

build-projects:
	@for p in $(PROJECTS); do \
		echo "== dbt build $$p"; \
		mkdir -p projects/$$p/target; \
		export FAULTLINE_DUCKDB_DIR=$(CURDIR)/projects/$$p/target; \
		for cmd in deps seed build "docs generate"; do \
			$(UV) run --frozen dbt $$cmd --project-dir projects/$$p --profiles-dir projects/$$p || exit 1; \
		done; \
	done

lint:
	$(UV) run --frozen ruff check .
	$(UV) run --frozen ruff format --check .

typecheck:
	$(UV) run --frozen mypy

test:
	$(UV) run --frozen pytest

check: lint typecheck build-projects test

benchmark:
	@test -n "$(SPLIT)" || (echo "usage: make benchmark SPLIT=<name from benchmark/plan.toml>"; exit 2)
	$(UV) run --frozen faultline benchmark generate --split $(SPLIT)

fetch-benchmark:
	$(UV) run --frozen python -c "from pathlib import Path; from faultline.eval.loader import load_incidents; [print(s, len(load_incidents(s)[0]), 'incidents ready') for s in ('train', 'dev')]"

eval-dev:
	$(UV) run --frozen faultline eval --split dev --baseline dbt_tests
	$(UV) run --frozen faultline eval --split dev --baseline dbt_tests_guess
	$(UV) run --frozen faultline eval --split dev --baseline monitors
	$(UV) run --frozen faultline eval --split train --baseline monitors
	$(UV) run --frozen faultline eval --split dev --baseline triage
	$(UV) run --frozen faultline eval --split train --baseline triage
	$(UV) run --frozen faultline eval --split dev --baseline triage --ablate tests
	$(UV) run --frozen faultline eval --split dev --baseline triage --ablate lineage

# Needs a local model server (see docs/EVAL.md). Never runs in CI.
eval-dev-llm:
	$(UV) run --frozen faultline eval --split dev --baseline raw_log_llm

# The full triage with the local LLM re-ranker. Needs a local model server. Never runs in CI.
eval-dev-triage-llm:
	$(UV) run --frozen faultline eval --split dev --baseline triage_llm

clean:
	rm -rf .venv .pytest_cache .mypy_cache .ruff_cache build dist
	@for p in $(PROJECTS); do rm -rf projects/$$p/target projects/$$p/logs; done

# M7: rebuilds every dev run (about 160 dbt builds in all); not part of `make check`.
eval-dev-fixes:
	$(UV) run --frozen faultline fix eval --split dev

eval-dev-testgen:
	$(UV) run --frozen faultline testgen eval --split dev

# From a clean clone: set up, fetch the benchmark, then check every number.
repro: setup fetch-benchmark
	$(UV) run --frozen faultline repro

# The one final scoring (M8). On a Mac with the adapters; see docs/EVAL.md.
final-scoring:
	./scripts/final_scoring.sh

# ---------------------------------------------------------------- M6, on a Mac
# Apple silicon only; none of this runs in CI. Steps in docs/EVAL.md.
MLX_MODEL := mlx-community/Qwen2.5-7B-Instruct-4bit
MLX := $(UV) run --frozen --group mlx

setup-mlx:
	$(UV) sync --frozen --group mlx

finetune-data:
	$(UV) run --frozen faultline finetune export --slot ranker
	$(UV) run --frozen faultline finetune export --slot raw_log

finetune-ranker:
	$(MLX) mlx_lm.lora -c finetune/ranker.yaml

finetune-raw-log:
	$(MLX) mlx_lm.lora -c finetune/raw_log.yaml

# Each server runs in its own terminal; stop it with Ctrl+C before starting the next.
serve-mlx-base:
	$(MLX) mlx_lm.server --model $(MLX_MODEL) --port 8080

serve-mlx-ranker:
	$(MLX) mlx_lm.server --model $(MLX_MODEL) --adapter-path build/adapters/ranker --port 8080

serve-mlx-raw-log:
	$(MLX) mlx_lm.server --model $(MLX_MODEL) --adapter-path build/adapters/raw_log --port 8080

eval-dev-mlx-base:
	$(UV) run --frozen faultline eval --split dev --baseline triage_llm --llm-profile mlx_base
	$(UV) run --frozen faultline eval --split dev --baseline raw_log_llm --llm-profile mlx_base

eval-dev-mlx-ranker:
	$(UV) run --frozen faultline eval --split dev --baseline triage_llm --llm-profile mlx_ranker

eval-dev-mlx-raw-log:
	$(UV) run --frozen faultline eval --split dev --baseline raw_log_llm --llm-profile mlx_raw_log

# The hosted reference. Needs ANTHROPIC_API_KEY set in the shell, never in a file.
reference-dry-run:
	$(UV) run --frozen faultline eval --split dev --baseline raw_log_llm --reference --dry-run
	$(UV) run --frozen faultline eval --split dev --baseline triage_llm --reference --dry-run

eval-dev-reference:
	$(UV) run --frozen faultline eval --split dev --baseline raw_log_llm --reference
	$(UV) run --frozen faultline eval --split dev --baseline triage_llm --reference
