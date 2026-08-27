# Changelog

All notable changes to this project are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
This project is a single deliverable rather than a released library, so the
history is kept unreleased and grouped by the brief's six steps.

## [Unreleased]

### Added
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
