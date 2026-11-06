# Vestor — Project Overview

## 1. Vision

Vestor is a **local-first, single-user UK compensation and tax planning application** for people who receive salary, bonuses, employer share awards (particularly US-listed RSUs), taxable benefits and pension contributions.

Headline question:

> **How much extra cash can I safely spend from my compensation, and what pension contribution gets me to my desired adjusted net income?**

A user can model their compensation across a UK tax year, change future share prices, FX rates and bonus amounts, and see an explainable calculation of:
- projected **adjusted net income (ANI)**, with headroom to a user-defined target (initially £100,000);
- additional gross pension contribution or salary sacrifice needed to reach that target;
- estimated spendable proceeds from RSU sales and net bonuses;
- the separate treatment of employment income at RSU vest and CGT on subsequent share sales;
- uncertainty, unsupported cases and data yet to be confirmed.

This is a planning tool, **not** a payroll engine, tax filing service, personal investment adviser or successor to Payday. Payday answers cash-flow questions; Vestor answers compensation, tax and pension-scenario questions.

## 2. Non-negotiable product principles

1. **Financial correctness first.** Deterministic, versioned tax rules, decimal arithmetic, explicit rounding, comprehensive worked examples, and traceable calculations.
2. **Actual vs forecast.** Actual taxable GBP payroll figures supersede modelled FX approximations. Future events are always labelled assumptions.
3. **Different taxes, different bases.** Vesting is usually employment income; subsequent disposal can generate CGT. A tax-withholding sale is not a reduction in vest income.
4. **No double-counting.** Payrolled benefits, RSU amounts and salary-sacrifice deductions must not be added or deducted twice.
5. **Local-first and private.** No login, cloud account, telemetry or third-party data feed required for core features. Local data is not checked into Git.
6. **Explain all outputs.** Every figure should expose events, dates, taxable bases, FX source/rate, tax-year rule version and assumptions.
7. **Tax-year precision.** UK tax years run 6 April through 5 April. Never treat a calendar-year boundary as a tax-year boundary.
8. **Conservative uncertainty.** Unsupported tax cases surface warnings or are blocked; never silently apply a guessed rule.
9. **User control.** Editing a scenario must never rewrite actual events or source records.
10. **Issue-sized development.** Each milestone has documented acceptance criteria; code agents work from focused GitHub issues.

## 3. Target user experience

- A **tax-year dashboard** presents salary, RSUs, bonus, employer benefits, pension, other income, projected ANI and progress against the target.
- A **compensation calendar** shows actual and predicted vestings, bonus dates, sales and pension elections.
- An **RSU ledger** lists grants/vest lots, sale transactions, sell-to-cover, fees and FX conversions, with links to the underlying calculations.
- A **scenario planner** compares share price, bonus and pension choices side by side: current plan versus optimistic and conservative cases.
- A **pension planner** works backwards from a chosen ANI target, with configurable buffer and practical bounds such as available bonus and scheme restrictions.
- A **cash view** distinguishes gross pay/share value, tax withheld or owed, fees, pension contributions, cash actually received, tax still potentially payable and spendable cash.
- Each screen distinguishes **confirmed / estimated / unknown** input values.

## 4. Scope and boundaries

### M1 — Compensation and ANI foundation
- Tax-year configuration and effective-dated UK rules (initially 2026/27; personal tax residence/jurisdiction explicit).
- Base salary and effective-dated salary-sacrifice changes.
- Bonus events: expected versus confirmed, taxable period, optional bonus sacrifice.
- Pension methods: salary sacrifice, net pay, relief at source; model each correctly and avoid duplicate relief.
- Taxable employer benefits with renewal and effective dates; payrolled/P11D reconciliation flags.
- Other income inputs relevant to ANI, including interest and dividends, with correct gross-income distinctions.
- Adjusted net income calculation and £100k Personal Allowance taper.
- Transparent explanation, input validation and worked-example unit tests.
- M1 **does not** claim to calculate full UK tax bills or RSU CGT.
- [M1 detailed milestone specification](docs/M1_COMPENSATION_ANI.md) · [M1 live issue tracker](https://github.com/amberdemon/vestor/issues/1).

### M2 — RSU, FX and CGT
- Actual and forecast vest schedules, number of shares and vest FMV, original payroll taxable GBP amount.
- Employee share events: vest/acquisition, same-day sell-to-cover disposal and voluntary share sales.
- USD/GBP conversion by event date; separate vest-income, acquisition cost, disposal proceeds and fee basis.
- UK share identification: same-day, qualifying 30-day acquisitions, Section 104 pool, with chronological ordering and partial lots.
- CGT tax-year allowance/rates and provisional CGT, with explicit scope constraints.
- Actual and expected withholding/repayment tracked independently from taxable vest income.
- M2 **does not** import broker files automatically or handle every kind of employee equity arrangement.

### M3 — Scenarios and pension optimisation
- Variable vest/sale share prices and FX assumptions, bonus variations, pension rates and target ANI.
- Scenario comparison with effective income tax/NI and marginal benefit where implemented and supported.
- Minimum additional gross contribution needed to meet ANI target, with configurable buffer.
- Bonus-only versus monthly sacrifice and fallback personal pension contribution paths; eligibility and deadlines surfaced.
- Compare **spendable cash**, **pension contribution** and **outstanding tax provision** separately.
- Restrict optimisation by user-entered contribution eligibility/allowances and employer scheme rules; flag rather than silently assume.

### M4 — Local persistence and product polish
- Durable local scenarios and actual event history, editing with audit details, JSON/CSV export and restore.
- Accessible dashboard, mobile layout and print-friendly calculation report.
- Dockerised, loopback-only operation, SQLite persistence with migration/testing strategy.
- No accounts, bank access or cloud sync by default.

## 5. Engineering direction

**M1.2 scaffold architecture:** a pure Python `Decimal` domain, a thin FastAPI bridge and a React/TypeScript/Vite shell. FastAPI serves the built UI and health endpoint on one loopback-only Docker Compose port. pytest, mypy, TypeScript and Vitest run in Docker and PR CI. See the [architecture decision](docs/M1_APP_ARCHITECTURE.md) and [local commands](README.md#run-locally). SQLite remains planned for M4.

For early M1, a minimal functional interface is acceptable. Prioritise the deterministic engine; avoid premature microservices, user login, real-time quote providers, background jobs, bank connectors, Kubernetes and an AI tax-calculation layer. No automatic fetching of historical tax or FX rates is required for core use: user-entered rates must work offline.

## 6. Domain language

- **Tax year:** 6 April to next 5 April, named by start/end year.
- **Employment income:** taxable pay and value of taxable benefits, including gross taxable RSU value at vest.
- **ANI:** HMRC-defined adjusted net income; not identical to gross salary or payslip taxable pay.
- **RSU vest:** shares delivered at vest; FMV is employment-income basis in typical UK arrangements, subject to scheme facts.
- **Acquisition cost:** GBP allowable cost used for CGT; may differ from display-only USD cost basis.
- **Withholding:** tax/NI paid or earmarked through payroll/sell-to-cover, not automatically a deductible expense.
- **Disposal:** sale or other disposal generating proceeds and a potential gain/loss.
- **Share matching:** UK statutory ordering for same class in same capacity: same day, following 30 days, then Section 104 pool, subject to precise statutory conditions.
- **Scenario:** an immutable set of assumptions layered onto source events; cannot overwrite actuals.
- **Spendable cash:** actual or projected received cash net of sale costs, withholding, tax liabilities/repayments, transfers and chosen pension sacrifice, with already-paid versus outstanding taxes separate.

## 7. Quality and safety requirements

- Currency amounts, FX conversion, quantities and tax computations cannot use binary floating point.
- Version tax rules by tax year and jurisdiction. Show rules version and a verification date.
- Display figures in GBP with clear rounding conventions; retain high precision for interim steps.
- Make assumptions editable, not hidden. Never assert the current market price or exchange rate without a dated source.
- Do not provide false precision for a tax-year projection. Label withholding as estimated where not confirmed.
- Explicitly exclude or warn for unsupported situations (non-UK residence, cross-border tax, split-year residence, complex pension annual allowances/taper/carry-forward, share options, jointly held or mixed-class shares, corporate actions).
- Test negative gains, multi-lot RSUs, sell-to-cover matching, 30-day matching, GBP exchange gains, benefits rate changes, pension methods and the Personal Allowance taper.
- Avoid storing credentials, tax identifiers or statements in logs. No analytics.
- Human review needed for tax rule changes; cite source legislation/HMRC guidance in the financial spec.

## 8. Definition of done for milestones

A milestone is complete only when:
1. user-facing functions in its scope operate locally;
2. acceptance tests and worked examples pass;
3. source figures, assumptions, limitations and output breakdowns are inspectable;
4. `PROJECT.md`, `docs/SPEC.md` and relevant documentation reflect shipped behaviour;
5. an integration/verification issue documents supported and unsupported cases.

## 9. Immediate next steps

1. Review the [M1.1 financial contract](docs/M1_FINANCIAL_CONTRACT.md) and synthetic fixtures.
2. Use the [M1.2 scaffold](docs/M1_APP_ARCHITECTURE.md) for local development and checks.
3. Follow the [M1 tracker](https://github.com/amberdemon/vestor/issues/1) in dependency order, with PR review and tests for each implementation issue.
4. Do not expand to M2 calculations until M1 has verified results.

**Implemented foundations.** The M1.2 scaffold provides local startup and health checks. M1.3 adds versioned 2026/27 rules, inclusive UK tax-year dates and dated GBP evidence in the Python domain. M1.4 adds effective-dated salary and dated bonus calculations in the Python domain, with payroll provenance and an explicit pension reduction basis. M1.5 adds payroll pension reductions, separate personal pension and Gift Aid deductions, and ordinary employer contribution evidence in the Python domain. The combined ANI calculation and user interface remain planned.
