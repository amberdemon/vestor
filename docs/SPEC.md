# Vestor — Functional and Financial Rules Specification

**Status:** M1.2 app scaffold, M1.3 tax-year and dated GBP primitives, M1.4 salary and bonus domain, M1.5 pension and Gift Aid domain, M1.6 taxable benefits domain, M1.7 manual GBP RSU income domain, M1.8 other-income domain, and M1.9 combined ANI engine and M1.10 local calculator/API implemented
**Implemented M1 jurisdiction:** full-year UK resident employee, England/Northern Ireland, standard Personal Allowance; other jurisdictions/years are explicitly unsupported
**Initial tax year:** 2026/27 (6 April 2026–5 April 2027)  
**Document owner:** product / engineering; review financial rules before code merges  
**Priority:** deterministic, explainable calculations over feature breadth

Clean-checkout Docker checks, desktop/mobile browser scenarios and 34 independent financial scenarios passed on 9 November 2026. Acceptance is established by the reviewed, passing merge of [release PR #23](https://github.com/amberdemon/vestor/pull/23); the final commit and CI verdict are recorded in [#12](https://github.com/amberdemon/vestor/issues/12). See the [release evidence](M1_RELEASE_VERIFICATION.md).

## 1. Goal and calculation contract

M1 answers question 1. Questions 2–4 describe planned M2/M3 capabilities and are not release outputs:
1. **Adjusted net income (ANI):** What is the projected ANI for a UK tax year and the shortfall/excess relative to a configured target?
2. **Pension planning:** What gross additional qualifying pension contribution or valid salary sacrifice would reduce ANI to the requested target, subject to the scheme constraints and available compensation?
3. **RSU proceeds:** What was taxable when shares vested, what is potentially taxable when shares are sold, what cash is actually receivable, and what remains owed?
4. **Scenario analysis:** How do different future vesting prices, sale prices, FX rates, benefit renewals and bonus values affect ANI, estimated tax and available cash?

**Never collapse** taxable income, taxable gains, payroll withholding and cash proceeds into a single number. CGT proceeds are **not** employment income and gains are **not** added to ANI merely because shares are sold. Paying employment tax does **not** reduce employment income.

## 2. Inputs and data model

Dated inputs carry `source_status` (`actual`, `forecast` or `unknown`), `source_note` and an effective date. An actual or forecast source can still have an unknown value. Distinguish a manually entered value from one imported from payroll in future.

### TaxYear
- `start_date`, `end_date`, `tax_residence`, `income_tax_jurisdiction`.
- M1 versions the standard Personal Allowance taper, basic pension/Gift Aid relief rate and validation sources. Income-tax bands, CGT and NI rates are future scope.
- **No silent fallback** to the latest tax year when a year has no verified rule set.

### Employment
- Salary periods have inclusive effective dates, annual GBP rate, source evidence and optional pay frequency. Dated salary payments separately identify their covered service days, taxable receipt timing, payroll composition and pension reduction basis.
- Bonuses have a stable event ID, payment or confirmed taxable receipt date, entitlement evidence, GBP amount, source status and pension reduction basis. A confirmed record can explicitly link to the forecast it supersedes.
- Pension: employer and employee funding separately; methods `salary_sacrifice|net_pay|relief_at_source|other`, contribution bases, percentage or amount, effective dates, gross-up where applicable.
- Benefit: stable benefit and period IDs, category, inclusive effective periods, taxable status (`yes|no|unknown`), and annual taxable forecast or confirmed payroll/P11D value. Annual premium, payer and employee contributions are separate evidence. Use explicit actual replacement links and named payroll links for amounts already included in entered pay. See the [M1.6 benefit contract](M1_FINANCIAL_CONTRACT.md#m16-taxable-benefit-domain).
- Other income: gross taxable interest/dividends and manually determined nonnegative taxable UK trading/property profits. Explicit exemption reasons and unknown treatment remain separate. Dated receipts or stated assessment-year totals identify covered income streams; overlapping summaries/components block the subtotal. Generic other income is unsupported. Qualifying adjustments remain solely in the M1.5 contract. See the [M1.8 contract](M1_FINANCIAL_CONTRACT.md#m18-other-income-domain).

### RSU and transactions
- Vest: identifier, date, grant reference, shares acquired, gross vest FMV per share / total in USD, **confirmed GBP taxable payroll amount** when available, event-date FX rate/source, scheme notes.
- Employee NIC / income tax on vest: liability estimate, actual payroll withholding or separate repayment, currency and settlement status.
- Sale: trade date, shares and security/class, price, gross proceeds, fee detail and fee eligibility, date-specific FX conversion, settlement date, broker account, cash received.
- Sell-to-cover: record as actual share disposal(s) and withholding/remittance separately; shares sold, price, fees and timing can differ from vest price.
- Holdings: same share class and beneficial capacity, acquisition and disposal history, validated opening Section 104 pool or imported historical lots.
- Transfer: Wise/broker FX execution, fee, conversion rate and date; transfer cost is a cash movement, not automatically CGT-allowable.
- Rate: date, GBP per 1 USD, source, status and purpose. **No reuse of a single FX rate for unrelated dates by default.**

### Scenario
- Named scenario, baseline actual events, future assumptions/overrides, tax year, rate-set version, calculated timestamp and warnings.
- Scenario overrides must not mutate source actuals.

M1 implementation and acceptance details: [M1 Compensation & ANI milestone](M1_COMPENSATION_ANI.md) · [GitHub tracker #1](https://github.com/amberdemon/vestor/issues/1).

## 3. ANI engine — M1

The [M1.1 financial contract](M1_FINANCIAL_CONTRACT.md) defines the supported 2026/27 rules, source verification, planning conventions and worked regression fixtures.

### Tax-year inclusion
- Use actual taxable payroll dates and amounts when known. Where only an annual rate and effective dates are known, use the documented calendar-day forecast.
- Allocate ordinary cash bonuses to the taxable receipt date under employment rules, including earlier entitlement where applicable.
- RSU vest value belongs to the relevant employment income event even when shares were withheld or sold to cover.
- Employer-funded taxable benefits are included at their **taxable benefit value** (payrolled or P11D as appropriate), not mechanically at displayed employer premiums if a different valuation applies.
- For annual taxable values changing on renewal, time-apportion only when appropriate to the benefit's taxable valuation method. Label estimates and prefer payroll facts.
- Include applicable other taxable income even if the tax on it is reduced by savings/dividend allowances.
- M1.7 accepts manual gross GBP vest events with confirmed ordinary award treatment and charge dates. Explicit actual links supersede forecasts before tax-year filtering. Named payroll components reconcile the included gross amount in both directions; unresolved inclusion suppresses the RSU subtotal. Sold-to-cover percentages are informational only. See the [M1.7 contract](M1_FINANCIAL_CONTRACT.md#m17-manual-gbp-rsu-income-domain).
- CGT is separate and excluded from ANI.

### Pension methods (do not double count)
- **Salary sacrifice:** valid contractual reduction decreases taxable salary or eligible bonus before employment income is counted. Do *not* also subtract it as a personal contribution in ANI.
- **Net pay arrangement:** contributions reduce taxable pay through payroll, subject to applicable rules; do not deduct twice.
- **Relief at source:** gross up eligible personal contributions for basic-rate relief and use appropriate ANI adjustment; do not mislabel the net payment as gross.
- **Ordinary employer pension contributions** are funding evidence, not an employee ANI deduction. An annual allowance view is future scope.
- M1.5 applies payroll reductions to linked employment lines using an explicit before/after basis per method and the eligible pay base. Effective-dated salary sacrifice schedules use the calendar-day convention. Dated payroll reductions use the known or expected payroll evidence.
- Eligible gross pension paid without prior relief, relief-at-source pension, and qualifying cash Gift Aid produce separate dated deductions. Ordinary employer contributions remain visible as funding evidence. See the [M1.5 domain contract](M1_FINANCIAL_CONTRACT.md#m15-pensions-and-gift-aid-domain) for supported inputs and remaining constraints.

### Core outputs
- `employment_income_gbp`, `other_relevant_income_gbp`, `adjustments_gbp`, `ani_gbp`.
- Personal Allowance taper: for the initial 2026/27 rule set, subtract half the ANI excess above £100,000 from £12,570, floor at zero and round the remaining allowance up to a whole pound.
- `headroom = target_ani - projected_ani`; can be negative.
- **Planned M3, not an M1 output:** `extra_qualifying_gross_pension_needed = max(0, projected_ani - target_ani + configured_buffer)` *only for a qualifying contribution that reduces ANI pound-for-pound*. Show feasibility against annual allowance, earnings, employer restrictions, bonus amount, deadlines and method.
- Tax bands, income tax and NI estimates are a later verified capability, **not** inferred from one effective rate when projected income crosses the taper.
- Preserve decimal precision, document final rounding and tax-year reporting rules.

## 4. RSU taxation and share matching — M2

### Vesting
- In the ordinary UK employee RSU case, gross taxable employment benefit is the **full market value of shares delivered at vest**, subject to award scheme and payroll facts. A 45% sell-to-cover withholding does **not** make 55% of vest value taxable.
- Prefer the company's reported GBP payroll taxable amount. If unavailable, compute an indicative GBP value from USD vest FMV and date-specific rate, prominently labelled estimated.
- Validate `shares × per-share FMV = total FMV` within an explicit tolerance; discrepancy triggers investigation rather than silently preferring one number.
- A payroll tax repayment is a settlement of tax already due; do not deduct it from ANI or treat it as share acquisition cost without a justified rule.

### Share disposals
- Gain/loss must be calculated in **GBP**, converting allowable acquisition cost at acquisition-date rate and disposal proceeds at disposal-date rate.
- Document eligible incidental disposal/acquisition costs; distinguish broker sale fees from remittance FX fees, which are not automatically allowable.
- Apply share identification in proper chronological ordering for same class/capacity: **same-day acquisitions**, acquisitions within the **following 30 calendar days** (subject to conditions), then the **Section 104 pool**.
- Handle partial quantities, multiple sales and acquisitions, sale-before-vest and same-day sell-to-cover. **Do not assume** that all later acquired shares are available for the earlier disposal: same-day disposals can absorb same-day acquisitions first.
- The Section 104 pool tracks quantity and GBP allowable cost. Its updates need deterministic tests.
- Resolve matching across tax-year boundaries and disposal dates; identify losses and potentially deferred or restricted loss rules where relevant. Flag unsupported share classes, corporate actions, jointly held shares, options and nonstandard RSUs.
- Treat the 30-day rule as a matching rule, **not an exemption or penalty**.
- Tax-year CGT estimates require other gains/losses and the annual exempt amount, rate bands, and correct interaction with taxable income. Do not present a reliable CGT bill without these inputs; output a bounded or qualified estimate if incomplete.

### Withholding and cash
- Keep distinct:
  1. gross vest value (employment-income basis);
  2. withholding / payroll tax and NI paid or owed;
  3. gross share disposal proceeds;
  4. broker transaction fees;
  5. actual cash received;
  6. transfers / conversion fees;
  7. estimated/unpaid CGT and any later income tax reconciliation;
  8. **spendable cash** net of all remaining obligations.
- Do not subtract withholding twice when computing the proceeds from retained shares.
- Prevent tax withheld as shares from being misrepresented as an ordinary share-sale fee.

## 5. Scenarios and pension optimiser — M3

Inputs: projected share/FX prices per event, sale timing, bonuses, benefits, savings interest, pension amounts/percentages, target ANI and buffer. Optimiser should:
- calculate gross qualifying reduction required (not presume bonus sacrifice is always available);
- split eligible March bonus sacrifice versus monthly sacrifice versus relief-at-source personal contributions;
- respect employer election deadlines and employer-specific rules as provided by the user;
- provide **after-tax cash foregone** and additional pension invested, with clear employee NI differences;
- explicitly treat pension annual allowance, taper and carry-forward as eligibility checks / warning flags unless fully supported and verified;
- compare net spendable cash and post-sacrifice ANI with the *same* tax-year assumptions;
- avoid stock-price predictions and investment advice.

## 6. Worked examples / required regression fixtures

**These are fictional examples, not user financial data.** All money is GBP unless explicitly marked USD; exact statutory tax calculations are to be verified against tax-year rules.

### F1 — Salary and salary sacrifice
- Annual salary £80,000; valid 2% base salary sacrifice for full year; no other inputs.
- Taxable salary / ANI component = £78,400. Do not deduct £1,600 a second time.

### F2 — Bonus sacrifice
- Baseline ANI excluding bonus £95,000; gross bonus £10,000.
- Without sacrifice ANI = £105,000; with valid £5,500 bonus sacrifice ANI = £99,500.
- Pension amount is £5,500, and remaining **gross taxable** bonus is £4,500 (net bonus requires tax/NI engine).

### F3 — Renewing benefit
- Confirmed annual taxable benefit cost £2,400 from 6 April through 31 October, £3,000 from 1 November to 5 April, where pro-rating is valid.
- Use calendar-day allocation where appropriate, producing £2,656.44 in 2026/27. Prefer actual payroll values for confirmed coverage.

### F4 — Vest versus sale
- 100 RSUs vest with taxable total $1,000 at USD/GBP 0.80; original acquisition GBP basis £800.
- They later sell for total $1,200 at USD/GBP 0.75 with £10 eligible broker selling costs.
- Estimated GBP gain = (£900 − £10) − £800 = **£90**. RSU employment income remains **£800**, separate from gain; payroll withholding does not reduce either income figure.

### F5 — Same-day sell-to-cover and 30-day matching
- 100 existing shares (pool basis £500) sold on 20 November.
- On 15 December, 40 shares acquired at vest and 20 of those disposed on the same day for withholding.
- Validate same-day match of 20 December acquisitions with 20 December disposals before matching eligible remainder to November sale; derive quantity and GBP basis under documented chronological matching algorithm, not a naive 'all 40 new shares' shortcut.

### F6 — FX movement without USD stock gain
- Acquire 10 shares at $10 with GBP/USD conversion 0.70 GBP per USD; sell at $10 with rate 0.80.
- Even without USD share-price movement, GBP gain before fees = £10.

### F7 — Pension methods
- Compare £1,000 valid bonus salary sacrifice vs £800 personal contribution under relief-at-source grossed to £1,000.
- Both can reduce ANI by £1,000 under applicable conditions, but salary sacrifice can additionally change NI; no duplicate tax relief.

### F8 — Personal Allowance taper
- ANI £99,999, £100,000, £100,002, £125,140 for an eligible individual in a rule set with a £12,570 standard Personal Allowance and £100k taper threshold.
- Test boundary, fractional pound rounding and allowance floor.

### F9 — Missing confidence
- Missing RSU vest-date FX or taxable payroll GBP value must produce a missing-data warning, not a confident number.
- Unsupported residence/tax treatment must not generate an unqualified personalised tax recommendation.

### F10 — Year boundaries
- Bonus paid on 31 March and next on 6 April: fall in different tax years.
- RSU vest and sale on different tax years remain separate dated events.

## 7. Architecture, interfaces and security

- Calculations are pure functions over immutable input DTOs and a versioned rules object, with `Decimal` or exact minor-unit/rational representations; no binary float for money or FX.
- Return `value`, `status` (confirmed/estimated/incomplete/unsupported), `breakdown`, `warnings`, `source_events` and `rule_version`.
- M1 exposes a strict transient calculation API and health check; all inputs are validated server-side. Persisted event CRUD and scenario APIs remain planned.
- M1 stores no financial records. Local SQLite persistence, migrations, export/import and explicit backup semantics remain M4 scope.
- No telemetry or remote stock/FX calls necessary. Third-party price integrations are future opt-in features.
- Deployment via Docker Compose bound to loopback by default. No authentication is acceptable only for local-only deployment.
- Tax records are sensitive: anonymised test fixtures, no real employee/payroll data in public repository, logs or screenshots.

## 8. Definition of done / verification

Every behaviour-changing issue:
- adds fixture-based deterministic unit tests including relevant edge cases;
- links its financial rule to this document and a source of authority;
- documents rounding/FX assumptions and unsupported cases;
- keeps output explainable;
- includes an independent worked-example review for financial changes;
- does not silently expand later milestone scope.

A milestone must finish with an integration/verification issue, manual scenarios and a signed-off limitations list.

The [M1 release verification report](M1_RELEASE_VERIFICATION.md) maps acceptance to tests, independent arithmetic, release checks and explicit unsupported cases. M2-only F4–F6 remain future regression fixtures.

## 9. Implementation decisions

The [M1.1 financial contract](M1_FINANCIAL_CONTRACT.md) records the financial decisions. The [M1.2 architecture decision](M1_APP_ARCHITECTURE.md) records the shipped local shell, health endpoint and test pipeline. The [M1.3 domain primitives](M1_COMPENSATION_ANI.md#implemented-m13-primitives) implement inclusive year membership, scope selection and dated GBP event evidence. Date-specific FX and cash availability rules belong to M2 and M3 respectively.

## 10. Authoritative references for implementation review

Check official current tax-year guidance before coding or releasing changes:
- HMRC [Adjusted net income](https://www.gov.uk/guidance/adjusted-net-income)
- HMRC [Tax on your private pension](https://www.gov.uk/tax-on-your-private-pension/pension-tax-relief)
- HMRC [Salary sacrifice for employers](https://www.gov.uk/guidance/salary-sacrifice-and-the-effects-on-paye)
- HMRC [Capital Gains Tax on shares](https://www.gov.uk/tax-sell-shares)
- HMRC [HS284 shares and Capital Gains Tax](https://www.gov.uk/government/publications/shares-and-capital-gains-tax-hs284-self-assessment-helpsheet)
- HMRC [Expenses and benefits: medical or dental treatment and insurance](https://www.gov.uk/expenses-and-benefits-medical-treatment)
- HMRC [Income Tax rates and allowances](https://www.gov.uk/income-tax-rates)

These are reference entry points, **not** confirmation that every described edge case is currently verified. Implementers must verify the applicable tax year and relevant HMRC manual or legislation section.

## Implemented M1.9 ANI engine

`vestor_domain.ani.calculate_ani(AniInputs(...))` is the pure entry point for raw typed component evidence. It selects verified rules and invokes employment, pension, benefits, RSU and other-income domains before producing a source-linked waterfall. Coverage or explicit absence is required for every category. The input evidence, all component dates, replacement decisions, warnings and rules metadata remain inspectable; M1.10 supplies the strict API and local UI that consume the same result.

The waterfall reports salary and bonus after payroll reductions, gross RSUs, taxable benefits, other taxable income, qualifying gross pension at the net-income step, then gross Gift Aid and relief-at-source deductions at the ANI step. Already included payroll components contribute once. Source IDs must be unique across categories; component references are links to the original evidence. The remaining standard Personal Allowance is rounded up to whole pounds from **unrounded ANI**. Signed headroom is optional target minus ANI; it is not a pension recommendation.

Results use exact rational amounts and a deterministic `to_wire()` representation containing exact numerator/denominator strings and half-up GBP displays. The `rounding_discrepancy_gbp` field is displayed ANI minus the sum of independently rounded signed waterfall rows; a nonzero difference must be disclosed by consumers. It is informational and does not change the financial result status. Incomplete/unsupported results suppress ANI, allowance and headroom while retaining known component evidence. No full income-tax, NI, CGT, cash or optimisation result is provided. See the [financial contract](M1_FINANCIAL_CONTRACT.md#m19-combined-ani-domain).

## Implemented M1.10 local calculator

The React calculator now exposes repeatable M1 record forms for effective-dated salary, dated payroll/component reconciliation, bonus, salary-sacrifice/net-pay reductions, personal pensions and Gift Aid, benefits/renewals, manual GBP RSU vest income and supported other income. Actual/forecast changes preserve source identity; separately linked actual records retain replaced forecasts. All categories require explicit coverage/absence confirmation. Native labelled date/value controls, keyboard operation, error summaries, status announcements and responsive layout support desktop and mobile use.

A thin strict JSON API reconstructs the existing domain inputs and calls `calculate_ani`; React performs no financial arithmetic. GBP/percentage inputs remain decimal strings, date-only values retain their dates and booleans are never coerced. Results preserve domain status, source-linked expandable waterfall, dated evidence, rule version, unrounded calculation/rounding disclosures, target headroom, £100,000 threshold and standard Personal Allowance. Material unknown/unsupported cases show warnings without final numbers. Input and failed-request values are not logged or echoed in errors.

Inputs are **not saved — data lost on refresh**. Editing clears stale results; service failure preserves entries. No persistence, tax/NI bill, FX, CGT or pension optimisation is added. Automated route, input/label and real-browser desktop/mobile tests cover the supported integration. The [release verification report](M1_RELEASE_VERIFICATION.md) records supported limitations and acceptance through [release PR #23](https://github.com/amberdemon/vestor/pull/23). See [calculator usage and checks](../README.md#using-the-m1-calculator).
