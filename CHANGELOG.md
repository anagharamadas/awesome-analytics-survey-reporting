# Changelog

All notable changes to this project are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
This project is a single deliverable rather than a released library, so the
history is kept unreleased and grouped by the brief's six steps.

## [Unreleased]

### Added
- **Step 2 — ingest.** 38,017 rows read, 37,415 loaded, 590 rejected, and it
  reconciles exactly. Idempotent on natural keys + `ON CONFLICT DO UPDATE`,
  verified over three runs and from an empty database by content checksum, not
  just row counts.
- **Step 4 — `/api/surveys/{id}/summary`.** Saturday-to-Friday weeks bucketed
  in the client's own reporting timezone. 3.7 ms p50, 7.7 ms worst of 240
  samples against a 300 ms budget, answered by an Index Only Scan with zero
  heap fetches.
- **Step 5 — the page.** Weekly summary with loading, error and empty states.
  All twelve surveys verified, including survey 9 which has neither responses
  nor invitations.
- **Step 6 — `REVIEW.md`** (block, five ranked findings) and `README.md`.
- **Tests.** 74 total: 59 for `normalize.py`, 15 for the summary endpoint.
  The endpoint tests seed their own fixtures and were mutation-checked —
  removing the Saturday shift fails 12, counting all statuses fails 1,
  dividing by responses received fails 2.
- **Step 3 — `normalize.py`.** Three pure field parsers with a shared
  empty-marker set derived by reading `data/responses.csv` rather than
  guessing: `""`, `N/A`, `n/a`, `NULL`, `null`, `-`, `none`. 59 tests.
- **Step 1 — schema.** `clients ──< surveys ──< responses >── respondents`,
  plus `ingest_runs` for provenance. `TIMESTAMPTZ` throughout with the
  reporting zone on `clients.reporting_timezone`, so onboarding the Dubai
  customer is one `INSERT` and not a migration.
- `scripts/profile_data.py` — the profiling pass run before any schema was
  designed. Committed because every decision below cites its output.
- `RISK_REGISTER.md` — spec, data and delivery risks with the decision
  shipped against each.
- `docs/adr/` — architecture decision records for the four choices that
  would be expensive to reverse.
- CI running the backend test suite and a TypeScript build on every push.

### Changed
- `frontend/src/types.ts`: `completion_rate` and `median_duration_seconds`
  widened to `number | null`. Survey 9 has zero invitations and zero
  responses, so both are genuinely undefined for it, and the file's own
  comment invites saying so.

### Fixed
- `REJECTS_PATH` defaulted to `/repo/rejects.csv`, a path that only exists
  because docker-compose mounts it. CI caught the `PermissionError` on a bare
  checkout; the default is now derived from the module's own location and
  works in both environments.

### Security
- `Candidate Brief.html` removed from git history before the first push and
  added to `.gitignore`. It is the provider's material and does not belong
  in a public repo.

---

### Commit convention

[Conventional Commits](https://www.conventionalcommits.org/). Bodies carry
the *reasoning*, not a restatement of the diff — the brief says the history
is read as evidence of process, so each commit is meant to answer "why this
and not the obvious alternative" without the reader needing the code open.
