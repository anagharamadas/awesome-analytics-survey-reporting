# ADR 0001 — Store every instant as `TIMESTAMPTZ`, and put the reporting zone on the client

**Status:** Accepted · **Relates to:** E-05, S-02

## Context

The export writes `DD/MM/YYYY HH:MM:SS` with no offset marker at all. The
brief states this is Asia/Kolkata local time, and adds the constraint that
matters:

> A second customer is being onboarded in Dubai next quarter, so store
> timestamps in a way that will not have to be re-migrated when that happens.

Two separate concerns hide inside that sentence, and conflating them is the
trap:

1. **The instant** — the actual moment in time a response started.
2. **The reporting wall clock** — which local Saturday-to-Friday week that
   instant falls into, which differs for Kolkata (UTC+05:30) and Dubai
   (UTC+04:00).

## Options considered

**A. `TIMESTAMP WITHOUT TIME ZONE`, storing Kolkata wall-clock time.**
Simplest to eyeball against the CSV, and every existing row would read back
looking exactly like the source. But the column then means "local time in
some zone we did not write down". The moment Dubai rows land in the same
column, the stored values become mutually incomparable and every historical
row needs re-parsing to say which zone it was. This is precisely the
re-migration the brief warns against.

**B. `TIMESTAMPTZ`, with the reporting zone hard-coded as Asia/Kolkata in
the query.** Storage is correct and needs no migration. But onboarding Dubai
means a code change and a release, and the two clients can never be reported
in one query — the zone would have to be a request parameter that the caller
has to know to supply.

**C. `TIMESTAMPTZ`, with the reporting zone as an IANA name on `clients`.**
Chosen.

## Decision

Every instant column is `TIMESTAMP WITH TIME ZONE`. Postgres normalises
these to UTC internally, so the stored instants are already zone-neutral and
correct in perpetuity — there is nothing about them left to migrate.

`normalize.parse_client_datetime` attaches `Asia/Kolkata` rather than
converting to UTC, so parsing and storage stay separable: if a week lands in
the wrong bucket you can tell immediately whether the parser mislabelled it
or the query mis-bucketed it.

The reporting zone lives on `clients.reporting_timezone`, `NOT NULL DEFAULT
'Asia/Kolkata'`, holding an IANA name. The summary query converts with
`AT TIME ZONE c.reporting_timezone` before bucketing the week.

Onboarding Dubai is then:

```sql
INSERT INTO clients (name, reporting_timezone) VALUES ('…', 'Asia/Dubai');
```

No schema change, no backfill, no re-parse of history, and Kolkata and Dubai
clients can be reported side by side in one query, each in its own week.

## Consequences

- `tzdata` must be pinned in `requirements.txt`: `python:3.12-slim` ships no
  zoneinfo database, so `ZoneInfo("Asia/Kolkata")` raises inside the
  container while passing on macOS. (E-06 — this one bit.)
- `reporting_timezone` is `NOT NULL` with a default rather than nullable:
  "we do not know this client's reporting zone" is not a state the report
  can render, so the schema refuses to represent it.
- Neither Kolkata nor Dubai observes DST, so no timestamp in this dataset is
  ambiguous or non-existent. Nothing in the design leans on that — a DST
  zone would work, because `AT TIME ZONE` resolves the fold itself.
- The zone is per client, not per survey. If one client ever needs two
  reporting zones, this needs a nullable override on `surveys`. Not built;
  there is no evidence anyone wants it.
