## What this changes

<!-- One or two sentences. What behaviour is different after this merges? -->

## Why

<!-- The reasoning, not the diff. What was wrong before, or what is now
     possible that was not? Link the ADR or risk-register ID if there is one. -->

## How I verified it

<!-- What you actually ran, and what it printed. "Tests pass" on its own is
     not evidence — say which tests, and what they would have caught. -->

- [ ] `docker compose exec backend pytest`
- [ ] Ingest re-run is still idempotent (row counts unchanged on second run)
- [ ] `/summary` still returns under 300 ms on the full dataset
- [ ] Clicked through all twelve surveys, including survey 9 (zero responses,
      zero invitations)

## Risks and what I did about them

<!-- Anything a reviewer should push on. If a decision was a judgement call
     rather than the only option, say so here and say what the alternative was. -->

## Checklist

- [ ] Reasoning is in the commit body, not only in this description
- [ ] New decisions that are expensive to reverse have an ADR in `docs/adr/`
- [ ] `RISK_REGISTER.md` updated if this opens, closes or changes a risk
- [ ] `CHANGELOG.md` updated
- [ ] No secrets, tokens or credentials in the diff
