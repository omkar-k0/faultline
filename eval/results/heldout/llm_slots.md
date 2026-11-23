# The two LLM slots on heldout

Built from the result files in this folder; a row is missing until its run exists.
The hosted reference line is listed apart from faultline's own local results (CLAUDE.md principle 7).

## ranking (triage)

faultline, local models:

| Variant | Top-1 | Top-3 | Wrong top-1 | Not confirmed | False alarms | Cost per incident | File |
|---|---|---|---|---|---|---|---|
| rules only, no model | 72.9% (35/48) | 75.0% (36/48) | 6.2% (3/48) | 0.0% (0/48) | 10.0% (1/10) | local | [triage.md](triage.md) |
| base, MLX | 70.8% (34/48) | 75.0% (36/48) | 8.3% (4/48) | 0.0% (0/48) | 10.0% (1/10) | local | [triage_llm.mlx_base.md](triage_llm.mlx_base.md) |
| tuned on train, MLX | 75.0% (36/48) | 75.0% (36/48) | 4.2% (2/48) | 0.0% (0/48) | 10.0% (1/10) | local | [triage_llm.mlx_ranker.md](triage_llm.mlx_ranker.md) |

Reference line, hosted, not part of faultline:

| Variant | Top-1 | Top-3 | Wrong top-1 | Not confirmed | False alarms | Cost per incident | File |
|---|---|---|---|---|---|---|---|
| Claude, hosted (reference) | 72.9% (35/48) | 75.0% (36/48) | 6.2% (3/48) | 0.0% (0/48) | 10.0% (1/10) | $0.0084 | [triage_llm.reference.md](triage_llm.reference.md) |

## raw-log baseline

faultline, local models:

| Variant | Top-1 | Top-3 | Wrong top-1 | Not confirmed | False alarms | Cost per incident | File |
|---|---|---|---|---|---|---|---|
| base, MLX | 0.0% (0/48) | 2.1% (1/48) | 10.4% (5/48) | 0.0% (0/48) | 0.0% (0/10) | local | [raw_log_llm.mlx_base.md](raw_log_llm.mlx_base.md) |
| tuned on train, MLX | 2.1% (1/48) | 2.1% (1/48) | 37.5% (18/48) | 0.0% (0/48) | 20.0% (2/10) | local | [raw_log_llm.mlx_raw_log.md](raw_log_llm.mlx_raw_log.md) |

Reference line, hosted, not part of faultline:

| Variant | Top-1 | Top-3 | Wrong top-1 | Not confirmed | False alarms | Cost per incident | File |
|---|---|---|---|---|---|---|---|
| Claude, hosted (reference) | 8.3% (4/48) | 8.3% (4/48) | 4.2% (2/48) | 20.8% (10/48) | 0.0% (0/10) | $0.0515 | [raw_log_llm.reference.md](raw_log_llm.reference.md) |
