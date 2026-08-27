"""
FastAPI app. The wiring, CORS and the health check are done for you.

Add your endpoints here or in a router you import - your call.

--------------------------------------------------------------------------
The client's four report rules, and how each is honoured
--------------------------------------------------------------------------

1. "Our reporting week runs Saturday to Friday. It always has."
   date_trunc('week', ...) returns a Monday and takes no offset argument.
   Shifting the input forward two days moves Saturday onto Monday, and
   shifting the result back recovers it:

       date_trunc('week', local_ts + interval '2 days') - interval '2 days'

   Checked at both ends: Sat 3 Jan 2026 -> +2d = Mon 5 Jan -> truncates to
   Mon 5 Jan -> -2d = Sat 3 Jan. Fri 9 Jan -> +2d = Sun 11 Jan -> truncates
   to Mon 5 Jan -> -2d = Sat 3 Jan. Both ends of the Saturday-to-Friday week
   land on the same Saturday; Sat 10 Jan opens the next one. There is a test
   for exactly these boundaries.

   The shift happens in the CLIENT's reporting timezone, read from
   clients.reporting_timezone, not in UTC. Bucketing UTC instants would put
   every response between 00:00 and 05:30 IST into the previous week.

2. "Completion rate is completed responses over invitations sent for that
   survey. Not over the responses we received."
   The denominator is surveys.invitations_sent - a campaign-level number
   reused for every week, which is unusual but is exactly what was asked for
   and is what makes the number show "who never turned up". Weekly rates
   still sum to the campaign rate.

   Survey 9 has invitations_sent = 0, so the rate is undefined, not zero.
   It comes back as null. Returning 0.0 would be a wrong number on a
   client's screen, which is worse than an honest blank.

3. "A partial response counts in the response count. It does not count as
   completed. abandoned and started count in neither."
   The counted population is status IN ('completed','partial'). Note this
   makes the field named `responses_started` EXCLUDE rows whose status is
   literally 'started' - implemented per the client's prose rather than the
   field name, and flagged in README section 4.

   Completion is read from `status` and never from whether completed_at is
   present: all 10,953 'partial' rows in the export carry a completed_at, so
   that column means "last activity". Trusting it would overcount
   completions by roughly two thirds.

4. "Under 300 milliseconds."
   One round trip. All bucketing, counting and the median are done in
   Postgres; nothing is aggregated in Python. The access path is the
   covering index ix_responses_survey_started (survey_id, started_at)
   INCLUDE (status, duration_seconds). Measured number in README section 5.
"""

import math

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from .db import get_session

app = FastAPI(title="Survey Reporting Slice")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class SurveyOut(BaseModel):
    """Exactly the `Survey` type already declared in frontend/src/types.ts.

    The brief says "return whatever the list page needs"; the list page was
    written against that type, so it is the specification.
    """

    survey_id: int
    survey_name: str
    client_name: str
    invitations_sent: int


class WeekRow(BaseModel):
    """One reporting week. Mirrors `WeekRow` in frontend/src/types.ts."""

    week_start: str

    # Responses that count, per rule 3: completed + partial.
    responses_started: int
    responses_completed: int

    # A ratio in 0..1, not a percentage, and deliberately NOT rounded here:
    # rounding is presentation, and a client reconciling completed/invitations
    # by hand should get exactly this number back. The UI formats it.
    # Null when the survey has zero invitations - the rate is then genuinely
    # undefined, and 0.0 would be a wrong number rather than a missing one.
    completion_rate: float | None

    # Null when no counted response that week recorded a duration. Not 0:
    # "nobody reported a duration" and "everyone finished instantly" are
    # different facts and must not render the same.
    median_duration_seconds: int | None


class SurveySummaryOut(BaseModel):
    survey_id: int
    survey_name: str
    client_name: str
    invitations_sent: int
    weeks: list[WeekRow]


# Kept as one statement so Postgres plans it as a whole. Parameterised - the
# survey_id is bound, never interpolated.
SUMMARY_SQL = text(
    """
    WITH counted AS (
        SELECT
            (
                date_trunc(
                    'week',
                    (r.started_at AT TIME ZONE c.reporting_timezone)
                        + interval '2 days'
                ) - interval '2 days'
            )::date                       AS week_start,
            r.status,
            r.duration_seconds
        FROM responses r
        JOIN surveys s ON s.survey_id = r.survey_id
        JOIN clients c ON c.id        = s.client_id
        WHERE r.survey_id = :survey_id
          -- Rule 3: abandoned and started count in neither column.
          AND r.status IN ('completed', 'partial')
    )
    SELECT
        week_start,
        count(*)                                          AS responses_started,
        count(*) FILTER (WHERE status = 'completed')      AS responses_completed,
        -- percentile_cont, not percentile_disc: the textbook median averages
        -- the two middle values on an even count. NULL durations are ignored
        -- by the aggregate, and a week where none was recorded yields NULL.
        percentile_cont(0.5) WITHIN GROUP (ORDER BY duration_seconds)
                                                          AS median_duration
    FROM counted
    GROUP BY week_start
    ORDER BY week_start
    """
)


@app.get("/api/health")
def health(db: Session = Depends(get_session)):
    """Proves the app is up and can reach Postgres."""
    db.execute(text("SELECT 1"))
    return {"ok": True}


@app.get("/api/surveys", response_model=list[SurveyOut])
def list_surveys(db: Session = Depends(get_session)):
    """Every survey, including ones with no responses at all.

    Survey 9 ("Pilot - Do Not Report") has zero responses and zero
    invitations. It is deliberately still listed: the brief requires the page
    to survive every survey, and silently hiding empty ones would mean the
    client cannot tell "no data" from "not a survey".
    """
    rows = db.execute(
        text(
            """
            SELECT s.survey_id, s.survey_name, c.name AS client_name,
                   s.invitations_sent
            FROM surveys s
            JOIN clients c ON c.id = s.client_id
            ORDER BY s.survey_id
            """
        )
    ).mappings()
    return [SurveyOut(**row) for row in rows]


@app.get("/api/surveys/{survey_id}/summary", response_model=SurveySummaryOut)
def survey_summary(survey_id: int, db: Session = Depends(get_session)):
    """The weekly summary. See the module docstring for the four rules."""
    survey = db.execute(
        text(
            """
            SELECT s.survey_id, s.survey_name, s.invitations_sent,
                   c.name AS client_name
            FROM surveys s
            JOIN clients c ON c.id = s.client_id
            WHERE s.survey_id = :survey_id
            """
        ),
        {"survey_id": survey_id},
    ).mappings().first()

    # 404 rather than an empty summary: "this survey has no responses" and
    # "this survey does not exist" are different answers and the front end
    # should be able to tell them apart.
    if survey is None:
        raise HTTPException(status_code=404, detail="Survey not found")

    invitations = survey["invitations_sent"]
    rows = db.execute(SUMMARY_SQL, {"survey_id": survey_id}).mappings().all()

    weeks = [
        WeekRow(
            week_start=row["week_start"].isoformat(),
            responses_started=row["responses_started"],
            responses_completed=row["responses_completed"],
            # Rule 2. Guarded rather than assumed: survey 9 has 0 invitations.
            completion_rate=(
                row["responses_completed"] / invitations if invitations else None
            ),
            # math.floor(x + 0.5), not round(): Python's round() is
            # round-half-to-even, so round(1230.5) is 1230 and round(1231.5)
            # is 1232. Two adjacent medians rounding in opposite directions is
            # not something anyone should have to explain to a client.
            # percentile_cont can only ever produce .0 or .5 here, since every
            # stored duration is an integer.
            median_duration_seconds=(
                math.floor(row["median_duration"] + 0.5)
                if row["median_duration"] is not None
                else None
            ),
        )
        for row in rows
    ]

    # Weeks with no counted response are absent rather than present-and-zero.
    # Gap-filling with generate_series was considered and rejected: survey 12
    # has one genuine response dated 31/12/2027, which would manufacture ~70
    # empty weeks between it and the rest of the data. If the client wants
    # zero-rows for genuinely quiet weeks, that is a bounded series join here.
    return SurveySummaryOut(
        survey_id=survey["survey_id"],
        survey_name=survey["survey_name"],
        client_name=survey["client_name"],
        invitations_sent=invitations,
        weeks=weeks,
    )
