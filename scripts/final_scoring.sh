#!/usr/bin/env bash
# The one final scoring of the frozen split (CLAUDE.md, M8). Run once, on a Mac with
# the M6 adapters in build/adapters/ and ANTHROPIC_API_KEY set in this shell.
#
# Order: deterministic methods, then the local models through MLX (the script starts
# and stops the server itself), then the hosted reference after a free dry run and
# your typed "yes". Each method is scored once: a method that already has a result
# file is skipped, so a run cut short can be continued without scoring anything twice.
set -euo pipefail

SPLIT=heldout
OUT=eval/results/$SPLIT
MODEL=mlx-community/Qwen2.5-7B-Instruct-4bit
FL="uv run --frozen faultline"

if [[ -n "$(git status --porcelain -- src benchmark faultline.toml)" ]]; then
  echo "src/, benchmark/ or faultline.toml has uncommitted changes; commit first." >&2
  exit 1
fi
echo "Final scoring at commit $(git rev-parse --short HEAD)."

score() {  # name, then the eval arguments
  local name=$1; shift
  if [[ -f "$OUT/$name.json" ]] && ! grep -q '"incomplete"' "$OUT/$name.json"; then
    echo "skip $name (already scored)"; return
  fi
  $FL eval --split $SPLIT "$@"
}

# 1. Deterministic.
score dbt_tests --baseline dbt_tests
score dbt_tests_guess --baseline dbt_tests_guess
score monitors --baseline monitors
score triage --baseline triage
score triage.no_tests --baseline triage --ablate tests
score triage.no_lineage --baseline triage --ablate lineage

# 2. Local models through MLX.
serve() {  # adapter path or "" for the base model
  # ${extra[@]+...}: macOS bash 3.2 treats an empty array as unset under set -u.
  local extra=()
  [[ -n "$1" ]] && extra=(--adapter-path "$1")
  uv run --frozen --group mlx mlx_lm.server --model $MODEL ${extra[@]+"${extra[@]}"} --port 8080 \
    > build/mlx_server.log 2>&1 &
  SERVER=$!
  for _ in $(seq 1 120); do
    curl -s localhost:8080/v1/models >/dev/null 2>&1 && return
    sleep 5
  done
  echo "MLX server did not start; see build/mlx_server.log" >&2
  kill "$SERVER" 2>/dev/null || true; exit 1
}
stop() { kill "$SERVER" 2>/dev/null || true; wait "$SERVER" 2>/dev/null || true; }
mkdir -p build
needs() {  # true when any of these is missing or incomplete
  for n in "$@"; do
    [[ -f "$OUT/$n.json" ]] || return 0
    grep -q '"incomplete"' "$OUT/$n.json" && return 0
  done
  return 1
}

if needs triage_llm.mlx_base raw_log_llm.mlx_base; then
  serve ""
  score triage_llm.mlx_base --baseline triage_llm --llm-profile mlx_base
  score raw_log_llm.mlx_base --baseline raw_log_llm --llm-profile mlx_base
  stop
fi
if needs triage_llm.mlx_ranker; then
  serve build/adapters/ranker
  score triage_llm.mlx_ranker --baseline triage_llm --llm-profile mlx_ranker
  stop
fi
if needs raw_log_llm.mlx_raw_log; then
  serve build/adapters/raw_log
  score raw_log_llm.mlx_raw_log --baseline raw_log_llm --llm-profile mlx_raw_log
  stop
fi

# 3. The hosted reference, in the same final run.
if needs raw_log_llm.reference triage_llm.reference; then
  : "${ANTHROPIC_API_KEY:?set ANTHROPIC_API_KEY in this shell first}"
  $FL eval --split $SPLIT --baseline raw_log_llm --reference --dry-run
  $FL eval --split $SPLIT --baseline triage_llm --reference --dry-run
  read -r -p "Spend that on the reference? Type yes: " answer
  [[ "$answer" == "yes" ]] || { echo "Stopped before the reference."; exit 0; }
  score raw_log_llm.reference --baseline raw_log_llm --reference
  score triage_llm.reference --baseline triage_llm --reference
fi

echo
echo "Done at commit $(git rev-parse --short HEAD). Now:"
echo "  git add $OUT && git commit -m 'eval: final scoring' && git push"
