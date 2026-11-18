"""Natural run-to-run variation, applied before any fault.

Without it every clean run is identical, and a monitor that alarms on any
change would score perfectly on clean runs. Rules:
- numeric measures get multiplicative noise (sd 2%), integers stay integers;
- keys, dates, timestamps, booleans and text are never changed;
- rows are never dropped. Dropping payments left orders without a payment and
  failed `not_null` tests on clean runs, so row counts stay as shipped. Known
  weakness: clean runs do not vary in volume.
"""

from __future__ import annotations

import random
from pathlib import Path

from faultline.inject.catalog import FaultCatalog
from faultline.inject.workspace import read_csv, write_csv

NOISE_SD = 0.02


def _noisy(value: str, rng: random.Random) -> str:
    if value == "":
        return value
    factor = 1.0 + rng.gauss(0.0, NOISE_SD)
    if "." in value:
        decimals = len(value.split(".", 1)[1])
        return f"{float(value) * factor:.{decimals}f}"
    return str(round(int(value) * factor))


def resample(workspace: Path, catalog: FaultCatalog, rng: random.Random) -> dict[str, int]:
    """Rewrite every seed file in place. Returns the row count per seed node."""
    kept: dict[str, int] = {}
    for seed in catalog.seeds:
        path = workspace / seed.file
        header, rows = read_csv(path)
        measures = [i for i, c in enumerate(seed.columns) if c.role == "numeric"]
        for row in rows:
            for i in measures:
                if i < len(row):
                    row[i] = _noisy(row[i], rng)
        write_csv(path, header, rows)
        kept[seed.node] = len(rows)
    return kept
