"""
The schema.

Shape:

    clients ──< surveys ──< responses >── respondents
                               │
                               └── ingest_runs (provenance)

Four design decisions carry this file. Each is defended in README section 2.

1.  Every timestamp is TIMESTAMP WITH TIME ZONE, and the reporting timezone
    lives on `clients`, not in the code.

    The brief says a Dubai customer is onboarding next quarter and timestamps
    must not need re-migrating. Postgres stores timestamptz as UTC internally,
    so the stored instants are already zone-neutral and correct forever. What
    would otherwise need migrating is the *reporting* zone -- the wall clock
    that decides which Saturday-to-Friday week a response falls in. Putting
    that on the client row as an IANA name makes onboarding Dubai one INSERT
    with reporting_timezone='Asia/Dubai', with no schema change, no backfill,
    and no re-parse of history.

    Deliberately NOT `timestamp without time zone`. That column type would
    silently reinterpret every stored instant the moment a second zone
    appeared, which is exactly the re-migration the brief is warning about.

2.  `responses` carries UNIQUE (survey_id, respondent_id).

    "A respondent counts only once per survey" is a business rule, and the
    database is the only place that can actually guarantee it. Enforcing it
    solely in the loader means the next writer -- a backfill script, an admin
    endpoint, a hand-run INSERT -- silently breaks the report. 578 respondents
    in this export answered the same survey twice, so this is a live rule, not
    a theoretical one.

3.  `respondents` is a table, not a column.

    2,189 canonical emails appear in more than one survey. One row per person,
    keyed on the canonical email that normalise_email() produces, means
    identity has one home. It also makes the UNIQUE above an integer pair
    rather than a 40-byte string, which is what the report actually joins on.

4.  Constraints cover what the report depends on, and nothing else.

    status, rating, and the two timestamps are constrained, because a bad
    value in any of them produces a wrong number on the client's screen.
    `channel` is deliberately left unconstrained: a new channel is a business
    event, not a data error, and rejecting a whole response because someone
    added "webchat" would be disproportionate.

Tables are created with Base.metadata.create_all(), called by app.ingest.
Alembic is in requirements.txt and would be the right answer the moment this
schema has to change under a live database; for a first cut with no history to
preserve, create_all() is the honest amount of machinery.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base

# The four states the export actually uses, lower-cased. The raw file writes
# seven spellings of these ("COMPLETED", "Completed", "completed", ...); case
# is a client-system artefact, not information, so it is folded at ingest and
# the canonical set is constrained here.
#
# Held as TEXT + CHECK rather than a native Postgres ENUM on purpose: adding a
# value to an ENUM needs ALTER TYPE, which historically could not run inside a
# transaction and still cannot be rolled back cleanly. Widening a CHECK is one
# ordinary DDL statement.
RESPONSE_STATUSES = ("completed", "partial", "abandoned", "started")

# Statuses that mean the respondent stopped without finishing, and therefore
# must not carry a completion timestamp.
OPEN_STATUSES = ("started", "abandoned")


class Client(Base):
    """One of the enterprise customers the surveys are run for."""

    __tablename__ = "clients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # Natural key. The export identifies clients only by name, so the name has
    # to be unique or re-running the ingest would fork one client into two.
    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)

    # IANA zone name, e.g. 'Asia/Kolkata', 'Asia/Dubai'. See note 1 above.
    # NOT NULL with a default rather than nullable: "we do not know this
    # client's reporting zone" is not a state the report can render, so the
    # schema refuses to represent it.
    reporting_timezone: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default="Asia/Kolkata"
    )

    surveys: Mapped[list["Survey"]] = relationship(back_populates="client")


class Survey(Base):
    """One survey campaign, with the invitation count the report divides by."""

    __tablename__ = "surveys"

    # The CSV's own survey_id is the primary key, not a surrogate. It is a
    # stable identifier that already exists in the client's world, the front
    # end routes on it, and re-running the ingest depends on it to recognise
    # rows it has already seen. autoincrement=False so Postgres does not
    # attach a sequence that would then be out of step with the file.
    survey_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=False
    )

    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id", ondelete="RESTRICT"), nullable=False, index=True
    )

    survey_name: Mapped[str] = mapped_column(String(300), nullable=False)

    # 0 is a real, loadable value: survey 9 ("Pilot - Do Not Report") has zero
    # invitations. It is NOT NULL because completion_rate is undefined without
    # it, and CHECK >= 0 because a negative invitation count is nonsense.
    # The divide-by-zero this permits is handled in the endpoint, which returns
    # a null completion_rate rather than inventing a number.
    invitations_sent: Mapped[int] = mapped_column(Integer, nullable=False)

    # DATE, not TIMESTAMPTZ: surveys.csv writes DD/MM/YYYY with no time, so
    # storing a timestamp would mean inventing a midnight that is not in the
    # source and would then be wrong for Dubai.
    created_date: Mapped[dt.date] = mapped_column(Date, nullable=False)

    client: Mapped["Client"] = relationship(back_populates="surveys")
    responses: Mapped[list["Response"]] = relationship(back_populates="survey")

    __table_args__ = (
        CheckConstraint("invitations_sent >= 0", name="ck_surveys_invitations_sent"),
    )


class Respondent(Base):
    """One person, identified by the canonical form of their email address."""

    __tablename__ = "respondents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # Exactly what normalise_email() returns. UNIQUE is what makes this table
    # an identity: two rows arriving as "Priya.Sharma22@example.com" and
    # "priya.sharma22@example.com " collapse onto one person here.
    email_canonical: Mapped[str] = mapped_column(
        String(320), nullable=False, unique=True
    )

    # Nullable on purpose. Row 900019's respondent_name is three spaces, and
    # the export shows the same person under different capitalisations. The
    # name is a display convenience the report never joins on, so an absent
    # one is not worth rejecting a response over.
    display_name: Mapped[str | None] = mapped_column(String(200), nullable=True)

    responses: Mapped[list["Response"]] = relationship(back_populates="respondent")


class IngestRun(Base):
    """One execution of app.ingest. Provenance for every loaded row."""

    __tablename__ = "ingest_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    rows_read: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rows_loaded: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rows_rejected: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class Response(Base):
    """One survey response."""

    __tablename__ = "responses"

    # Natural key again, and the thing that makes re-running the ingest safe:
    # the loader upserts on it, so the same file loaded twice updates 38,000
    # rows rather than inserting 38,000 more.
    response_id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=False
    )

    # RESTRICT, not CASCADE. Deleting a survey should be a deliberate,
    # audited operation rather than something a stray DELETE can do silently
    # -- see README section 6 for what that operation would actually look
    # like. RESTRICT makes the database refuse until that work has been done.
    survey_id: Mapped[int] = mapped_column(
        ForeignKey("surveys.survey_id", ondelete="RESTRICT"), nullable=False
    )
    respondent_id: Mapped[int] = mapped_column(
        ForeignKey("respondents.id", ondelete="RESTRICT"), nullable=False, index=True
    )

    status: Mapped[str] = mapped_column(String(16), nullable=False)

    # NOT NULL: a response with no start has no reporting week and cannot
    # appear in the report at all, so it is a reject, not a nullable row.
    started_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    # Nullable on purpose: 'started' and 'abandoned' responses never complete.
    # 10,755 rows in the export have no completion timestamp and they are all
    # legitimate.
    completed_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Nullable on purpose: 10,878 rows have no rating (blank or "N/A"). An
    # unanswered rating question is a real outcome, not a defect -- the CHECK
    # is what keeps the 1-5 rule, and a NULL never violates a CHECK.
    rating: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)

    # Nullable on purpose: the export omits durations. CHECK >= 0 catches the
    # -2400 in row 900008 as a second line of defence behind the ingest.
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Nullable and unconstrained: see note 4 in the module docstring.
    channel: Mapped[str | None] = mapped_column(String(32), nullable=True)
    free_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    ingest_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("ingest_runs.id", ondelete="SET NULL"), nullable=True
    )

    survey: Mapped["Survey"] = relationship(back_populates="responses")
    respondent: Mapped["Respondent"] = relationship(back_populates="responses")

    __table_args__ = (
        # The business rule from the brief, made unbreakable.
        UniqueConstraint(
            "survey_id", "respondent_id", name="uq_responses_one_per_respondent"
        ),
        CheckConstraint(
            "status IN " + str(RESPONSE_STATUSES), name="ck_responses_status"
        ),
        CheckConstraint(
            "rating IS NULL OR (rating BETWEEN 1 AND 5)", name="ck_responses_rating"
        ),
        CheckConstraint(
            "duration_seconds IS NULL OR duration_seconds >= 0",
            name="ck_responses_duration_non_negative",
        ),
        # Rows 900007 and 900008 finish before they start.
        CheckConstraint(
            "completed_at IS NULL OR completed_at >= started_at",
            name="ck_responses_completed_after_started",
        ),
        # A completed response must say when it completed, or responses_completed
        # and the median stop agreeing about which rows they are counting.
        CheckConstraint(
            "status <> 'completed' OR completed_at IS NOT NULL",
            name="ck_responses_completed_has_timestamp",
        ),
        # ...and the converse: a response the respondent walked away from must
        # not carry one. Note this deliberately permits 'partial' to have a
        # completed_at, because every partial row in the export does -- that
        # column is really "last activity", which is exactly why completion is
        # read from status and never from this column.
        CheckConstraint(
            "status NOT IN " + str(OPEN_STATUSES) + " OR completed_at IS NULL",
            name="ck_responses_open_has_no_completion",
        ),
        # The report query's exact access path: filter one survey, bucket by
        # started_at. Composite and in this order because the survey_id
        # equality prefix is what makes the started_at range scan cheap.
        # duration_seconds and status are INCLUDEd so the weekly aggregate is
        # answered from the index alone without touching the heap.
        Index(
            "ix_responses_survey_started",
            "survey_id",
            "started_at",
            postgresql_include=["status", "duration_seconds"],
        ),
    )
