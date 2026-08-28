"""
Fixtures for the endpoint tests.

These seed their own data rather than relying on the ingest having run, for
two reasons. A test that needs 37,000 rows loaded first is not a unit of
anything, and more importantly the interesting cases -- a response at one
minute to midnight on a Friday, a survey with zero invitations, the same
instant reported in two timezones -- do not exist in the export and have to
be constructed.

Everything is created under survey ids >= 9000 and emails prefixed
`test-fixture-`, which cannot collide with the real data (survey ids run 1-12),
and is torn down afterwards in foreign-key order.
"""

import os

import pytest
from sqlalchemy import delete, text
from sqlalchemy.exc import OperationalError

from app.db import Base, SessionLocal, engine
from app.models import Client, Respondent, Response, Survey
from app.normalize import parse_client_datetime

FIXTURE_SURVEY_MIN = 9000
FIXTURE_EMAIL_PREFIX = "test-fixture-"


def _database_available() -> bool:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except OperationalError:
        return False


# Skips rather than errors when there is no Postgres, so `pytest` still runs
# the normalize suite on a bare checkout. CI always provides a database, so
# these always execute there -- a skip in CI would be a red flag, not a pass.
requires_db = pytest.mark.skipif(
    not _database_available(),
    reason=f"no database at {os.getenv('DATABASE_URL', 'the default URL')}",
)


def _ist(raw: str):
    """Build a timestamp the way the client's export writes them."""
    return parse_client_datetime(raw)


def _cleanup(session):
    session.execute(
        delete(Response).where(Response.survey_id >= FIXTURE_SURVEY_MIN)
    )
    session.execute(delete(Survey).where(Survey.survey_id >= FIXTURE_SURVEY_MIN))
    session.execute(
        delete(Respondent).where(
            Respondent.email_canonical.like(f"{FIXTURE_EMAIL_PREFIX}%")
        )
    )
    session.execute(delete(Client).where(Client.name.like("Test Client %")))
    session.commit()


@pytest.fixture(scope="module")
def seeded():
    """Create a small, fully known dataset and yield nothing but its shape.

    Module-scoped: the rows are read-only for every test that uses them, so
    rebuilding them per test would only be slower.
    """
    Base.metadata.create_all(engine)
    session = SessionLocal()
    _cleanup(session)

    ist_client = Client(name="Test Client IST", reporting_timezone="Asia/Kolkata")
    dubai_client = Client(name="Test Client Dubai", reporting_timezone="Asia/Dubai")
    session.add_all([ist_client, dubai_client])
    session.flush()

    surveys = [
        # 9001: week boundaries. 100 invitations makes the rate arithmetic
        # readable by eye -- 2 completed is exactly 0.02.
        Survey(survey_id=9001, client_id=ist_client.id, survey_name="Week boundaries",
               invitations_sent=100, created_date=_ist("01/01/2026 00:00:00").date()),
        # 9002: which statuses count.
        Survey(survey_id=9002, client_id=ist_client.id, survey_name="Status rules",
               invitations_sent=100, created_date=_ist("01/01/2026 00:00:00").date()),
        # 9003: zero invitations, the survey-9 shape.
        Survey(survey_id=9003, client_id=ist_client.id, survey_name="No invitations",
               invitations_sent=0, created_date=_ist("01/01/2026 00:00:00").date()),
        # 9004: durations that are absent rather than zero.
        Survey(survey_id=9004, client_id=ist_client.id, survey_name="Missing durations",
               invitations_sent=100, created_date=_ist("01/01/2026 00:00:00").date()),
        # 9005: the same instants as 9001, reported by a Dubai client.
        Survey(survey_id=9005, client_id=dubai_client.id, survey_name="Dubai reporting",
               invitations_sent=100, created_date=_ist("01/01/2026 00:00:00").date()),
    ]
    session.add_all(surveys)

    people = [
        Respondent(email_canonical=f"{FIXTURE_EMAIL_PREFIX}{n}@example.com")
        for n in range(1, 13)
    ]
    session.add_all(people)
    session.flush()
    p = [person.id for person in people]

    def response(rid, sid, person_ix, started, status, duration, completed=None):
        return Response(
            response_id=rid, survey_id=sid, respondent_id=p[person_ix],
            status=status, started_at=_ist(started),
            completed_at=_ist(completed) if completed else None,
            rating=None, duration_seconds=duration, channel="email", free_text=None,
        )

    session.add_all([
        # --- 9001: the Saturday-to-Friday boundary, pinned at both ends ---
        # Sat 3 Jan 00:00:00 - the first instant of a reporting week.
        response(900101, 9001, 0, "03/01/2026 00:00:00", "completed", 100,
                 "03/01/2026 00:10:00"),
        # Fri 9 Jan 23:59:59 - the last instant of the SAME week.
        response(900102, 9001, 1, "09/01/2026 23:59:59", "completed", 300,
                 "10/01/2026 00:10:00"),
        # Sat 10 Jan 00:00:00 - one second later, the NEXT week.
        response(900103, 9001, 2, "10/01/2026 00:00:00", "completed", 200,
                 "10/01/2026 00:10:00"),
        # Sat 10 Jan 01:00 IST. The same instant is Fri 9 Jan 19:30 UTC and
        # Fri 9 Jan 23:30 in Dubai (UTC+04:00, only 90 minutes behind IST).
        # One instant, three different reporting weeks depending on the zone
        # you bucket in - see survey 9005 for the Dubai half.
        response(900104, 9001, 3, "10/01/2026 01:00:00", "completed", 400,
                 "10/01/2026 01:10:00"),

        # --- 9002: which statuses count, all inside one week ---
        response(900201, 9002, 4, "17/01/2026 10:00:00", "completed", 100,
                 "17/01/2026 10:10:00"),
        # A partial carries a completed_at in this export - that is why
        # completion is read from status, never from the column's presence.
        response(900202, 9002, 5, "17/01/2026 11:00:00", "partial", 500,
                 "17/01/2026 11:20:00"),
        response(900203, 9002, 6, "17/01/2026 12:00:00", "abandoned", 900),
        response(900204, 9002, 7, "17/01/2026 13:00:00", "started", 900),

        # --- 9003: a completed response against zero invitations ---
        response(900301, 9003, 8, "17/01/2026 10:00:00", "completed", 100,
                 "17/01/2026 10:10:00"),

        # --- 9004: one week with no durations at all, one with some ---
        response(900401, 9004, 9, "17/01/2026 10:00:00", "completed", None,
                 "17/01/2026 10:10:00"),
        response(900402, 9004, 10, "24/01/2026 10:00:00", "completed", 250,
                 "24/01/2026 10:10:00"),

        # --- 9005: the same instant as 900104, under a Dubai client ---
        response(900501, 9005, 11, "10/01/2026 01:00:00", "completed", 400,
                 "10/01/2026 01:10:00"),
    ])
    session.commit()

    yield

    _cleanup(session)
    session.close()
