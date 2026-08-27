# Risk register

Live document. Every risk here is one I actually hit while building this
slice, not a generic checklist. Spec risks (`S-*`) are the substance of
README section 4 — "what I found wrong in the brief" — and each one records
the decision I shipped so it can be argued with rather than guessed at.

**Scoring:** likelihood × impact, each Low / Med / High.
**Status:** `Open` (live, needs a client answer) · `Mitigated` (handled in
code, decision documented) · `Accepted` (known, deliberately not fixed).

---

## S — Specification risks

These are ambiguities and contradictions in the client's brief. The brief
says client specs are rarely perfect and that spotting this is part of the
job. Each was decided, not ignored, and each decision is reversible in one
place.

| ID | Risk | L | I | Decision shipped | Status |
|----|------|---|---|------------------|--------|
| S-01 | **`responses_started` excludes status `started`.** The client's rule says "a partial counts in the response count; `abandoned` and `started` count in neither", so the field named `responses_started` must exclude the rows whose status is literally `started`. A reader who trusts the field name gets a different number. | High | High | Implemented per the client's prose, not the field name: `responses_started` = `completed` + `partial`. Flagged for renaming to `responses_counted`. | Open |
| S-02 | **Which timestamp decides the reporting week is never stated.** `started_at` and `completed_at` can fall in different weeks. | High | High | Bucket on `started_at`. It is `NOT NULL` on every row, so no response is ever invisible; bucketing on `completed_at` would put the two counts on different clocks and stop the columns tying out. | Mitigated |
| S-03 | **The median's population is never stated.** Median of all responses, of completed only, or of the counted set? | High | Med | Median over the same rows as `responses_started` (`completed` + `partial`) with a non-null duration. Same population as the count beside it, so the columns are mutually consistent. | Mitigated |
| S-04 | **Weekly completion rate divides by a campaign-level denominator.** "Completed over invitations sent for that survey" gives every week the same denominator, so weekly rates are individually tiny. | Med | Med | Implemented exactly as stated — the client was emphatic and says the point is "to see who never turned up". Weekly rates do sum to the campaign rate, so it is coherent. Flagged as surprising. | Mitigated |
| S-05 | **`invitations_sent = 0` makes completion rate undefined.** Survey 9 ("Pilot - Do Not Report") has 0 invitations. | High | High | `completion_rate` returns `null`, never `0` and never a division error. `types.ts` widened to `number \| null`; the UI renders `—`. Inventing 0% would be a wrong number, which is worse than an honest blank. | Mitigated |
| S-06 | **Which duplicate wins is never stated.** 578 respondents answered the same survey twice (584 surplus rows). | High | High | Rank `completed` > `partial` > `started` > `abandoned`, then latest `started_at`, then highest `response_id`. Deterministic, so re-running the ingest picks the same winner every time. Losers go to `rejects.csv`. | Mitigated |
| S-07 | **"Ratings are 1 to 5 … reject it" — reject the row, or null the rating?** `rejects.csv` is row-level, which implies the row. | Med | Med | Reject the whole row. The brief pairs the rule with "bad rows go to `rejects.csv`", and silently nulling a field the client called a data error would hide it. | Mitigated |
| S-08 | **No rule for timestamps outside the reporting period.** Row 900018 is dated 31/12/2027, a year past every other row. | Med | Low | Loaded, not rejected. It parses and is internally consistent; the brief gives no rule against it, and deleting real data on an invented rule is worse than surfacing it. It appears as a lone 2027 week. | Accepted |
| S-09 | **Step 6a contains a direct contradiction.** Compliance (4 Aug): every response "gone permanently". Reporting (11 Aug): the audit table keeps "every response ever submitted". Both cannot hold for the same data. | High | High | Not built (design-only step). Resolved in README section 6 by separating the personal data from the countable fact. | Open |
| S-10 | **`GET /api/surveys` has no specified response shape.** "Return whatever the list page needs." | Low | Low | Returns exactly the `Survey` type already declared in `frontend/src/types.ts`, since the front end was written against it. | Mitigated |

---

## D — Data risks

Found by `scripts/profile_data.py` before any schema was written. The export
"has been through three system migrations" and the brief says to assume
nothing about it.

| ID | Risk | L | I | Mitigation | Status |
|----|------|---|---|------------|--------|
| D-01 | **`responses.csv` is BOM-prefixed.** A plain `utf-8` read names the first column `﻿response_id` and every lookup on `response_id` silently misses. | High | High | Read with `encoding="utf-8-sig"` everywhere, including the profiler. | Mitigated |
| D-02 | **Seven spellings of four statuses** (`COMPLETED`, `Completed`, `completed`, `Partial`, `partial`, …). Case-sensitive comparison undercounts completions by roughly two thirds. | High | High | Case-folded at ingest; canonical set pinned by a `CHECK` constraint. | Mitigated |
| D-03 | **Every `partial` row carries a `completed_at`** (10,953 of them). Inferring completion from that column's presence overcounts completions by ~67%. | High | High | Completion is read from `status` only. The `CHECK` constraint deliberately permits `partial` to hold a `completed_at`, documenting that the column means "last activity". | Mitigated |
| D-04 | **Multiple spellings of "no value":** `""`, `N/A`, `n/a`, `NULL`, `null`, `-`, `none`. Treating any as a literal string turns an absence into a data error, or worse into a value. | High | High | One shared `_clean()` in `normalize.py` matches the set case-insensitively for all three functions. Set derived from the file, not guessed. | Mitigated |
| D-05 | **Orphan foreign key.** Row 900010 references `survey_id = 47`, which does not exist in `surveys.csv`. | Med | High | FK is `NOT NULL`; the ingest rejects the row with reason `unknown_survey`. | Mitigated |
| D-06 | **Duplicate primary key.** `response_id = 900011` appears twice, byte-identical. | Med | High | Natural PK on `response_id` plus an upsert; the second occurrence is logged as `duplicate_response_id`. | Mitigated |
| D-07 | **Impossible calendar date.** Row 900006 is `29/02/2023`; 2023 is not a leap year. A lenient parser (`dateutil`) would silently slide it to 1 March. | Med | High | `strptime` validates the calendar and raises. Rejected as `unparseable_started_at`. | Mitigated |
| D-08 | **Timestamps that finish before they start.** Rows 900007 and 900008. | Med | High | Rejected at ingest and additionally forbidden by `ck_responses_completed_after_started`. | Mitigated |
| D-09 | **Negative and comma-formatted durations** (`-2400`, `2,460`). | Med | Med | `parse_duration_seconds` strips the separator (formatting) and returns the negative unchanged; the ingest rejects the negative as implausible, per the function's own docstring. | Mitigated |
| D-10 | **Non-ASCII payloads** — emoji, Devanagari, umlauts, apostrophes, embedded quotes and literal `\n` in free text. Any of these breaks a naive CSV writer or a string-concatenated query. | Med | High | UTF-8 end to end, `csv` module for both read and write, parameterised SQL throughout. | Mitigated |
| D-11 | **Email variants from three unsynchronised systems** — case and trailing whitespace differ for the same person. | High | High | Canonicalised in `normalise_email`. Dots and `+tags` deliberately **not** stripped: those are one provider's delivery quirks, and stripping them would merge genuinely distinct respondents. | Mitigated |
| D-12 | **PII-shaped content in a public repo.** `data/responses.csv` carries names and email addresses. | Low | Med | Verified synthetic: every address is `@example.com` (RFC 2606 reserved) and names recombine from a small fixed pool. Provider-supplied and provider-sanctioned for a public repo. | Accepted |

---

## E — Engineering and delivery risks

| ID | Risk | L | I | Mitigation | Status |
|----|------|---|---|------------|--------|
| E-01 | **Two-hour cap is a hard cap.** The brief states that over-delivering scores *worse*, not better. | High | High | Time boxed per step; anything unreached is stated plainly in README section 8 rather than quietly finished late. | Accepted |
| E-02 | **`/summary` must return under 300 ms** against the fully loaded dataset. | Med | High | Single aggregate query, weekly bucketing pushed into Postgres, covering index `(survey_id, started_at) INCLUDE (status, duration_seconds)`. Measured number and method in README section 5. | Mitigated |
| E-03 | **Re-running the ingest must not double the data.** | High | High | Natural keys plus `INSERT … ON CONFLICT DO UPDATE`. Verified by running twice and diffing row counts. | Mitigated |
| E-04 | **The page must survive all twelve surveys,** including ones with no data at all. | High | High | Survey 9 has zero responses *and* zero invitations — the exact case that produces both an empty table and a divide-by-zero. Explicit empty state; all twelve clicked through. | Mitigated |
| E-05 | **A `timestamp without time zone` column would need re-migrating** when the Dubai customer onboards next quarter. | Med | High | `TIMESTAMPTZ` throughout; the reporting zone lives on `clients.reporting_timezone` as an IANA name, so onboarding Dubai is one `INSERT`. | Mitigated |
| E-06 | **`python:3.12-slim` ships no zoneinfo database,** so `ZoneInfo("Asia/Kolkata")` raises at import inside the container while passing on macOS. | Med | High | `tzdata` pinned in `requirements.txt`. | Mitigated |
| E-07 | **No licence is granted on this repo.** It contains provider-supplied scaffold and data that I do not hold the rights to relicense, so no `LICENSE` file was added — an MIT header here would be a claim I cannot make. | Low | Med | Deliberate omission, recorded here so it reads as a decision rather than an oversight. | Accepted |
| E-08 | **`Candidate Brief.html` is the provider's IP.** Committing it to a public repo republishes their assessment. | Med | Med | Stripped from git history before the first push and added to `.gitignore`; kept on local disk only. | Mitigated |
