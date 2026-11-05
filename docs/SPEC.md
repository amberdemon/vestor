# Vestor — Functional and Financial Rules Specification

**Status:** design proposal, not implemented or tax-verified software  
**Initial jurisdiction:** UK resident employee; English / Northern Irish non-savings income tax bands unless configured otherwise  
**Initial tax year:** 2026/27 (6 April 2026–5 April 2027)  
**Document owner:** product / engineering; review financial rules before code merges  
**Priority:** deterministic, explainable calculations over feature breadth

## 1. Goal and calculation contract

Vestor answers these distinct questions:
1. **Adjusted net income (ANI):** What is the projected ANI for a UK tax year and the shortfall/excess relative to a configured target?
2. **Pension planning:** What gross additional qualifying pension contribution or valid salary sacrifice would reduce ANI to the requested target, subject to the scheme constraints and available compensation?
3. **RSU proceeds:** What was taxable when shares vested, what is potentially taxable when shares are sold, what cash is actually receivable, and what remains owed?
4. **Scenario analysis:** How do different future vesting prices, sale prices, FX rates, benefit renewals and bonus values affect ANI, estimated tax and available cash?

**Never collapse** taxable income, taxable gains, payroll withholding and cash proceeds into a single number. CGT proceeds are **not** employment income and gains are **not** added to ANI merely because shares are sold. Paying employment tax does **not** reduce employment income.

## 2. Inputs and data model

Every editable field carries `source_status` = `actual|forecast`, `source_note`, and (if relevant) effective date. Distinguish a manually entered value from one imported from payroll in future.

### TaxYear
- `start_date`, `end_date`, `tax_residence`, `income_tax_jurisdiction`.
- Versioned income tax rates/bands, Personal Allowance taper, CGT annual exempt amount and rates, employee NI bands/rates, relief rules and validation sources.
- **No silent fallback** to the latest tax year when a year has no verified rule set.

### Employment
- Salary periods: `effective_from`, `effective_to`, annualised amount, pay frequency, salary sacrifice basis, qualifying amount.
- Bonus: `payment_date` / taxable payroll date, gross amount, tentative or confirmed, contribution election deadline, eligible bonus sacrifice.
- Pension: employer and employee funding separately; methods `salary_sacrifice|net_pay|relief_at_source|other`, contribution bases, percentage or amount, effective dates, gross-up where applicable.
- Benefit: category, annual premium or payroll taxable value, taxable status (`yes|no|unknown`), renewal date, payer, employee contributions, effective periods; prefer confirmed payroll taxable values to estimates.
- Other taxable income: interest, dividends, rental and miscellaneous categories, allowable deductions / gift aid as separate explicit inputs. Do not equate zero tax due on an income stream with zero inclusion in ANI.

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

The implementation must follow HMRC's actual definition of adjusted net income rather than a simplified salary-only proxy.

### Tax-year inclusion
- Annual salary must be allocated to actual applicable payroll dates/pay periods; handle salary changes and partial tax years.
- Bonus belongs in the tax year when taxable/received under employment rules; never allocate by vest date if payroll rules require otherwise.
- RSU vest value belongs to the relevant employment income event even when shares were withheld or sold to cover.
- Employer-funded taxable benefits are included at their **taxable benefit value** (payrolled or P11D as appropriate), not mechanically at displayed employer premiums if a different valuation applies.
- For annual premiums changing on renewal, time-apportion only when appropriate to the benefit's taxable valuation method; mark estimates and prefer payroll facts.
- Include applicable other taxable income even if the tax on it is reduced by savings/dividend allowances.
- CGT is separate and excluded from ANI.

### Pension methods (do not double count)
- **Salary sacrifice:** valid contractual reduction decreases taxable salary or eligible bonus before employment income is counted. Do *not* also subtract it as a personal contribution in ANI.
- **Net pay arrangement:** contributions reduce taxable pay through payroll, subject to applicable rules; do not deduct twice.
- **Relief at source:** gross up eligible personal contributions for basic-rate relief and use appropriate ANI adjustment; do not mislabel the net payment as gross.
- **Employer pension contributions** are not automatically employee taxable income or an ANI deduction; maintain a separate annual allowance view.
- Add supported Gift Aid and other permitted adjustments explicitly, never as hidden deductions.

### Core outputs
- `employment_income_gbp`, `other_relevant_income_gbp`, `adjustments_gbp`, `ani_gbp`.
- Personal Allowance taper: for the initial 2026/27 rule set, loss is £1 for each £2 ANI above £100,000, subject to limits; configurable from versioned rules.
- `headroom = target_ani - projected_ani`; can be negative.
- `extra_qualifying_gross_pension_needed = max(0, projected_ani - target_ani + configured_buffer)` *only for a qualifying contribution that reduces ANI pound-for-pound*. Show feasibility against annual allowance, earnings, employer restrictions, bonus amount, deadlines and method.
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
- Estimate the relevant tax-year amount using defined daily/monthly allocation and test boundary semantics; do not use £3,000 for full year. Prefer actual payroll values.

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
- Return `value`, `status` (confirmed/estimated/unsupported), `breakdown`, `warnings`, `source_events` and `rule_version`.
- APIs (when introduced): create/update compensation events, list tax-year summary, evaluate scenario, explain result; validate all inputs server-side.
- Local-only persistence; SQLite migrations, export/import data without secrets, and explicit backup semantics.
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

## 9. Open decisions to resolve before implementing M1

1. Confirm exact target jurisdictions (initially England and Northern Ireland income tax; Scottish treatment later).
2. Choose current HMRC reference URLs, source provenance, and rule-set update/approval process.
3. Define decimal precision, day/month benefit apportionment, HMRC rounding and date-specific exchange-rate acceptance.
4. Confirm minimal UI/backend split for M1; avoid adding a server merely to serve static demo input.
5. Specify payroll date conventions, edge cases for restricted stock, and required pension annual allowance warnings.
6. Clarify what qualifies as 'cash available' when income tax was already withheld but employer tax is owed separately.

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
