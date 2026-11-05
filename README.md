# Vestor

**Know what your compensation is worth after tax — and what to put into your pension.**

Vestor is a planned local-first UK compensation planner for salary, bonuses, employee RSUs, taxable benefits, pension contributions and share disposals. It models actual and forecast events separately, helps estimate adjusted net income (ANI) around the £100,000 Personal Allowance taper, and explains spendable proceeds and pension trade-offs.

> **Status:** specification stage. No calculation engine has been implemented or verified yet. Estimates are planning aids, not tax advice.

- [Project overview and roadmap](PROJECT.md)
- [Product and financial rules specification](docs/SPEC.md)
- [Instructions for coding agents](AGENTS.md)

## Principles

- Keep financial information local and private; never commit real payroll, vesting or account data.
- Use UK-tax-year-aware, versioned rules and explicit GBP currency conversions.
- Distinguish taxable vesting income from gains on later share sales.
- Separate actual values from forecasts, and estimates from confirmed payroll deductions.
- Make every result auditable from its underlying events, rates and assumptions.
- Build deterministic, tested rules before dashboards or external integrations.

## Planned development

M1 — Compensation, adjusted net income and pension calculations

M2 — RSU vesting, share disposals, GBP FX and CGT matching

M3 — Scenario comparisons, pension optimisation and cash projections

M4 — Local persistence, reporting, usability and verification

See [PROJECT.md](PROJECT.md) for milestone boundaries. GitHub issues will be created separately.

## Privacy

This repository is public. **Do not commit real compensation amounts, employer records, tax statements, account details, trade confirmations, or imported statements.** Any examples in the documentation are fictional.
