# ADR 0004 — Bucket the reporting week on `started_at`

**Status:** Accepted · **Relates to:** S-01, S-02, S-03, D-03

## Context

The client is emphatic about the week:

> Our reporting week runs Saturday to Friday. It always has. Every other
> report we get uses this and the numbers have to tie out.

What they never say is **which timestamp** puts a response in a week. A
response can start on Friday and complete on Saturday, landing in two
different weeks depending on the column chosen.

## Options considered

**A. Bucket on `completed_at`.** Reads more literally for
`responses_completed`. Rejected: 10,755 rows have no `completed_at` at all,
so they would need a fallback to `started_at` — meaning the two counts in
one row of the report would be bucketed by two different clocks, and the
columns would stop tying out. That is the one thing the client asked for.

**B. Bucket on `started_at`.** Chosen.

## Decision

A response belongs to the week its `started_at` falls in, evaluated in the
client's own reporting timezone (ADR 0001). `started_at` is `NOT NULL` on
every row, so no response is ever invisible.

`responses_completed` therefore means "started in this week and was
completed", not "was completed during this week". Stated in README section 4
because it is a real semantic difference a client could disagree with.

**Computing a Saturday-start week in Postgres.** `date_trunc('week', …)`
returns Monday and has no offset argument. Shifting the input by two days
moves Saturday onto Monday, and shifting the result back recovers it:

```sql
date_trunc('week', local_ts + interval '2 days') - interval '2 days'
```

Checked at both boundaries: Sat 3 Jan 2026 → +2d = Mon 5 Jan → truncates to
Mon 5 Jan → −2d = **Sat 3 Jan**. Fri 9 Jan → +2d = Sun 11 Jan → truncates to
Mon 5 Jan → −2d = **Sat 3 Jan**. Both ends of the Saturday-to-Friday week map
to the same Saturday, and Sat 10 Jan opens the next one.

## Consequences

- **Two counts, one clock.** Both `responses_started` and
  `responses_completed` come from the same bucketing expression, so the
  columns reconcile by construction.
- The counted population is `completed` + `partial`, per the client's rule
  that "a partial counts in the response count … `abandoned` and `started`
  count in neither". This makes the field named `responses_started` exclude
  the rows whose status is literally `started` (S-01). Implemented per the
  prose, flagged for renaming.
- Completion is read from `status`, never from whether `completed_at` is
  present. Every one of the 10,953 `partial` rows carries a `completed_at`,
  so that column means "last activity"; trusting it would overcount
  completions by roughly two thirds (D-03).
- `median_duration_seconds` is taken over the same rows as
  `responses_started`, with non-null durations, so the median describes the
  population counted next to it. `percentile_cont` (interpolated, the
  textbook median) rather than `percentile_disc`. A week where no counted
  response recorded a duration returns `null`, not `0`.
- The lone 2027 row (S-08) produces one sparse week far from the rest. Left
  visible on purpose — it is real data, and it doubles as proof the page
  survives sparse weeks.
