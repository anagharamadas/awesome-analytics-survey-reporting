# ADR 0002 — Model respondent identity as its own table

**Status:** Accepted · **Relates to:** D-11, S-06

## Context

The brief gives one rule and one warning:

> A respondent counts only once per survey.
> Their email addresses arrive from three different client systems and have
> never been normalised.

Profiling the export: 35,170 distinct raw email strings, and **2,189
canonical addresses appear in more than one survey**. So a respondent is
genuinely a cross-survey entity, not a per-response attribute.

## Options considered

**A. Canonical email as a column on `responses`,** with
`UNIQUE (survey_id, respondent_email_canonical)`. Fewer tables, no join.
Still enforces the rule. But the same person is stored 2,189+ times over,
the unique index is on a 320-byte string rather than an integer pair, and
there is nowhere to hang anything about a person later — which matters
immediately, because the Step 6a delete question is entirely about
separating a person's identity from their countable responses.

**B. Respondents table, plus a denormalised copy of the email on
`responses`.** Fastest reads. Rejected: two sources of truth that drift, and
under questioning there is no good answer for which one wins.

**C. `respondents` table, FK from `responses`.** Chosen.

## Decision

`respondents(id, email_canonical UNIQUE NOT NULL, display_name NULL)`, where
`email_canonical` is exactly what `normalise_email()` returns.

`responses.respondent_id` is a `NOT NULL` FK, and the business rule is a
database constraint:

```sql
UNIQUE (survey_id, respondent_id)  -- uq_responses_one_per_respondent
```

## Consequences

- The rule cannot be broken by a future writer. Enforcing "once per survey"
  only in the loader means the next backfill script, admin endpoint or
  hand-run `INSERT` silently corrupts the report. 578 respondents in this
  export already answered twice, so this is live, not theoretical.
- `display_name` is nullable on purpose. Row 900019's `respondent_name` is
  three spaces, and the same person appears under different capitalisations.
  The name is display convenience the report never joins on, so an absent
  one is not worth rejecting a response over.
- Canonicalisation is **case and surrounding whitespace only**. Dots and
  `+tags` are deliberately preserved: those are one provider's delivery
  quirks, not email semantics, and folding them would merge distinct people.
  Row 900003's free text — *"It is O'Brien, not Obrien"* — reads as the
  dataset making exactly this point.
- Identity is the canonical email, so a person who changes address becomes
  two respondents. Correct for this dataset (the client has no other
  identifier) and honest about its limit.
