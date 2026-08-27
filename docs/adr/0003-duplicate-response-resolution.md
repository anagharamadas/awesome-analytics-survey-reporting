# ADR 0003 — Resolve duplicate responses by outcome, then recency

**Status:** Accepted · **Relates to:** S-06, D-06

## Context

The brief says a respondent counts only once per survey, and says nothing
about which response to keep when there is more than one. This is not an
edge case: **578 respondents answered the same survey twice, 584 surplus
rows**. Whichever rule is chosen moves the completion rate on the client's
screen, so it cannot be left to insertion order.

Separately, `response_id = 900011` appears twice, byte-identical — a
different problem (a duplicated *row*, not a duplicated *person*) needing a
different answer.

## Options considered

**A. Earliest `started_at` wins.** "The first attempt is the real one."
Simple to explain, but can discard a `completed` response in favour of an
`abandoned` one, deflating the completion rate — the single number the
client cares most about.

**B. Latest `started_at` wins.** What a naive upsert does by accident. Same
defect as A: recency alone can throw away the better outcome.

**C. Keep every row, deduplicate in the query with `DISTINCT ON`.** Loses no
data. Rejected: it moves a business rule into the endpoint, has to be
repeated in every future query, and spends the 300 ms budget on work that
belongs at write time.

**D. Rank by outcome first, then recency.** Chosen.

## Decision

Within one `(survey_id, respondent_id)` group, keep the row that sorts first
by:

1. **Outcome rank** — `completed` > `partial` > `started` > `abandoned`
2. **Latest `started_at`** — the most recent attempt at that outcome
3. **Highest `response_id`** — a total order, so ties cannot exist

Every losing row is written to `rejects.csv` with reason
`duplicate_respondent_in_survey`, so the count reconciles.

Duplicate `response_id` is handled earlier and separately: the first
occurrence wins, the second is logged as `duplicate_response_id`. That is a
file defect, not a business decision.

## Consequences

- **Deterministic.** Step 3 makes the ordering total, so the same input
  always produces the same winner. Without it, re-running the ingest could
  quietly swap winners and change the report while claiming idempotency.
- Biased toward counting a respondent as completed where they ever
  completed. That is the honest reading of "a respondent counts only once" —
  the person did complete the survey; the duplicate is a system artefact.
- Rejecting 584 rows that are not *malformed* slightly overloads the word
  "reject". Kept anyway: `rejects.csv` is meant to account for every row not
  in the database, and a distinct reason string keeps the two categories
  separable. README section 3 reports them separately.
- If the client says the first attempt should win, only the sort key
  changes — one line, one place.
