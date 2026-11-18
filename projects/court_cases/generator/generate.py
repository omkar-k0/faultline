"""Generate the synthetic seed data for the court_cases project.

Every court, judge, lawyer, party and case is fictional. Names are built from
codes so none points at a real person or court. The data follows the shape of
a court case lifecycle: filing, hearings (many adjourned), orders, court fees
and their payments. Local times are Indian Standard Time without a zone, as a
court register would record them; the courts table carries the UTC offset.

Run from the repository root:
    python projects/court_cases/generator/generate.py
Same seed, same files.
"""

from __future__ import annotations

import csv
import random
from datetime import date, datetime, timedelta
from pathlib import Path

SEED = 20261118
OUT = Path(__file__).resolve().parents[1] / "seeds"

STATES = ["Maharashtra", "Karnataka", "Tamil Nadu", "Delhi", "Gujarat", "West Bengal"]
COURT_LEVELS = ["district", "district", "district", "high"]
CASE_TYPES = {"civil": 0.34, "criminal": 0.26, "commercial": 0.18, "family": 0.14, "writ": 0.08}
DOCUMENT_TYPES = [
    "plaint",
    "written_statement",
    "affidavit",
    "application",
    "rejoinder",
    "evidence",
    "vakalatnama",
]
ADJOURN_REASONS = [
    "counsel_unavailable",
    "documents_pending",
    "bench_unavailable",
    "party_absent",
    "time_sought",
    "strike",
]
PAY_METHODS = ["e_stamp", "upi", "netbanking", "court_counter"]
START = datetime(2023, 1, 2)
END = datetime(2026, 6, 30)


def write(name: str, header: list[str], rows: list[list[object]]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / f"{name}.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


def ts(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S")


def court_time(rng: random.Random, day: date) -> datetime:
    """A slot in court hours, 10:30 to 16:30 local time."""
    minutes = rng.randrange(0, 6 * 60, 15)
    return datetime(day.year, day.month, day.day, 10, 30) + timedelta(minutes=minutes)


def next_working_day(day: date) -> date:
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day


def main() -> None:
    rng = random.Random(SEED)

    courts = []
    for i in range(1, 13):
        level = rng.choice(COURT_LEVELS)
        state = STATES[(i - 1) % len(STATES)]
        name = f"{'High Court' if level == 'high' else 'District Court'} {i:02d} ({state})"
        courts.append([f"CRT{i:02d}", name, state, level, 330])
    write(
        "raw_courts",
        ["court_id", "court_name", "state", "court_level", "utc_offset_minutes"],
        courts,
    )

    judges = []
    for i in range(1, 37):
        court = courts[(i - 1) % len(courts)][0]
        appointed = START.date() - timedelta(days=rng.randrange(200, 4000))
        judges.append([f"JDG{i:03d}", court, f"Presiding Officer {i:03d}", appointed.isoformat()])
    write("raw_judges", ["judge_id", "court_id", "judge_name", "appointed_on"], judges)

    lawyers = []
    for i in range(1, 71):
        enrolled = START.date() - timedelta(days=rng.randrange(300, 9000))
        firm = f"Chambers {rng.randrange(1, 19):02d}" if rng.random() < 0.7 else ""
        lawyers.append(
            [
                f"LAW{i:03d}",
                f"BAR/{rng.randrange(1990, 2022)}/{i:05d}",
                f"Advocate {i:03d}",
                firm,
                enrolled.isoformat(),
            ]
        )
    write("raw_lawyers", ["lawyer_id", "bar_number", "lawyer_name", "firm", "enrolled_on"], lawyers)

    parties = []
    for i in range(1, 361):
        ptype = rng.choices(["individual", "company", "government"], [0.62, 0.28, 0.10])[0]
        parties.append([f"PTY{i:04d}", ptype, f"{ptype.title()} Party {i:04d}", rng.choice(STATES)])
    write("raw_parties", ["party_id", "party_type", "party_name", "state"], parties)

    cases, hearings, filings, orders, payments = [], [], [], [], []
    hearing_n = filing_n = order_n = payment_n = 0
    judges_by_court: dict[str, list[str]] = {}
    for j in judges:
        judges_by_court.setdefault(str(j[1]), []).append(str(j[0]))
    span = (END - START).days

    for i in range(1, 841):
        court = rng.choice(courts)
        court_id = str(court[0])
        ctype = rng.choices(list(CASE_TYPES), list(CASE_TYPES.values()))[0]
        filed_day = next_working_day((START + timedelta(days=rng.randrange(0, span - 120))).date())
        filed_at = court_time(rng, filed_day)
        petitioner, respondent = rng.sample(parties, 2)
        lead = rng.choice(lawyers)
        judge = rng.choice(judges_by_court[court_id])
        claim = round(rng.lognormvariate(13.0, 1.1), -2) if ctype in {"civil", "commercial"} else ""

        # hearings: most are adjourned; a case ends disposed, or stays pending
        n_hearings = max(1, int(rng.gammavariate(2.2, 3.0)))
        day = filed_day
        disposed_on = ""
        status = "pending"
        last_hearing_id = None
        for h in range(n_hearings):
            day = next_working_day(day + timedelta(days=rng.randrange(14, 90)))
            if datetime(day.year, day.month, day.day) > END:
                break
            hearing_n += 1
            hid = f"HRG{hearing_n:06d}"
            final = h == n_hearings - 1 and rng.random() < 0.72
            if final:
                outcome, reason = "disposed", ""
            elif rng.random() < 0.63:
                outcome, reason = "adjourned", rng.choice(ADJOURN_REASONS)
            else:
                outcome, reason = rng.choice(["heard", "heard", "reserved"]), ""
            duration = rng.randrange(5, 25) if outcome == "adjourned" else rng.randrange(15, 120)
            hearings.append(
                [hid, f"CASE{i:05d}", ts(court_time(rng, day)), outcome, reason, duration]
            )
            last_hearing_id = hid
            if outcome in {"heard", "reserved"} and rng.random() < 0.25:
                order_n += 1
                orders.append(
                    [
                        f"ORD{order_n:06d}",
                        f"CASE{i:05d}",
                        hid,
                        "interim",
                        day.isoformat(),
                        rng.choice(["allowed", "dismissed", "partly_allowed"]),
                    ]
                )
            if final:
                status, disposed_on = "disposed", day.isoformat()
                order_n += 1
                orders.append(
                    [
                        f"ORD{order_n:06d}",
                        f"CASE{i:05d}",
                        hid,
                        "final",
                        day.isoformat(),
                        rng.choices(
                            ["allowed", "dismissed", "partly_allowed", "settled"],
                            [0.38, 0.27, 0.15, 0.20],
                        )[0],
                    ]
                )
                break
        if status == "pending" and rng.random() < 0.05:
            status = rng.choice(["transferred", "withdrawn"])
        cases.append(
            [
                f"CASE{i:05d}",
                f"{ctype[:3].upper()}/{filed_day.year}/{i:05d}",
                court_id,
                ctype,
                ts(filed_at),
                petitioner[0],
                respondent[0],
                lead[0],
                judge,
                status,
                claim,
                disposed_on,
            ]
        )
        _ = last_hearing_id

        # filings and the court fee paid for each
        n_filings = 1 + int(rng.expovariate(1 / 2.2))
        fday = filed_day
        for f in range(n_filings):
            filing_n += 1
            doc = "plaint" if f == 0 else rng.choice(DOCUMENT_TYPES[1:])
            fday = next_working_day(fday + timedelta(days=0 if f == 0 else rng.randrange(7, 120)))
            if datetime(fday.year, fday.month, fday.day) > END:
                break
            pages = rng.randrange(2, 180)
            fee = (
                500 + pages * 10
                if doc != "plaint"
                else round(1000 + (claim or 0) * 0.01, 0)
                if claim
                else 1500
            )
            fee = min(fee, 300000)
            fid = f"FIL{filing_n:06d}"
            by = lead[0] if rng.random() < 0.8 else rng.choice(lawyers)[0]
            filings.append(
                [fid, f"CASE{i:05d}", by, doc, ts(court_time(rng, fday)), pages, int(fee)]
            )
            # most fees paid once, in full; some in two parts
            parts = 2 if rng.random() < 0.12 else 1
            for p in range(parts):
                payment_n += 1
                amount = (
                    int(fee)
                    if parts == 1
                    else (int(fee) // 2 if p == 0 else int(fee) - int(fee) // 2)
                )
                paid = court_time(rng, fday) + timedelta(days=p * rng.randrange(1, 20))
                payments.append(
                    [f"PAY{payment_n:06d}", fid, ts(paid), amount, rng.choice(PAY_METHODS)]
                )

    write(
        "raw_cases",
        [
            "case_id",
            "case_number",
            "court_id",
            "case_type",
            "filed_at_local",
            "petitioner_party_id",
            "respondent_party_id",
            "lead_lawyer_id",
            "judge_id",
            "status",
            "claim_amount_inr",
            "disposed_on",
        ],
        cases,
    )
    write(
        "raw_hearings",
        [
            "hearing_id",
            "case_id",
            "scheduled_at_local",
            "outcome",
            "adjournment_reason",
            "duration_minutes",
        ],
        hearings,
    )
    write(
        "raw_filings",
        [
            "filing_id",
            "case_id",
            "filed_by_lawyer_id",
            "document_type",
            "filed_at_local",
            "page_count",
            "court_fee_inr",
        ],
        filings,
    )
    write(
        "raw_orders",
        ["order_id", "case_id", "hearing_id", "order_type", "order_date", "order_outcome"],
        orders,
    )
    write(
        "raw_fee_payments",
        ["payment_id", "filing_id", "paid_at_local", "amount_inr", "payment_method"],
        payments,
    )


if __name__ == "__main__":
    main()
