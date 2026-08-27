"""
Ingest entry point.

Run it with:

    docker compose exec backend python -m app.ingest

The CSVs are mounted read-only at /data. `rejects.csv` is written to the repo
root (see REJECTS_PATH below and the extra mount in docker-compose.yml).

--------------------------------------------------------------------------
The client's five import rules, and where each one lives
--------------------------------------------------------------------------

1. "A bad row must not stop the import."
   Every field is parsed inside _field(), which converts a ValueError into a
   reason string instead of letting it escape. A row accumulates *all* of its
   reasons rather than short-circuiting on the first, because telling the
   client "row 900008 has a negative duration" when it also finishes before it
   starts would send them round the loop twice.

2. "Ratings are 1 to 5 ... Reject it and log it. Do not clamp it."
   _parse_rating(). The whole row is rejected, not just the field: the rule is
   stated alongside "bad rows go to rejects.csv", and silently nulling a value
   the client explicitly called a data error would hide it.

3. "Dates arrive day first ... All of it is Asia/Kolkata ... a second customer
   is being onboarded in Dubai."
   parse_client_datetime() attaches Asia/Kolkata; the column is TIMESTAMPTZ,
   which Postgres stores as UTC; the reporting zone lives on
   clients.reporting_timezone. See docs/adr/0001.

4. "A respondent counts only once per survey."
   _resolve_duplicates(), and enforced for good by the UNIQUE constraint
   uq_responses_one_per_respondent. See docs/adr/0003 for which row wins.

5. "Re-running the ingest on the same file must not double the data."
   Natural primary keys plus INSERT ... ON CONFLICT DO UPDATE. Second run
   updates 38,000 rows rather than inserting 38,000 more. CI asserts it by
   running the ingest twice and diffing row counts.
"""

from __future__ import annotations

import csv
import os
import sys
import time
from collections import Counter, defaultdict
from typing import Any, Callable, Iterable

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from .db import SessionLocal, engine
from .models import (
    OPEN_STATUSES,
    RESPONSE_STATUSES,
    Base,
    Client,
    IngestRun,
    Respondent,
    Response,
    Survey,
)
from .normalize import (
    blank_to_none,
    normalise_email,
    parse_client_datetime,
    parse_duration_seconds,
)

DATA_DIR = os.getenv("DATA_DIR", "/data")
SURVEYS_CSV = os.path.join(DATA_DIR, "surveys.csv")
RESPONSES_CSV = os.path.join(DATA_DIR, "responses.csv")

# /data is mounted read-only, so rejects cannot be written beside the source.
# docker-compose mounts the repo root at /repo for this.
REJECTS_PATH = os.getenv("REJECTS_PATH", "/repo/rejects.csv")

RESPONSE_COLUMNS = [
    "response_id",
    "survey_id",
    "respondent_name",
    "respondent_email",
    "started_at",
    "completed_at",
    "status",
    "rating",
    "duration_seconds",
    "channel",
    "free_text",
]

# Which response survives when one respondent answered the same survey twice.
# Higher wins. See docs/adr/0003: outcome first, then recency, then id -- a
# total order, so re-running the ingest cannot quietly pick a different winner.
STATUS_RANK = {"completed": 3, "partial": 2, "started": 1, "abandoned": 0}

# Rows are upserted in batches rather than one statement per row. 38,000
# round trips would dominate the runtime for no benefit.
CHUNK_SIZE = 1000


# --------------------------------------------------------------------------
# Field-level parsing
# --------------------------------------------------------------------------


def _field(
    fn: Callable[[Any], Any], raw: Any, reason: str, reasons: list[str]
) -> Any:
    """Apply a parser, turning a ValueError into a reject reason.

    This is rule 1 ("a bad row must not stop the import") in one place. It
    returns None on failure and appends the reason, so the caller keeps going
    and collects every problem with the row instead of only the first.
    """
    try:
        return fn(raw)
    except ValueError:
        reasons.append(reason)
        return None


def _parse_int(raw: Any) -> int | None:
    """Parse an identifier column, honouring the shared empty markers."""
    text = blank_to_none(raw)
    if text is None:
        return None
    try:
        return int(text)
    except ValueError as exc:
        raise ValueError(f"not an integer: {text!r}") from exc


def _parse_rating(raw: Any) -> int | None:
    """Parse a rating and apply the client's 1-5 rule.

    The pure parse is delegated to normalize.parse_duration_seconds rather
    than re-implemented: rating shares the export's empty-marker vocabulary
    and its integer shape, and a second inline copy of "what counts as empty"
    is exactly the bug normalize.py exists to prevent.

    The 1-5 range check lives *here*, in the ingest, for the same reason the
    negative-duration check does -- normalize.py stays free of business rules.
    """
    value = parse_duration_seconds(raw)
    if value is None:
        return None
    if not 1 <= value <= 5:
        # Deliberately not clamped. The client was explicit about that.
        raise ValueError(f"rating outside 1-5: {value}")
    return value


def _parse_status(raw: Any) -> str | None:
    """Fold the export's seven spellings onto the four canonical statuses."""
    text = blank_to_none(raw)
    if text is None:
        return None
    status = text.lower()
    if status not in RESPONSE_STATUSES:
        raise ValueError(f"unknown status: {text!r}")
    return status


# --------------------------------------------------------------------------
# Row validation
# --------------------------------------------------------------------------


def _validate_response(row: dict[str, str], known_surveys: set[int]) -> tuple[dict | None, list[str]]:
    """Turn one raw CSV row into either a loadable record or a list of reasons."""
    reasons: list[str] = []

    response_id = _field(_parse_int, row["response_id"], "unparseable_response_id", reasons)
    if response_id is None and "unparseable_response_id" not in reasons:
        reasons.append("missing_response_id")

    survey_id = _field(_parse_int, row["survey_id"], "unparseable_survey_id", reasons)
    if survey_id is None and "unparseable_survey_id" not in reasons:
        reasons.append("missing_survey_id")
    elif survey_id is not None and survey_id not in known_surveys:
        # Row 900010 points at survey 47, which is not in surveys.csv. Loading
        # it would mean either a dangling reference or inventing a survey.
        reasons.append("unknown_survey")

    email = _field(normalise_email, row["respondent_email"], "invalid_email", reasons)
    if email is None and "invalid_email" not in reasons:
        # Without an email there is no way to apply "once per survey" at all.
        reasons.append("missing_email")

    started_at = _field(parse_client_datetime, row["started_at"], "unparseable_started_at", reasons)
    if started_at is None and "unparseable_started_at" not in reasons:
        reasons.append("missing_started_at")

    completed_at = _field(parse_client_datetime, row["completed_at"], "unparseable_completed_at", reasons)

    status = _field(_parse_status, row["status"], "unknown_status", reasons)
    if status is None and "unknown_status" not in reasons:
        reasons.append("missing_status")

    rating = _field(_parse_rating, row["rating"], "rating_out_of_range", reasons)

    duration = _field(parse_duration_seconds, row["duration_seconds"], "unparseable_duration", reasons)
    if duration is not None and duration < 0:
        # normalize.py returned -2400 unchanged, exactly as its docstring
        # requires. Plausibility is this layer's job, and here it is.
        reasons.append("negative_duration")

    # Cross-field rules. Only checked when both operands parsed, so a row does
    # not collect a confusing consequential reason on top of its real one.
    if started_at is not None and completed_at is not None:
        if completed_at < started_at:
            reasons.append("completed_before_started")
    if status == "completed" and completed_at is None:
        reasons.append("completed_without_completion_time")
    if status in OPEN_STATUSES and completed_at is not None:
        reasons.append("open_status_with_completion_time")

    if reasons:
        return None, reasons

    return {
        "response_id": response_id,
        "survey_id": survey_id,
        "email_canonical": email,
        "display_name": blank_to_none(row["respondent_name"]),
        "status": status,
        "started_at": started_at,
        "completed_at": completed_at,
        "rating": rating,
        "duration_seconds": duration,
        "channel": blank_to_none(row["channel"]),
        "free_text": blank_to_none(row["free_text"]),
    }, []


# --------------------------------------------------------------------------
# Deduplication
# --------------------------------------------------------------------------


def _resolve_duplicates(
    records: list[dict],
) -> tuple[list[dict], list[tuple[dict, str]]]:
    """Apply both uniqueness rules. Returns (winners, [(record, reason), ...]).

    Two distinct problems, deliberately handled separately:

    * A repeated response_id is a *file* defect -- the same row written twice
      (900011). First occurrence wins; there is no judgement to make.
    * One respondent answering the same survey twice is a *business* question,
      and the brief does not answer it. 578 respondents do this. The rule is
      in docs/adr/0003 and is a total order so it is reproducible.
    """
    dropped: list[tuple[dict, str]] = []

    seen_ids: set[int] = set()
    unique_by_id: list[dict] = []
    for record in records:
        if record["response_id"] in seen_ids:
            dropped.append((record, "duplicate_response_id"))
            continue
        seen_ids.add(record["response_id"])
        unique_by_id.append(record)

    groups: dict[tuple[int, str], list[dict]] = defaultdict(list)
    for record in unique_by_id:
        groups[(record["survey_id"], record["email_canonical"])].append(record)

    winners: list[dict] = []
    for group in groups.values():
        if len(group) == 1:
            winners.append(group[0])
            continue
        ranked = sorted(
            group,
            key=lambda r: (
                STATUS_RANK[r["status"]],  # best outcome first
                r["started_at"],           # then the most recent attempt
                r["response_id"],          # then a tiebreak that always exists
            ),
            reverse=True,
        )
        winners.append(ranked[0])
        dropped.extend((r, "duplicate_respondent_in_survey") for r in ranked[1:])

    # Sorted so the loaded order, the respondent id sequence and rejects.csv
    # are all byte-identical between runs. CI diffs rejects.csv against a
    # fresh run, which only works if this is deterministic.
    winners.sort(key=lambda r: r["response_id"])
    dropped.sort(key=lambda pair: pair[0]["response_id"])
    return winners, dropped


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------


def _chunks(items: list[dict], size: int = CHUNK_SIZE) -> Iterable[list[dict]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def _load_surveys(session, rows: list[dict[str, str]]) -> tuple[set[int], list[tuple[dict, str]]]:
    """Upsert clients and surveys. Returns (known survey ids, rejects)."""
    rejects: list[tuple[dict, str]] = []
    clients: dict[str, str] = {}
    surveys: list[dict] = []

    for row in rows:
        reasons: list[str] = []
        survey_id = _field(_parse_int, row["survey_id"], "unparseable_survey_id", reasons)
        name = blank_to_none(row["survey_name"])
        client_name = blank_to_none(row["client_name"])
        invitations = _field(_parse_int, row["invitations_sent"], "unparseable_invitations_sent", reasons)

        # surveys.csv writes DD/MM/YYYY with no time. Reusing the timestamp
        # parser with an explicit midnight keeps one date-parsing
        # implementation instead of a second, subtly different one.
        created = _field(
            lambda raw: parse_client_datetime(f"{blank_to_none(raw)} 00:00:00"),
            row["created_date"],
            "unparseable_created_date",
            reasons,
        )

        if survey_id is None and not reasons:
            reasons.append("missing_survey_id")
        if name is None:
            reasons.append("missing_survey_name")
        if client_name is None:
            reasons.append("missing_client_name")
        if invitations is None and "unparseable_invitations_sent" not in reasons:
            reasons.append("missing_invitations_sent")
        elif invitations is not None and invitations < 0:
            reasons.append("negative_invitations_sent")
        if created is None and "unparseable_created_date" not in reasons:
            reasons.append("missing_created_date")

        if reasons:
            rejects.append(({"survey_id": row.get("survey_id", "")}, "; ".join(reasons)))
            continue

        clients[client_name] = client_name
        surveys.append(
            {
                "survey_id": survey_id,
                "client_name": client_name,
                "survey_name": name,
                "invitations_sent": invitations,
                "created_date": created.date(),
            }
        )

    if clients:
        stmt = pg_insert(Client).values([{"name": n} for n in sorted(clients)])
        # DO UPDATE rather than DO NOTHING purely so RETURNING yields every
        # row, including ones that already existed. DO NOTHING returns nothing
        # for conflicts, which would leave existing clients unmapped.
        stmt = stmt.on_conflict_do_update(
            index_elements=[Client.name], set_={"name": stmt.excluded.name}
        ).returning(Client.id, Client.name)
        client_ids = {name: cid for cid, name in session.execute(stmt).all()}
    else:
        client_ids = {}

    payload = [
        {
            "survey_id": s["survey_id"],
            "client_id": client_ids[s["client_name"]],
            "survey_name": s["survey_name"],
            "invitations_sent": s["invitations_sent"],
            "created_date": s["created_date"],
        }
        for s in surveys
    ]
    if payload:
        stmt = pg_insert(Survey).values(payload)
        stmt = stmt.on_conflict_do_update(
            index_elements=[Survey.survey_id],
            set_={
                c: stmt.excluded[c]
                for c in ("client_id", "survey_name", "invitations_sent", "created_date")
            },
        )
        session.execute(stmt)

    return {s["survey_id"] for s in surveys}, rejects


def _load_respondents(session, records: list[dict]) -> dict[str, int]:
    """Upsert one row per person and return canonical email -> id."""
    names: dict[str, str | None] = {}
    for record in records:  # records are sorted by response_id, so this is stable
        email = record["email_canonical"]
        if names.get(email) is None:
            names[email] = record["display_name"]

    ids: dict[str, int] = {}
    payload = [{"email_canonical": e, "display_name": n} for e, n in sorted(names.items())]
    for chunk in _chunks(payload):
        stmt = pg_insert(Respondent).values(chunk)
        stmt = stmt.on_conflict_do_update(
            index_elements=[Respondent.email_canonical],
            # COALESCE so a later run that happens to see a blank name does not
            # erase a good one already stored.
            set_={
                "display_name": func.coalesce(
                    stmt.excluded.display_name, Respondent.display_name
                )
            },
        ).returning(Respondent.id, Respondent.email_canonical)
        ids.update({email: rid for rid, email in session.execute(stmt).all()})
    return ids


def _load_responses(session, records: list[dict], respondent_ids: dict[str, int], run_id: int) -> int:
    payload = [
        {
            "response_id": r["response_id"],
            "survey_id": r["survey_id"],
            "respondent_id": respondent_ids[r["email_canonical"]],
            "status": r["status"],
            "started_at": r["started_at"],
            "completed_at": r["completed_at"],
            "rating": r["rating"],
            "duration_seconds": r["duration_seconds"],
            "channel": r["channel"],
            "free_text": r["free_text"],
            "ingest_run_id": run_id,
        }
        for r in records
    ]
    updatable = [c for c in payload[0] if c != "response_id"] if payload else []
    for chunk in _chunks(payload):
        stmt = pg_insert(Response).values(chunk)
        # This is rule 5. The natural primary key means a second run of the
        # same file updates rows in place instead of appending them.
        stmt = stmt.on_conflict_do_update(
            index_elements=[Response.response_id],
            set_={c: stmt.excluded[c] for c in updatable},
        )
        session.execute(stmt)
    return len(payload)


# --------------------------------------------------------------------------
# Rejects
# --------------------------------------------------------------------------


def _write_rejects(path: str, rejects: list[tuple[dict, str]]) -> None:
    """One row per rejected input row, carrying the original values.

    The original columns are preserved verbatim rather than the parsed ones,
    because the point of this file is that the client can open it, see what
    they actually sent, and fix it at source.
    """
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=["source_file", "source_row", "reject_reason", *RESPONSE_COLUMNS],
            extrasaction="ignore",
            # QUOTE_MINIMAL plus the csv module handles the apostrophes,
            # embedded double quotes and non-ASCII in this export. Hand-rolled
            # string joining would not.
        )
        writer.writeheader()
        for row, reason in rejects:
            writer.writerow({**row, "reject_reason": reason})


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


def _read_csv(path: str) -> list[dict[str, str]]:
    # utf-8-sig, not utf-8: responses.csv carries a BOM, and a plain utf-8 read
    # names the first column "﻿response_id" so every response_id lookup
    # silently returns None.
    with open(path, encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def run() -> int:
    """Load both CSVs. Return a process exit code."""
    started = time.perf_counter()
    print(f"surveys:   {SURVEYS_CSV}")
    print(f"responses: {RESPONSES_CSV}")

    Base.metadata.create_all(engine)

    survey_rows = _read_csv(SURVEYS_CSV)
    response_rows = _read_csv(RESPONSES_CSV)
    rows_read = len(survey_rows) + len(response_rows)

    session = SessionLocal()
    try:
        run_row = IngestRun(rows_read=rows_read)
        session.add(run_row)
        session.flush()

        known_surveys, rejects = _load_surveys(session, survey_rows)
        for row, reason in rejects:
            row["source_file"] = "surveys.csv"

        valid: list[dict] = []
        # enumerate from 2: row 1 is the header, so these line numbers match
        # what the client sees when they open the file.
        for line_no, row in enumerate(response_rows, start=2):
            record, reasons = _validate_response(row, known_surveys)
            if record is None:
                rejects.append(
                    ({**row, "source_file": "responses.csv", "source_row": line_no},
                     "; ".join(reasons))
                )
            else:
                record["_source_row"] = line_no
                record["_raw"] = row
                valid.append(record)

        winners, dropped = _resolve_duplicates(valid)
        for record, reason in dropped:
            rejects.append(
                ({**record["_raw"], "source_file": "responses.csv",
                  "source_row": record["_source_row"]}, reason)
            )

        for record in winners:
            record.pop("_raw", None)
            record.pop("_source_row", None)

        respondent_ids = _load_respondents(session, winners)
        loaded = _load_responses(session, winners, respondent_ids, run_row.id)

        rejects.sort(key=lambda pair: (pair[0].get("source_file", ""), int(pair[0].get("source_row", 0) or 0)))
        _write_rejects(REJECTS_PATH, rejects)

        run_row.rows_loaded = loaded
        run_row.rows_rejected = len(rejects)
        run_row.finished_at = func.now()
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    elapsed = time.perf_counter() - started
    reasons_seen = Counter(
        reason for _, blob in rejects for reason in blob.split("; ")
    )

    print()
    print(f"rows read      {rows_read}")
    print(f"rows loaded    {loaded}")
    print(f"rows rejected  {len(rejects)}")
    print(f"rejects.csv    {REJECTS_PATH}")
    print(f"elapsed        {elapsed:.1f}s")
    print()
    print("distinct reject reasons:")
    for reason, count in sorted(reasons_seen.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"  {count:>5}  {reason}")

    with SessionLocal() as check:
        print()
        print("table counts:")
        for table in (Client, Survey, Respondent, Response):
            count = check.execute(select(func.count()).select_from(table)).scalar()
            print(f"  {table.__tablename__:<14} {count}")

    return 0


if __name__ == "__main__":
    sys.exit(run())
