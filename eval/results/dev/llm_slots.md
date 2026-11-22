# The two LLM slots on dev

Built from the result files in this folder; a row is missing until its run exists.
The hosted reference line is listed apart from faultline's own local results (CLAUDE.md principle 7).

## ranking (triage)

faultline, local models:

| Variant | Top-1 | Top-3 | Wrong top-1 | Not confirmed | False alarms | Cost per incident | File |
|---|---|---|---|---|---|---|---|
| rules only, no model | 89.6% (43/48) | 89.6% (43/48) | 0.0% (0/48) | 0.0% (0/48) | 0.0% (0/30) | local | [triage.md](triage.md) |
| base, Ollama | 87.5% (42/48) | 89.6% (43/48) | 2.1% (1/48) | 0.0% (0/48) | 0.0% (0/30) | local | [triage_llm.md](triage_llm.md) |
| base, MLX | 87.5% (42/48) | 89.6% (43/48) | 2.1% (1/48) | 0.0% (0/48) | 0.0% (0/30) | local | [triage_llm.mlx_base.md](triage_llm.mlx_base.md) |
| tuned on train, MLX | 89.6% (43/48) | 89.6% (43/48) | 0.0% (0/48) | 0.0% (0/48) | 0.0% (0/30) | local | [triage_llm.mlx_ranker.md](triage_llm.mlx_ranker.md) |

Reference line, hosted, not part of faultline:

| Variant | Top-1 | Top-3 | Wrong top-1 | Not confirmed | False alarms | Cost per incident | File |
|---|---|---|---|---|---|---|---|
| not run yet |  |  |  |  |  |  |  |

## raw-log baseline

faultline, local models:

| Variant | Top-1 | Top-3 | Wrong top-1 | Not confirmed | False alarms | Cost per incident | File |
|---|---|---|---|---|---|---|---|
| base, Ollama | 2.1% (1/48) | 2.1% (1/48) | 14.6% (7/48) | 0.0% (0/48) | 0.0% (0/30) | local | [raw_log_llm.md](raw_log_llm.md) |
| base, MLX | 2.1% (1/48) | 2.1% (1/48) | 12.5% (6/48) | 0.0% (0/48) | 0.0% (0/30) | local | [raw_log_llm.mlx_base.md](raw_log_llm.mlx_base.md) |

Reference line, hosted, not part of faultline:

| Variant | Top-1 | Top-3 | Wrong top-1 | Not confirmed | False alarms | Cost per incident | File |
|---|---|---|---|---|---|---|---|
| not run yet |  |  |  |  |  |  |  |
