"""
Read the data before writing anything that touches it.

This is the script I actually ran first. It is committed because every schema
and ingest decision downstream is justified by its output, and because the
normalize.py empty-marker set was derived from it rather than guessed.

    python3 scripts/profile_data.py
"""

from __future__ import annotations

import collections
import csv
import pathlib
import re

DATA = pathlib.Path(__file__).resolve().parent.parent / "data"
CLIENT_DATETIME = re.compile(r"\d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2}")


def load(name: str) -> list[dict[str, str]]:
    # utf-8-sig: responses.csv is written with a BOM, so a plain utf-8 read
    # names the first column "﻿response_id" and every lookup misses.
    with (DATA / name).open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def main() -> None:
    surveys = load("surveys.csv")
    responses = load("responses.csv")
    print(f"surveys.csv   {len(surveys):>6} rows")
    print(f"responses.csv {len(responses):>6} rows")

    print("\n== low-cardinality columns (verbatim) ==")
    for col in ("survey_id", "status", "rating", "channel"):
        counts = collections.Counter(r[col] for r in responses)
        print(f"\n {col} -- {len(counts)} distinct")
        for value, n in counts.most_common():
            print(f"   {value!r:12} {n}")

    print("\n== values that will not parse ==")
    for col in ("started_at", "completed_at"):
        odd = collections.Counter(
            r[col] for r in responses if not CLIENT_DATETIME.fullmatch(r[col])
        )
        print(f" {col}: {dict(odd)}")
    odd = collections.Counter(
        r["duration_seconds"]
        for r in responses
        if not re.fullmatch(r"\d+", r["duration_seconds"])
    )
    print(f" duration_seconds: {dict(odd)}")
    odd = [
        r["respondent_email"]
        for r in responses
        if not re.fullmatch(r"[a-z0-9.]+@example\.com", r["respondent_email"])
    ]
    print(f" respondent_email: {odd}")

    print("\n== referential integrity ==")
    known = {s["survey_id"] for s in surveys}
    orphans = {r["survey_id"] for r in responses} - known
    print(f" survey_ids in responses with no survey row: {orphans or 'none'}")
    empty = [s["survey_id"] for s in surveys if s["invitations_sent"] == "0"]
    print(f" surveys with invitations_sent == 0 (divide-by-zero risk): {empty}")
    silent = sorted(known - {r["survey_id"] for r in responses}, key=int)
    print(f" surveys with zero responses (empty-report risk): {silent}")

    print("\n== duplicate keys ==")
    ids = collections.Counter(r["response_id"] for r in responses)
    print(f" repeated response_id: {[i for i, n in ids.items() if n > 1]}")
    per_survey = collections.Counter(
        (r["survey_id"], r["respondent_email"].strip().lower()) for r in responses
    )
    extra = sum(n - 1 for n in per_survey.values() if n > 1)
    groups = sum(1 for n in per_survey.values() if n > 1)
    print(f" one respondent answering a survey twice: {groups} groups, {extra} extra rows")

    print("\n== status vs completed_at ==")
    print(" (if partial rows carry a completed_at, completion cannot be")
    print("  inferred from that column -- only from status)")
    pair = collections.Counter(
        (
            r["status"].lower(),
            r["completed_at"].strip().casefold() in {"", "n/a", "null", "-", "none"},
        )
        for r in responses
    )
    for (status, is_empty), n in sorted(pair.items()):
        print(f"   status={status:<10} completed_at empty={str(is_empty):<5} {n}")

    print("\n== year spread of started_at ==")
    print(f"   {collections.Counter(r['started_at'][6:10] for r in responses).most_common()}")


if __name__ == "__main__":
    main()
