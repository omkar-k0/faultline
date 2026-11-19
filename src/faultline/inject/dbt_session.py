"""Run the dbt steps for one workspace in a single Python process.

Started as `python -m faultline.inject.dbt_session <workspace>` so each
incident stays isolated in its own process, while dbt is imported and the
project parsed once instead of four times. Exit codes go to
`<workspace>/target/steps.json`.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

STEPS: tuple[tuple[str, ...], ...] = (("deps",), ("seed",), ("build",), ("docs", "generate"))


def main(argv: list[str]) -> int:
    from dbt.cli.main import dbtRunner

    ws = Path(argv[1])
    target = ws / "target"
    target.mkdir(exist_ok=True)
    runner = dbtRunner()
    codes: dict[str, int] = {}
    for step in STEPS:
        args = [*step, "--project-dir", str(ws), "--profiles-dir", str(ws), "--quiet"]
        try:
            result = runner.invoke(args)
            codes[" ".join(step)] = 0 if result.success else 1
        except Exception:  # dbt raised instead of returning a failed result
            codes[" ".join(step)] = 2
        if step == ("build",) and (target / "run_results.json").is_file():
            shutil.copy(target / "run_results.json", target / "build_run_results.json")
    (target / "steps.json").write_text(json.dumps(codes))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
