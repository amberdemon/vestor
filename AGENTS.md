# AGENTS.md — Vestor coding-agent instructions

## Purpose and required reading

Vestor is a local-first UK RSU, compensation, tax and pension planning tool. It is **not** Payday and is **not** a tax return preparation service.

Before implementing any issue, read, in order:
1. `PROJECT.md`
2. `docs/SPEC.md`
3. the GitHub milestone/tracker and the specific assigned GitHub issue
4. existing tests and the relevant implementation

The **issue is the unit of implementation**. Do not implement future-milestone scope opportunistically.

## Financial safety and correctness

- Use exact decimal or integer/rational arithmetic for financial values and FX. **Never use binary floating-point money arithmetic.**
- Do not confuse adjusted net income, employment income, RSU vest value, capital gains, employer withholding and cash proceeds.
- In UK RSU cases, separate taxable vesting value from share acquisition basis and later share disposal; sell-to-cover is both a share disposal and a method of settling withholding.
- Respect separate event dates, GBP conversions, tax years and tax rules versions.
- The UK share matching engine must apply proper same-day, following-30-day and Section 104 ordering. Do not implement a shortcut that matches all shares acquired on a later vest to earlier sales without considering simultaneous disposals.
- Actual, confirmed payroll GBP values take precedence over forecast FX-derived values; keep the original evidence and explain discrepancies.
- Do not silently assume a benefit premium equals a taxable benefit, a broker FX fee is a CGT deduction, or a personal pension contribution is salary sacrifice.
- Model pension contribution methods separately; do not double-subtract salary sacrifice or net-pay contributions.
- Unsupported tax situations and incomplete inputs must produce explicit warnings, not confident tax values.
- All computed outputs must expose inputs, dates, assumptions, rule version and a clear explanation.
- Tax rule changes require independent source verification, documented effective date and tests.

## Architecture

Proposed stack from `PROJECT.md`: React/TypeScript/Vite UI, Python `Decimal` financial domain, optional FastAPI API, SQLite, Docker Compose. The first implementation issue must confirm the smallest maintainable vertical slice and lock dependencies.

Keep domain functions pure and testable. Keep UI presentation separate from money and tax rules. Avoid microservices, Redis, Kubernetes, authentication, bank feeds, third-party stock price calls, LLM-generated calculations or remote analytics in early milestones.

Run locally and offline for core use. Expose any local HTTP service to `127.0.0.1` on the host by default. Use migrations for persisted data once introduced.

## Security and privacy

**This repository is public.** Do not commit personal compensation details, employer tax forms, account numbers, real transaction histories, user identifiers, credentials, API keys or secrets.

Use synthetic examples in tests, screenshots, seed data and issues. Never log real financial data or publish it in PR output. Keep user data in local persistence ignored by Git.

## Tests and acceptance

For any financial-rule change:
- Add deterministic, table-driven / parametrised tests based on the fixtures in `docs/SPEC.md`.
- Cover boundary dates (6 April/5 April, effective-dated compensation changes and 30 calendar days), precision and rounding, FX moves, partial lots, tax method differences and missing-data paths.
- Cite the verified HMRC / legislation guidance and the applicable tax year in code comments or docs near the rule, as appropriate.
- Run affected unit tests plus the canonical full test suite before PR completion.
- Never weaken or delete tests to make CI pass.
- Include independent worked examples for major tax calculations; use no production/user payroll data.

## Scope control

- **M1:** compensation records, taxable benefits, pension methods, adjusted net income, Personal Allowance taper and explainable breakdown. Do not implement CGT or claim accurate net take-home tax calculations in M1.
- **M2:** RSU transaction ledger, GBP FX, share matching and qualified CGT, grounded in M1.
- **M3:** pension optimisation, tax-aware scenario comparisons and spendable-cash projections using verified supported rules.
- **M4:** persistence, export, accessibility and polish. Do not add cloud user accounts or bank integrations.

Do not call a milestone complete without the verification issue and documented supported limitations.

## Pull requests

One issue per focused PR where practical. PR description must include:
- issue and linked dependencies;
- summary and design decisions;
- financial rule assumptions and HMRC sources (if relevant);
- tests run and results;
- limitations / remaining uncertainties;
- screenshots for visible UI changes (using synthetic data).

Update `PROJECT.md`, `docs/SPEC.md`, and any relevant documentation when behaviour or architecture changes. Never silently change the roadmap or financial rule contract.

## Important distinction

The documentation currently describes **planned** features. Do not describe unimplemented features as shipped. If the issue depends on an unsupported tax case, surface the blocker and propose a narrowly scoped design/research issue before continuing.
