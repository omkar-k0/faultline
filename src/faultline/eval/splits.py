"""The frozen final split: the one file in src/ that may name it.

CLAUDE.md: benchmark/heldout/ is frozen; only `faultline eval --split heldout` may
touch it, and only to score. Here that means:

- scoring is reachable only through `run_eval` (the `faultline eval` command), which
  passes `allow_final=True`; every other command keeps to train and dev;
- each method is scored on it once: an existing complete result stops a second run;
- nothing here or anywhere else in src/ reads the split to build, tune or train.
"""

from __future__ import annotations

import json
from pathlib import Path

FINAL_SPLIT = "heldout"


class ScoredAlready(RuntimeError):
    """This method already has a result on the final split; it is scored once."""


def check_final_scoring(split: str, results_dir: Path, name: str) -> None:
    """Refuse a second scoring. A result marked incomplete (failed model calls) was never
    a result, so it may be scored again; nothing else may."""
    path = results_dir / split / f"{name}.json"
    if split == FINAL_SPLIT and path.exists():
        if "incomplete" in json.loads(path.read_text()):
            return
        raise ScoredAlready(
            f"{name} was already scored on {FINAL_SPLIT} "
            f"({results_dir / split / name}.json); it is scored once"
        )
