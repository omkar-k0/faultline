.PHONY: setup build-projects check lint typecheck test clean benchmark

PROJECTS := jaffle_shop stripe court_cases
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

clean:
	rm -rf .venv .pytest_cache .mypy_cache .ruff_cache build dist
	@for p in $(PROJECTS); do rm -rf projects/$$p/target projects/$$p/logs; done
