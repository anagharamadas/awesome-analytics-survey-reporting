# Architecture decision records

One short record per decision that would be expensive to reverse later.
Format is [MADR](https://adr.github.io/madr/)-flavoured and deliberately
brief: context, the options considered, what was chosen, and the cost of
being wrong.

Decisions that are cheap to change (naming, layout, which test runner) are
not recorded here. Only the ones where a future maintainer would otherwise
have to reconstruct the reasoning from scratch.

| ADR | Decision | Status |
|-----|----------|--------|
| [0001](0001-store-timestamps-as-timestamptz.md) | Store every instant as `TIMESTAMPTZ`; put the reporting zone on the client row | Accepted |
| [0002](0002-respondents-as-a-table.md) | Model respondent identity as its own table keyed on canonical email | Accepted |
| [0003](0003-duplicate-response-resolution.md) | Resolve one-respondent-two-responses by outcome, then recency | Accepted |
| [0004](0004-bucket-the-reporting-week-on-started-at.md) | Bucket the reporting week on `started_at` | Accepted |
