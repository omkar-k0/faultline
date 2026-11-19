"""Incident store: triage reports in a DuckDB file.

One row per incident (a lineage-connected group of symptoms in one run), keyed
`<run_id>#<n>`. The report is stored whole as JSON, next to the columns needed
to list incidents without opening it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import duckdb

SCHEMA = """
create table if not exists incidents (
    incident_key varchar primary key,
    run_id varchar not null,
    number integer not null,
    status varchar not null,
    symptoms integer not null,
    top_cause varchar,
    report json not null
)
"""


def incident_key(run_id: str, number: int) -> str:
    return f"{run_id}#{number}"


class IncidentStore:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.con = duckdb.connect(str(path))
        self.con.execute(SCHEMA)

    def close(self) -> None:
        self.con.close()

    def save(self, report: dict[str, Any]) -> list[str]:
        """Replace every stored incident of the report's run; return their keys."""
        run_id = str(report["run"])
        self.con.execute("delete from incidents where run_id = ?", [run_id])
        keys = []
        for inc in report["incidents"]:
            key = incident_key(run_id, int(inc["incident"]))
            top = inc["causes"][0]["description"] if inc["causes"] else None
            self.con.execute(
                "insert into incidents values (?, ?, ?, ?, ?, ?, ?)",
                [
                    key,
                    run_id,
                    int(inc["incident"]),
                    inc["status"],
                    len(inc["symptoms"]),
                    top,
                    json.dumps({**inc, "run": run_id}, sort_keys=True),
                ],
            )
            keys.append(key)
        return keys

    def get(self, key: str) -> dict[str, Any] | None:
        row = self.con.execute(
            "select report from incidents where incident_key = ?", [key]
        ).fetchone()
        return None if row is None else dict(json.loads(row[0]))

    def list(self, run_id: str | None = None) -> list[tuple[str, str, int, str | None]]:
        sql = "select incident_key, status, symptoms, top_cause from incidents"
        rows = (
            self.con.execute(sql + " where run_id = ? order by number", [run_id])
            if run_id
            else self.con.execute(sql + " order by incident_key")
        ).fetchall()
        return [(str(a), str(b), int(c), d) for a, b, c, d in rows]
