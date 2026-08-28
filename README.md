# Survey reporting slice — Awesome Analytics practical

FastAPI + Postgres + React. One vertical slice: the client's export in a
relational shape, and one weekly report on screen.

Supporting documents: [`REVIEW.md`](REVIEW.md) (Step 6b),
[`RISK_REGISTER.md`](RISK_REGISTER.md) (everything I found wrong, with the
decision against each), [`docs/adr/`](docs/adr/) (the four decisions that
would be expensive to reverse), [`rejects.csv`](rejects.csv) (straight out of
the ingest run below).

## 1. Running it

```bash
docker compose up --build
docker compose exec backend python -m app.ingest    # ~7s
docker compose exec backend pytest        # 74 tests
```

App on http://localhost:5173, API health on http://localhost:8000/api/health.

Two changes beyond a plain `docker compose up`:

- **`docker-compose.yml`**: added a `./:/repo` mount and `REJECTS_PATH`.
  `/data` is mounted read-only, so the ingest cannot write `rejects.csv`
  beside its source, and the brief wants that file committed.
- **`backend/requirements.txt`**: added `tzdata`. `python:3.12-slim` ships no
  zoneinfo database, so `ZoneInfo("Asia/Kolkata")` raises inside the container
  while passing on macOS. No other library was swapped or added.

## 2. Data model

```
clients ──< surveys ──< responses >── respondents
                            │
                            └── ingest_runs   (provenance)
```

**Keys.** `surveys.survey_id` and `responses.response_id` are the CSV's own
ids, used as natural primary keys with `autoincrement=False`. They are stable
in the client's world, the front end routes on them, and the idempotent
re-ingest upserts on them. `clients` and `respondents` get surrogate keys
because their natural keys are strings I would rather not have as foreign keys
in 37,000 rows.

**Timezones — the Dubai requirement.** Every instant is `TIMESTAMPTZ`, which
Postgres stores as UTC, so the stored values are already zone-neutral and
never need re-migrating. What *would* otherwise need migrating is the
reporting wall clock that decides which Saturday-to-Friday week a response
lands in, so that lives on **`clients.reporting_timezone`** as an IANA name
(`NOT NULL DEFAULT 'Asia/Kolkata'`), and the summary query converts with
`AT TIME ZONE c.reporting_timezone` before bucketing. Onboarding Dubai is
`INSERT INTO clients (name, reporting_timezone) VALUES (…, 'Asia/Dubai')` —
no schema change, no backfill, no re-parse, and both clients can be reported
in one query, each in its own week. `timestamp without time zone` was rejected
precisely because it would silently reinterpret history the moment a second
zone appeared. Full reasoning in [ADR 0001](docs/adr/0001-store-timestamps-as-timestamptz.md).

**Constraints.** The report is only as good as what the database refuses:

| Constraint | What it stops |
|---|---|
| `UNIQUE (survey_id, respondent_id)` | "A respondent counts only once per survey", guaranteed by the DB rather than hoped for in the loader. 578 respondents in this export break it. |
| `rating BETWEEN 1 AND 5` | row 900009's rating of 9 |
| `duration_seconds >= 0` | row 900008's `-2400` |
| `completed_at >= started_at` | rows 900007 and 900008, which finish before they start |
| `status <> 'completed' OR completed_at IS NOT NULL` | a completed response with no completion time |
| `status NOT IN ('started','abandoned') OR completed_at IS NULL` | a walked-away response carrying one |

Note what that last pair deliberately **permits**: `partial` rows *may* carry
a `completed_at`, because all 10,953 of them do. The constraint set documents
that the column means "last activity", which is exactly why completion is read
from `status` and never from that column's presence.

**Deliberately nullable.** `rating` (10,878 rows genuinely have no rating — an
unanswered question is an outcome, not a defect), `duration_seconds`,
`completed_at` (10,755 responses never completed), `channel`, `free_text`, and
`respondents.display_name` (row 900019's name is three spaces).

**Deliberately unconstrained.** `channel`. A new channel is a business event,
not a data error; rejecting a whole response because someone added `webchat`
would be disproportionate. I constrained what the report depends on and left
the rest open.

**Indexes.** `ix_responses_survey_started (survey_id, started_at) INCLUDE
(status, duration_seconds)` — the summary query's exact access path. `EXPLAIN`
confirms an **Index Only Scan with `Heap Fetches: 0`**, so the whole weekly
aggregate is answered from the index without touching the table. Plus the
FK index on `respondent_id`.

**Foreign keys are `ON DELETE RESTRICT`, not `CASCADE`** — deleting a survey
should be the deliberate, audited operation in section 6, not something a
stray `DELETE` does silently.

Tables are created with `Base.metadata.create_all()`. Alembic is the right
answer the moment this schema changes under a live database; with no history
to preserve yet, that is the honest amount of machinery.

## 3. Ingest results

| | |
|---|---|
| Rows read | **38,017** (12 surveys + 38,005 responses) |
| Rows loaded | **37,415** responses, across 4 clients, 12 surveys, 35,163 respondents |
| Rows rejected | **590** |

38,005 − 590 = 37,415. It reconciles exactly; nothing is silently dropped.

Distinct reasons, straight from the run:

| n | reason |
|---:|---|
| 583 | `duplicate_respondent_in_survey` |
| 2 | `completed_before_started` |
| 1 | `completed_without_completion_time` |
| 1 | `duplicate_response_id` |
| 1 | `invalid_email` |
| 1 | `negative_duration` |
| 1 | `rating_out_of_range` |
| 1 | `unknown_survey` |
| 1 | `unparseable_completed_at` |
| 1 | `unparseable_started_at` |

Two categories, worth separating: **7 rows are malformed**, and **583 are
valid rows dropped by the "once per respondent per survey" rule**. A row can
carry more than one reason — 900006 has three — because telling a client about
one problem at a time sends them round the loop three times.
`rejects.csv` carries the **original** column values, not the parsed ones, so
they can open it, see what they actually sent, and fix it at source.

**Idempotency** is verified rather than asserted: three consecutive runs
produce identical row counts, an identical md5 over every response's content,
and a byte-identical `rejects.csv`. Row counts alone would not prove it — an
upsert that overwrote with the wrong duplicate winner would keep counts stable
while changing the report.

**Canonical email** = trim + lower-case the whole address, nothing else.
Dots and `+tags` are deliberately **not** stripped: those are one provider's
delivery quirks, not email semantics, and folding them would merge genuinely
different people. Row 900003's free text reads *"It is O'Brien, not Obrien"*,
which I took as the dataset saying so. Lower-casing the local part is
technically against RFC 5321, which makes it case-sensitive — but no real mail
system treats `Asha.Rao` and `asha.rao` as two people, and the brief's own
example test requires them to compare equal.

## 4. What I found wrong in the brief

Full list with severity and status in [`RISK_REGISTER.md`](RISK_REGISTER.md).
The six that changed what I built:

**a. `responses_started` excludes responses whose status is `started`.** The
client's rule — "a partial counts in the response count; `abandoned` and
`started` count in neither" — makes the field named `responses_started` mean
`completed` + `partial`. I implemented the prose, not the field name, because
the prose is unambiguous and the name is not. **It should be renamed**
(`responses_counted`), because someone will eventually trust the label.

**b. Which timestamp decides the reporting week is never stated.** A response
can start on Friday and complete on Saturday. I bucket on `started_at`: it is
`NOT NULL` on every row, so nothing is invisible, and both counts come from
one clock so the columns tie out — which is what the client explicitly asked
for. `responses_completed` therefore means "started this week and was
completed". [ADR 0004](docs/adr/0004-bucket-the-reporting-week-on-started-at.md).

**c. The median's population is never stated.** I take it over the same rows
as `responses_started`, with non-null durations, so the median describes the
population printed next to it.

**d. `completion_rate` is undefined for survey 9**, which has
`invitations_sent = 0`. I return `null`, never `0`, and widened `types.ts` to
`number | null` so `tsc` refuses to compile a table that ignores it. `0%`
would be a wrong number on a client's screen, which is worse than a blank.
Related: the brief never says whether the rate is a ratio or a percentage — I
return a ratio in 0..1 unrounded, and the UI formats it.

**e. Which duplicate wins is never stated, and it affects 584 rows** — not one
planted pair. I rank `completed` > `partial` > `started` > `abandoned`, then
latest `started_at`, then highest `response_id`; the third key exists so the
order is total and re-running cannot quietly pick a different winner.
[ADR 0003](docs/adr/0003-duplicate-response-resolution.md).

**f. Step 6a contains a flat contradiction between two client emails.**
Compliance wants every response "gone permanently"; reporting wants the audit
table to keep "every response ever submitted". Resolved in section 6.

Two things I found in the **data** that the brief does not mention and that I
would raise with the client before the next run:

- **3,236 responses (8.6%) start before their own survey's `created_date`** —
  survey 12 was created 01/04/2026 and has 1,335 responses before it existed.
  Every survey's first reporting week is 2025-12-27. Either `created_date` is
  not a launch date, or timestamps were back-dated. I loaded them (discarding
  8.6% of the dataset on an inferred rule would be far worse) and made sure
  `created_date` is not used as a report boundary anywhere.
- **One response is dated 31/12/2027**, a year past everything else. It parses
  and is internally consistent, so it is loaded and shows as a lone 2027 week
  on survey 12. Deleting real data on a rule the client never gave is not my
  call to make silently.

One thing that is **not** wrong, though it looks it: the weekly completion
rate divides by a campaign-level `invitations_sent`, so every week gets the
same denominator and each week's rate looks tiny. That is exactly what was
asked for, it is coherent (weekly rates sum to the campaign rate), and the
client said the point is "to see who never turned up".

## 5. Performance

**3.7 ms median, 7.7 ms worst case. Budget is 300 ms.**

Measured with [`scripts/bench_summary.py`](scripts/bench_summary.py): 20
requests against each of the 12 surveys, 240 samples, end-to-end over HTTP
against the fully loaded 37,415-row dataset — so it includes FastAPI, Pydantic
validation, JSON serialisation and the network hop, not just the SQL. One
warm-up pass per survey is excluded, since the client only pays connection
setup and plan caching once.

| p50 | p95 | p99 | max |
|---|---|---|---|
| 3.7 ms | 7.5 ms | 7.7 ms | 7.7 ms |

The number matters less than the access path. `EXPLAIN (ANALYZE, BUFFERS)`
shows an **Index Only Scan on `ix_responses_survey_started` with
`Heap Fetches: 0`** — the `INCLUDE (status, duration_seconds)` columns answer
the status filter and the median straight from the index. All bucketing,
counting and the median happen in Postgres in one round trip; nothing is
aggregated in Python. That is what should hold at ten times the data.

**Correctness is pinned by tests, and the tests were checked for teeth.**
15 endpoint tests seed their own fixtures — a response at Sat 00:00:00 and
another at Fri 23:59:59, a `partial` that carries a `completed_at`, a survey
with zero invitations, a week with no durations at all. Because `REVIEW.md`
blocks a PR partly for tests that pass with the endpoint bodies deleted, I
mutation-checked my own: removing the two-day Saturday shift fails 12 tests,
counting all four statuses fails 1, and dividing by responses received instead
of invitations fails 2. A test that cannot fail is not protecting anything.

One of those tests caught a mistake of mine while I was writing it. I asserted
that Sat 10 Jan 03:00 IST would report in a different week for a Dubai client;
it does not, because Dubai is only 90 minutes behind Kolkata, not three hours.
The window where the two zones disagree is the 90 minutes after local midnight.
The fixture now uses 01:00 and the test passes for the right reason.

**Correctness was also verified independently of the tests.** The brief says to read the
output back against all four rules line by line, so
[`scripts/verify_summary.py`](scripts/verify_summary.py) recomputes the report
from the CSV sharing no code with the endpoint — the SQL buckets weeks with
`date_trunc('week', ts + '2 days') - '2 days'`, the verifier walks back to the
most recent Saturday with Python's `weekday()`. **All 12 surveys, 349 weeks,
identical.** Two independent implementations agreeing is evidence; one
implementation agreeing with itself is not.

## 6. The delete (Step 6a)

The two emails only contradict each other if "response" means one thing, and
it does not. Compliance owns the **personal data** — email, name, free text —
and that is what must be *"gone permanently"*. Reporting owns the **countable
fact** — which survey, which week, completed or not, how long it took — and
that is what has to survive for year-end reconciliation. A count is not
personal data.

So: soft-delete the survey first (`deleted_at`) so it leaves the list
immediately and the report stops serving it. Then, in one transaction, write
one anonymised row per response into the audit table — `survey_id`, week,
status, duration, and a salted hash of the respondent id, never the address —
and hard-delete the `responses` rows and any `respondents` left with no
remaining responses. The audit table takes no foreign key back to
`respondents`, so nothing can rejoin the identity later; that is what makes
the deletion permanent rather than merely hidden.

Keep the per-respondent salt in a KMS and destroy it per customer on offboarding,
which crypto-shreds even the hashes. I would confirm one thing before building
it: whether free text counts as a countable fact or as personal data. I would
treat it as personal and drop it, because respondents put names in free text.

## 7. AI log

**Tools.** Claude Code (Opus), driving the whole session. Roughly **90% of the
final code was AI-generated**, which the brief says is fine, and every line of
it was read, argued with, and in several places rewritten. The parts that are
mine in substance rather than keystrokes: profiling the export before letting
anything be designed, the timezone strategy, choosing which constraints to add
*and which to leave off*, the duplicate-resolution ordering, deciding which
anomalies to reject versus surface, and the ranking in `REVIEW.md`.

**Something the tool gave me that I did not accept — median rounding.**

```python
# Before (generated)
median_duration_seconds=round(row["median_duration"])

# After
median_duration_seconds=math.floor(row["median_duration"] + 0.5)
```

`percentile_cont` interpolates, so on an even count it returns `.5` values.
Python's `round()` is round-half-to-**even**: `round(1230.5)` is `1230` but
`round(1231.5)` is `1232`. Two adjacent weekly medians rounding in opposite
directions is not something anyone should have to explain to a client, and it
would never have shown up in a test. The generated code was not *wrong* in any
way a test would catch, which is exactly why it needed reading.

**A second one — rounding in the wrong layer.**

```python
# Before (generated)
completion_rate=round(row["responses_completed"] / invitations, 6)

# After
completion_rate=row["responses_completed"] / invitations if invitations else None
```

Two problems. The `if invitations` guard was missing entirely, so survey 9
(zero invitations) would have thrown `ZeroDivisionError` — I caught that from
profiling, not from the code. And rounding in the API is presentation leaking
into the data layer: a client reconciling `completed / invitations` by hand
should get back exactly the number they computed. I found the second one only
because my own cross-check script flagged a tolerance mismatch — the
verification caught a design smell, not just a bug.

**Where it got me somewhere faster.** Writing the profiling pass over
`responses.csv` in one shot — every column's cardinality, every value that
would not parse, orphan foreign keys, duplicate key groups, the
status/`completed_at` cross-tab. That is thirty minutes of careful scripting
compressed to about three, and it is what surfaced the BOM, the seven status
spellings, the fact that every `partial` row carries a `completed_at`, and the
full empty-marker set. Nearly every decision in this repo traces back to that
output. The leverage was in knowing to *look* first; the speed came from the tool.

## 8. Where the two hours went

Roughly: 15 min reading the brief and profiling the data, 20 min on the schema,
30 min on the ingest, 15 min on `normalize.py`, 20 min on the endpoint and
verifying it, 15 min on the page, 25 min on `REVIEW.md` and this file, and a
further 20 min on the endpoint tests — see below.

**I went over the two hours.** The core six steps landed close to budget; the
risk register, the ADRs and the CI workflow are extra, and I would rather say
so than pretend otherwise. They are not padding — the register holds this
section's content with severities attached, the ADRs hold section 2's
reasoning, and CI runs the graded test suite and asserts the idempotency claim
instead of restating it — but they are additional, and the brief is explicit
that more is not better.

**The endpoint tests were the one thing I went back for.** An earlier draft
of this section listed them as not-done and named that as my weakest point,
which sat badly next to a `REVIEW.md` that blocks a PR partly for tests that
cannot fail. They are now in, mutation-checked, and running in CI. I have left
this paragraph in rather than quietly editing the gap away, because the
sequence is the honest one.

**What I did not get to**, in the order I would pick it up:

1. **Reconciliation on re-ingest.** Re-running the *same* file is provably
   idempotent, which is what was asked. A *changed* file whose duplicate
   winner has moved would leave the superseded row behind, because the upsert
   has no way to know it should go.
3. **The `created_date` anomaly** — 8.6% of responses predate their survey.
   Currently surfaced, not resolved. It needs a client answer, not more code.
4. Survey-level timezone override, and zero-filled quiet weeks if the client
   wants them.

**The one thing I am least happy with**, if I have to pick a single line: the
duplicate-resolution rule quietly drops 583 real responses. It is documented,
deterministic, reversible in one sort key and every dropped row is in
`rejects.csv` — but it is a judgement I made on the client's behalf about
1.5% of their data, and it should have been a question in their inbox before
the first run rather than an ADR after it.
