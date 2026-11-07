# M1 — Compensation & Adjusted Net Income Foundation

**Status:** M1.2 scaffold and M1.3–M1.6 domain calculations for tax-year evidence, salary, bonus, pensions, Gift Aid and benefits implemented. The combined ANI calculation remains planned.
**Tax year:** UK 2026/27 (6 April 2026–5 April 2027)
**Jurisdiction:** UK resident, England/Northern Ireland rules for first release. Other jurisdictions/complex residence cases must be explicitly unsupported.
**Parent:** [PROJECT.md](../PROJECT.md) · [Financial specification](SPEC.md)

## Mission

Ship a usable, offline, single-user **adjusted net income (ANI) planning calculator** with an auditable breakdown, not a general tax return or full UK PAYE/NI estimator.

A user can enter annual salary, effective dates, salary-sacrifice pension, bonuses, RSU **GBP taxable vest income** (manual entry), employer benefits, personal pension contributions, savings interest, dividends, other supported income, Gift Aid, and an ANI target. The app determines which values fall in the selected UK tax year, shows projected ANI and its components, the standard Personal Allowance taper, and distinguishes actual figures from forecasts.

> M1 only handles RSUs as **employment-income events already valued in GBP**. USD vesting, share disposals, withholding and CGT are M2. Pension **optimisation** and precise net take-home cash comparisons are M3.

## Important scope decisions

1. **Calculation before presentation.** Implement a pure, deterministic Python `Decimal` domain engine, then a thin UI calling the same engine. Do not recreate business rules in TypeScript.
2. **Minimal app slice.** React/TypeScript/Vite and a tiny FastAPI endpoint are permitted if chosen in M1.2; SQLite is reserved for M4. Docker Compose must work offline after images/dependencies are installed, publishing only on loopback.
3. **No persistent financial record** in M1. Inputs may live in transient UI state, with a clear *not saved* warning. Durable local storage, imports and exports belong to M4.
4. **Supported 2026/27 rules** are versioned and source-cited; do not auto-use rules for another tax year. On unsupported jurisdictions/years or missing material inputs, show an explicit unsupported/incomplete state.
5. **Actual beats forecast.** A confirmed payroll taxable GBP value overrides any earlier estimate, without treating both as separate income.
6. **Financial data privacy.** The repository is public: use **synthetic test fixtures only**, no real compensation or payroll details.

## M1 release acceptance

- [ ] A clean checkout can launch a loopback-only app through documented Docker Compose commands and run the test suite.
- [x] UK tax-year boundaries and England/Northern Ireland 2026/27 standard allowance rules are represented in a versioned data structure with source and as-of date.
- [ ] Inputs can be entered for salary periods, bonus events, RSU GBP taxable-income events, salary sacrifice/net-pay/relief-at-source pensions, benefits, Gift Aid and other income categories.
- [ ] Engine rejects bad/ambiguous inputs and reports unknown or unsupported cases; no silent annualisation, duplicate benefits or hidden FX assumptions.
- [ ] Calculation has a traceable waterfall from taxable gross income through allowed adjustments to ANI; 2026/27 standard Personal Allowance taper and target headroom display correctly.
- [ ] UI makes actual versus forecast clear, shows 6 April–5 April tax-year scope, date allocation, assumptions, and that inputs are not saved.
- [ ] Automated tests cover precision, tax boundaries, benefits renewal, payroll actual overrides, all three pension methods, Gift Aid, other income and allowance boundaries.
- [ ] Final verification issue contains independent worked examples, test results, a limitations list and links to PRs; no unverified tax value is called authoritative.

## Implemented M1.3 primitives

- `TaxYear` and `DateRange` use inclusive date-only boundaries. The rule selector takes a tax-year start year, a UK income-tax jurisdiction and an explicit confirmation of full-year UK residence and standard allowance treatment. Only England and Northern Ireland in 2026/27 select a ruleset. The rules include the source URL, verification date, effective dates and version. The allowance calculation is M1.9.
- `DatedMoney` records an event ID, ISO date, exact GBP decimal amount, source status and note. GBP and percentage inputs use plain decimal strings with a leading digit and up to two and four fractional places respectively. Percentages range from 0 to 100. Explicit null represents an unknown GBP amount. Explicit zero represents a known amount.
- `resolve_events` rejects repeated event IDs, including identical rows. An actual with a separate ID can explicitly link to one supplied forecast ID. Each forecast can have one replacement. The actual takes precedence before year filtering even when its date changes the tax year. Both records appear as evidence, with the breakdown identifying the replacement. Matching dates or amounts alone leave records independent. Replacement of recurring coverage belongs to the relevant compensation issues.
- The resolver returns a coverage status, rule version, warnings, source events and included, excluded or replaced breakdown lines. The source events and lines are ordered by date then ID. An included unknown amount or source status, or unconfirmed coverage, yields an incomplete result. The wire representation uses strings for dates and amounts and a null result value. The resolver selects evidence and has no income aggregate.

## Implemented M1.5 pension and Gift Aid domain

- The Python domain applies valid salary or bonus sacrifice before any applicable net-pay deduction, using the reported employment basis for each method and retaining payroll evidence.
- Dated gross pension, relief-at-source pension and Gift Aid evidence supplies separate deductions for the eventual ANI waterfall. Ordinary employer contributions are recorded separately.
- The [M1.5 domain contract](M1_FINANCIAL_CONTRACT.md#m15-pensions-and-gift-aid-domain) describes eligibility confirmation, date handling, supported pay bases and warnings. The ANI engine and calculator UI follow in M1.9 and M1.10.

## Implemented M1.6 taxable benefits domain

- The Python domain values supported annual taxable forecasts across inclusive renewal dates and replaces only explicitly linked confirmed coverage. Payroll and P11D amounts retain their actual basis. Premiums and employee payments remain source evidence.
- The [M1.6 domain contract](M1_FINANCIAL_CONTRACT.md#m16-taxable-benefit-domain) describes date clipping, payroll reconciliation and limitations.

## Implemented M1.7 manual GBP RSU income domain

- The Python domain resolves dated gross GBP vest income and explicitly linked actual replacements, preserving source evidence and tax-year boundaries.
- Ordinary supported award treatment and charge dates require confirmation. Named payroll component reconciliation prevents duplicate addition. Sold-to-cover information has no effect on gross taxable income.
- The [M1.7 contract](M1_FINANCIAL_CONTRACT.md#m17-manual-gbp-rsu-income-domain) documents inputs and limitations. UI and combined ANI calculations remain planned.

## Financial rules and edge cases

The [M1.1 financial contract](M1_FINANCIAL_CONTRACT.md) defines the implementation rules and fixture expectations for this scope.

### Tax-year and jurisdiction
- Date-only events retain their actual date, no timezone reinterpretation. Tax-year membership is inclusive: **6 April through 5 April**.
- Annualised salary is a **rate**, not money already earned; allocate across in-year effective dates using known taxable payroll amounts or the documented calendar-day forecast. Part-year service and changes must not silently count as 12 full months.
- Bonuses are recorded as individually dated taxable events (forecast/actual). One event must not be counted twice when its status changes.
- Enforce England/Northern Ireland, standard Personal Allowance scope for M1; mark exceptions such as Blind Person's Allowance, multiple jobs with unusual payroll, split-year residence or pension annual allowance taper as unsupported, as appropriate.

### Pension
- Valid **salary sacrifice** reduces taxable salary/bonus from the beginning. Do not also deduct a separate pension contribution from ANI.
- **Net pay** reduces the taxable employment pay figure through payroll. Do not subtract again in ANI adjustments.
- **Relief at source** is recorded as net cash paid and gross contribution separately or grossed-up by a versioned rule; gross amount reduces ANI in the relevant step; no double-count.
- Employer pension contribution is tracked separately and **not** an employee ANI deduction.
- For M1, show contributions and documented rule application, **not** a claim that a contribution is permitted under all pension annual allowance restrictions.

### Benefits
- Entry can be: (a) actual payrolled/P11D taxable GBP amount, or (b) forecast annual taxable benefit value effective over dates where calendar-day apportionment is appropriate. Unknown taxability is not included as zero without warning.
- Renewal values across 1 November must not be incorrectly treated as full-year amounts. Show periods and assumptions.
- If a payrolled benefit is already present in entered taxable payroll income, ask for / capture an explicit inclusion flag and prevent duplicate addition.

### RSU (M1 boundary)
- Entry is `vest_date`, `taxable_income_gbp`, `status`, `source_note` (and optional plain-text label). It is a **gross employment-income inclusion**.
- Any USD value, FX conversion, grant tracking, withholding, tax repayment, share sale, Section 104 pooling, or CGT is **M2**.
- A retained/sold-to-cover percentage does not reduce gross vested employment income.

### Other income and ANI
- Support user-entered **taxable** interest and dividends even if tax on the amounts is reduced by separate allowances; offer gross taxable amount vs already-tax-exempt amount distinctly.
- Start with supported categories: taxable bank interest, taxable dividends, UK trading or property net taxable amounts (manual), Gift Aid and qualifying pension contributions. Flag ambiguous exemptions/deductions.
- Exclude CGT from ANI.
- Calculate: sum in-year taxable income **after** employer payroll reductions, minus valid gross relief-at-source/Gift Aid/other supported ANI deductions, with complete breakdown and no duplicate adjustment.
- Standard Personal Allowance for 2026/27 = **£12,570**; taper above **£100,000** at £1 per £2 excess to minimum 0, then round the remaining allowance up to a whole pound. The **ANI target** is user-entered and distinct from statutory taper threshold.
- A provisional *amount over target* may be displayed as a simple difference; the recommended method/amount of pension sacrifice is M3, not M1.

## Example acceptance scenarios (fictional)

1. Salary £80,000, 2% valid full-year salary sacrifice, no other income → ANI £78,400; pension not subtracted twice.
2. Baseline ANI £95,000 plus £10,000 bonus → ANI £105,000. If £5,500 valid bonus sacrifice was elected → ANI £99,500.
3. Gross £1,000 relief-at-source pension contribution paid as £800 out-of-pocket → ANI reduced by £1,000, subject to eligibility; does not reduce salary field.
4. Employee receives £2,400 annual taxable benefit until 31 October and £3,000 annual benefit starting 1 November → correct period-weighted estimate (method documented), never £3,000 for entire tax year.
5. RSU taxable GBP £4,000 entered on 5 April is in preceding tax year; an otherwise identical vest on 6 April is in following tax year.
6. £1,000 taxable interest plus £500 taxable dividends contribute £1,500 to ANI even if a tax computation might apply savings/dividend allowances.
7. ANI £100,002 → standard Personal Allowance reduced by £1; ANI £125,140 → zero standard Personal Allowance.
8. Enter confirmed payrolled taxable benefit already included in entered income → no duplicate counting, with visible provenance.
9. A user selecting Scotland or entering a year without verified rules sees an unsupported warning rather than a calculated tax result.

## Implementation order

1. **M1.1** — Ratify financial definitions, source/rounding decisions and worked examples.
2. **M1.2** — [Minimal architecture, Docker Compose and test harness](M1_APP_ARCHITECTURE.md).
3. **M1.3** — Versioned UK tax-year configuration and dated input primitives.
4. **M1.4** — Salary periods and bonus event logic.
5. **M1.5** — Pension methods and Gift Aid adjustment contract.
6. **M1.6** — Employer benefits and effective-dated renewal handling.
7. **M1.7** — RSU GBP taxable-income events (no trading or CGT).
8. **M1.8** — Other taxable income and exemptions/unknowns.
9. **M1.9** — ANI, standard Personal Allowance taper, explainable results.
10. **M1.10** — Accessible M1 calculator UI and API integration.
11. **M1.11** — End-to-end independent verification and documentation of supported cases.

The GitHub **M1 tracker issue** contains the canonical live checklist and real issue links.

## Non-goals

CGT, share matching, brokers/Wise integration, tax withholding, full PAYE or NI net take-home, HICBC calculation, personal tax filing, real-time market data, automated FX, accountant-grade tax advice, pension annual allowance optimisation, multiple user accounts, hosting publicly, third-party integrations, database persistence, CSV import, automated optimisation or scenario comparison.

## Official implementation references

- [HMRC adjusted net income](https://www.gov.uk/guidance/adjusted-net-income)
- [HMRC 2026/27 income tax allowances](https://www.gov.uk/government/publications/rates-and-allowances-income-tax/income-tax-rates-and-allowances-current-and-past)
- [HMRC salary sacrifice](https://www.gov.uk/guidance/salary-sacrifice-and-the-effects-on-paye)
- [HMRC pension tax relief](https://www.gov.uk/tax-on-your-private-pension/pension-tax-relief)
- [HMRC benefits reporting](https://www.gov.uk/expenses-and-benefits-medical-treatment)

**Authoritative HMRC text must be reviewed for implementation-specific nuances; these links do not eliminate the need for independently tested rules.**
