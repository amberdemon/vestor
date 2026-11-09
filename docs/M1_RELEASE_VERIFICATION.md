# M1 release verification

[Verification issue #12](https://github.com/amberdemon/vestor/issues/12) · [M1 tracker #1](https://github.com/amberdemon/vestor/issues/1) · [Financial contract](M1_FINANCIAL_CONTRACT.md)

**Gate status: release execution and independent financial verification passed on 9 November 2026; final PR-head review, CI and merge remain required.** This report records the implemented scope and observed acceptance evidence. Close #12 and then tracker #1 only after the final release PR is accepted/merged and its review/CI evidence is linked in #12.

The release candidate is main commit `80635ab`, containing implementation issues #2–#11. Release verification adds documentation and a reproducible offline smoke check/CI step to that candidate; financial application behavior is unchanged. All examples, browser inputs and screenshots are synthetic.

## Acceptance evidence

The evidence paths below map acceptance to the clean-checkout release runs and independent arithmetic recorded in the next sections. Final release PR-head review/CI/merge remain separate gates.

| M1 acceptance item | Evidence | Release gate |
| --- | --- | --- |
| Clean local startup, loopback publishing and offline core | `Dockerfile`, `compose.yaml`, `.github/workflows/checks.yaml`; clean-checkout startup/health/port/disconnected checks below | PASS: startup, binding and disconnected runtime |
| Versioned 2026/27 England/Northern Ireland rules | `backend/tests/test_tax_year.py`; rule version, source, verification date, inclusive boundaries and no fallback | PASS: 322 tests and strict mypy |
| All supported input categories and explicit absence | `backend/tests/test_api.py::test_all_nested_domain_records_cross_the_api_without_reinterpretation`; `frontend/src/App.test.tsx`; mixed browser scenario | PASS: 13 frontend tests, types and 10 browser scenarios |
| Validation, missing/unsupported inputs, no duplicate benefits | API strict-input tests; employment/benefit/RSU/other-income reconciliation tests; unknown-benefit/Scotland browser scenario | PASS: backend/frontend/browser checks |
| Traceable ANI, allowance and target | `backend/tests/test_ani.py`; F1/F2/mixed browser assertions; expandable source/rule evidence | PASS: domain/browser checks and 34 independent scenarios |
| Actual/forecast, dates, assumptions and unsaved warning | `frontend/e2e/calculator.spec.ts`; F1 source expansion/refresh/privacy and mixed explicit forecast replacement | PASS: desktop/mobile browser scenarios |
| Precision, renewals, payroll, pension methods and boundaries | Domain test modules for employment, pensions, benefits, RSUs, other income and ANI | PASS: 322 tests and strict mypy |
| Independent worked examples, PRs and limitations | Independent verification entry below, implementation table and supported limits | PASS: 34/34; no financial discrepancy |

## Observed release checks

Checks ran from a clean checkout of `80635ab27f6544ee70af43412b702ac5840aba51` on 9 November 2026. Docker used Python 3.14.6 and Node 24.18.0. The offline smoke script/CI step was then verified against that built runtime. Public-safe results follow; ignored local logs and generated reports are not committed.

| Check | Command / method | Observed result |
| --- | --- | --- |
| Backend / contracts / types | `docker build --target backend-checks .` (dependency check, import isolation, full pytest and strict mypy) | PASS: 322 pytest cases; mypy clean across 13 source files; dependency/import checks pass |
| Frontend / types | `docker build --target frontend-checks .` (TypeScript and Vitest) | PASS: TypeScript and 13 Vitest tests |
| Production build and startup | `docker compose up --build -d`; fetch `/` and `/api/health` | PASS: production build, Vestor HTML and health `{ "status": "ok" }` |
| Host binding | `docker compose port app 8000`, inspect published host address | PASS: `127.0.0.1:8000` |
| Offline core after installation | Runtime image with `--network none`, mounted `backend/tests/offline_smoke.py`; command below | PASS: health, HTML, bundled JS/CSS and F1 calculation with no container external network |
| Pinned Linux browsers | CI-equivalent Node `24.18.0-bookworm-slim`, package-pinned Playwright `1.56.1`, Chromium build `1194`, desktop and iPhone 13 viewport projects | PASS: 10/10 in 16.5 seconds |
| Independent arithmetic | Separate integer/Fraction expectations and independently constructed inputs compared with public domain and exact serialization | PASS: 34/34, no discrepancies; complete matrix below |
| Final candidate review / CI | Exact final PR head reviewed independently; all required CI checks pass | PENDING |

After building the runtime with Compose, reproduce the disconnected runtime check from the repository root:

```sh
docker run --rm --network none --read-only \
  -v "$PWD/backend/tests/offline_smoke.py:/offline_smoke.py:ro" \
  "$(docker compose images -q app)" python /offline_smoke.py
```

Observed output: `PASS disconnected runtime health, HTML, all bundled JS/CSS assets, and synthetic F1 API calculation.` The script starts the local server inside the isolated container and requests its loopback address, fetching bundled assets and asserting ANI £78,400, allowance £12,570 and headroom £21,600. This proves the built runtime serves the calculator and calculates without external connectivity. The browser suite separately proves the UI flow against the same financial application code. Image/dependency installation remains an online prerequisite.

The pinned Linux browser command matches CI (with Compose already running):

```sh
docker run --rm --network host -e CI=1 \
  -v "$PWD/frontend:/app" -w /app node:24.18.0-bookworm-slim \
  sh -c 'npm ci && npm exec -- playwright install --with-deps chromium && npm run e2e'
```

### UI, accessibility and privacy audit

Source review covers native labelled controls, fieldsets/legends, keyboard-focusable add/remove buttons, visible focus styles, `aria-invalid`/linked error descriptions, an alert error summary with focusable field/section targets, polite calculation status and native expandable evidence. The browser suite checks Enter-to-calculate, working error-summary focus, stale-result removal, unsupported output suppression and refresh. The mixed scenario asserts no horizontal overflow in both configured viewports.

Prior #11 screenshots were visually inspected for readable desktop/mobile F1 and mixed results. F1 shows ANI £78,400, standard allowance £12,570 and desktop headroom £21,600; the mixed scenario shows ANI £85,156.44. Mobile totals stack vertically and rule text wraps. These are sampled result views, not a full screen-reader or WCAG conformance audit. The clean-checkout pinned-browser rerun passed all ten desktop/mobile cases; the final release CI artifact link will be attached in #12.

Prior browser evidence: [PR #22](https://github.com/amberdemon/vestor/pull/22), [CI run 42581770627](https://github.com/amberdemon/vestor/actions/runs/42581770627). Final release screenshot/report artifact: to be linked with the final PR-head CI result in [#12](https://github.com/amberdemon/vestor/issues/12).

Privacy review: `frontend/src/api.ts` sends one same-origin calculation request, with no stock/FX/analytics calls. Financial inputs live in React memory; no database or browser-storage writes are implemented. The F1 browser test observes no cross-origin requests, verifies empty local/session storage and confirms refresh discards the result. Opening an official source link is an explicit external navigation, not a background data feed.

The runtime disables access logs; the API replaces FastAPI validation output and maps domain errors without returning rejected values or source identities. API and frontend error tests cover these paths. This checks application behavior, not host/browser security or every possible infrastructure log. `.gitignore` excludes `data/`, environment files, databases, browser reports and screenshots. The tests and inspected screenshots contain fictional values. No personal financial records are needed for release evidence.

## Independent arithmetic verification

An independent reviewer verified **34/34 synthetic scenarios** on 9 November 2026, with no financial discrepancy, against application commit `80635ab27f6544ee70af43412b702ac5840aba51` and rule version `uk-eng-ni-2026-27-v1`. The tracked checkout remained clean. The verification ran in Python 3.14.6 inside a read-only container with `--network none` and read-only source/script mounts.

Inputs were independently constructed using public domain classes and `calculate_ani`, without importing test fixtures/helpers, rule constants, expected values or formatting helpers. Expected arithmetic used integers and `fractions.Fraction`; Decimal was used only to construct application inputs. Inclusive days came from the standard date library. Inside the taper band the separate oracle used `12570 - floor((ANI - 100000)/2)`, with explicit below-threshold/zero-floor branches; penny display used integer quotient/remainder half-up. Every scenario checked exact ANI, allowance, signed headroom, status and exact serialized values, with selected checks on waterfall rows, net income and retained/replaced evidence. This independently verifies the numerical domain; API equivalence and real UI flow are covered by the separate canonical tests and browser runs above.

All amounts GBP. Expected and actual are both shown even when equal. Suppressed means no final numeric output. Except where changed explicitly, target is 100000 and all category coverage is confirmed. Annual-rate salary cases remain estimated, including where the supplied rate is known; confirmed dated payroll can be confirmed.

| Scenario | Independent working | ANI expected / actual | PA expected / actual | Headroom expected / actual | Status expected / actual | Result |
| --- | --- | --- | --- | --- | --- | --- |
| F1 salary sacrifice | 80000 × 98/100 = 78400 | 78400.00 / 78400.00 | 12570.00 / 12570.00 | 21600.00 / 21600.00 | estimated / estimated | PASS |
| F2a bonus | 95000 + 10000 = 105000 | 105000.00 / 105000.00 | 10070.00 / 10070.00 | -5000.00 / -5000.00 | estimated / estimated | PASS |
| F2b sacrificed bonus | 95000 + 10000 − 5500 = 99500 | 99500.00 / 99500.00 | 12570.00 / 12570.00 | 500.00 / 500.00 | estimated / estimated | PASS |
| F3 benefit renewal | 80000 + (2400 × 209 + 3000 × 156)/365 = 6033920/73 | 82656.44 / 82656.44 | 12570.00 / 12570.00 | 17343.56 / 17343.56 | estimated / estimated | PASS |
| F7a full bonus sacrifice | 100000 + 1000 − 1000 = 100000 | 100000.00 / 100000.00 | 12570.00 / 12570.00 | 0.00 / 0.00 | estimated / estimated | PASS |
| F7b relief at source | 100000 + 1000 − 800 × 5/4 = 100000 | 100000.00 / 100000.00 | 12570.00 / 12570.00 | 0.00 / 0.00 | estimated / estimated | PASS |
| F7c net pay already reflected | 101000 − 1000 already reflected in 100000 payroll; no second deduction | 100000.00 / 100000.00 | 12570.00 / 12570.00 | 0.00 / 0.00 | confirmed / confirmed | PASS |
| Net pay applied to gross | 101000 gross payroll − 1000 net-pay contribution = 100000 | 100000.00 / 100000.00 | 12570.00 / 12570.00 | 0.00 / 0.00 | confirmed / confirmed | PASS |
| F8a allowance boundary | ANI 99999; statutory PA = 12570 | 99999.00 / 99999.00 | 12570.00 / 12570.00 | 1.00 / 1.00 | estimated / estimated | PASS |
| F8b allowance boundary | ANI 100000; statutory PA = 12570 | 100000.00 / 100000.00 | 12570.00 / 12570.00 | 0.00 / 0.00 | estimated / estimated | PASS |
| F8c allowance boundary | ANI 100001.99; statutory PA = 12570 | 100001.99 / 100001.99 | 12570.00 / 12570.00 | -1.99 / -1.99 | estimated / estimated | PASS |
| F8d allowance boundary | ANI 100002; statutory PA = 12569 | 100002.00 / 100002.00 | 12569.00 / 12569.00 | -2.00 / -2.00 | estimated / estimated | PASS |
| F8e allowance boundary | ANI 125140; statutory PA = 0 | 125140.00 / 125140.00 | 0.00 / 0.00 | -25140.00 / -25140.00 | estimated / estimated | PASS |
| F8f allowance boundary | ANI 125141; statutory PA = 0 | 125141.00 / 125141.00 | 0.00 / 0.00 | -25141.00 / -25141.00 | estimated / estimated | PASS |
| F9a missing RSU GBP | Missing material vest GBP must suppress ANI/allowance/headroom | suppressed / suppressed | suppressed / suppressed | suppressed / suppressed | incomplete / incomplete | PASS |
| F9b Scotland | No supported jurisdiction rule; all final outputs suppressed | suppressed / suppressed | suppressed / suppressed | suppressed / suppressed | unsupported / unsupported | PASS |
| F9c premium is not taxable value | Premium only, unknown taxability; final outputs suppressed | suppressed / suppressed | suppressed / suppressed | suppressed / suppressed | incomplete / incomplete | PASS |
| F10 bonus tax-year boundaries | 80000 + 3000 on 6 Apr + 500 on 5 Apr = 83500; adjacent-year 6000 excluded | 83500.00 / 83500.00 | 12570.00 / 12570.00 | 16500.00 / 16500.00 | estimated / estimated | PASS |
| RSU 5/6 April and sell-to-cover | 80000 + full 4000 in-year vest = 84000; 45% sale does not reduce gross income | 84000.00 / 84000.00 | 12570.00 / 12570.00 | 16000.00 / 16000.00 | estimated / estimated | PASS |
| Other income versus ISA | 80000 + 1000 taxable interest + 500 dividends + 0 ISA = 81500 | 81500.00 / 81500.00 | 12570.00 / 12570.00 | 18500.00 / 18500.00 | estimated / estimated | PASS |
| Gross pension Gift Aid employer | 101000 − 500 gross pension = 100500 net income; − 800 × 5/4 = 99500 ANI; employer 9000 excluded | 99500.00 / 99500.00 | 12570.00 / 12570.00 | 500.00 / 500.00 | estimated / estimated | PASS |
| Salary change on 1 November | 73000 × 209/365 + 91250 × 156/365 = 80800 | 80800.00 / 80800.00 | 12570.00 / 12570.00 | 19200.00 / 19200.00 | estimated / estimated | PASS |
| Part-year employment | 0 × 209/365 + 73000 × 156/365 = 31200 | 31200.00 / 31200.00 | 12570.00 / 12570.00 | 68800.00 / 68800.00 | estimated / estimated | PASS |
| Contribution effective date boundary | 101000 − 800 × 5/4 = 100000; later provider credit does not move effective 5 April payment | 100000.00 / 100000.00 | 12570.00 / 12570.00 | 0.00 / 0.00 | estimated / estimated | PASS |
| Custom target positive headroom | 110000 target − 105000 ANI = +5000; statutory PA remains 10070 | 105000.00 / 105000.00 | 10070.00 / 10070.00 | 5000.00 / 5000.00 | estimated / estimated | PASS |
| Custom target negative headroom | 90000 target − 105000 ANI = −15000; statutory PA remains 10070 | 105000.00 / 105000.00 | 10070.00 / 10070.00 | -15000.00 / -15000.00 | estimated / estimated | PASS |
| Absent optional target | ANI 105000 and PA 10070 retained; headroom absent | 105000.00 / 105000.00 | 10070.00 / 10070.00 | suppressed / suppressed | estimated / estimated | PASS |
| Unrounded taper before display | 36500728.50/365 = 73001457/730 = 100001.995890…; display 100002.00 but PA 12570 | 100002.00 / 100002.00 | 12570.00 / 12570.00 | -2.00 / -2.00 | estimated / estimated | PASS |
| Signed ANI no invented floor | Explicitly qualifying gross pension 500 against income 0 produces signed ANI −500; PA 12570 | -500.00 / -500.00 | 12570.00 / 12570.00 | 100500.00 / 100500.00 | estimated / estimated | PASS |
| Missing category confirmation | Unknown RSU coverage cannot silently become zero | suppressed / suppressed | suppressed / suppressed | suppressed / suppressed | incomplete / incomplete | PASS |
| Unsupported tax year | No fallback from 2025 to verified 2026 rules | suppressed / suppressed | suppressed / suppressed | suppressed / suppressed | unsupported / unsupported | PASS |
| Unsupported beats incomplete | Unsupported award plus missing GBP suppresses final figures as unsupported | suppressed / suppressed | suppressed / suppressed | suppressed / suppressed | unsupported / unsupported | PASS |
| Payroll bonus benefit RSU actual override | 102000 payroll − 12000 bonus − 8000 vest − 2000 benefit = 80000 salary; adding isolated components once restores 102000 | 102000.00 / 102000.00 | 11570.00 / 11570.00 | -2000.00 / -2000.00 | confirmed / confirmed | PASS |
| Actual vest correction moves tax year | 80000 salary; forecast replaced before filtering; corrected actual is next-year, so neither vest contributes | 80000.00 / 80000.00 | 12570.00 / 12570.00 | 20000.00 / 20000.00 | estimated / estimated | PASS |

Nonterminating exact expectations also matched: benefit-renewal ANI `6033920/73`; unrounded taper ANI `73001457/730`. The latter displays £100,002.00 while retaining the correct £12,570 allowance because its exact value is below £100,002. Gross pension/Gift Aid scenario independently checked £100,500 net income before £1,000 grossed Gift Aid. Payroll actual replacement independently checked salary £80,000, bonus £12,000, RSUs £8,000, benefits £2,000 and total £102,000, with original forecasts retained as replaced evidence.

The signed-ANI arithmetic scenario deliberately supplies an explicit eligibility confirmation to exercise the documented arithmetic contract; it does not establish pension eligibility for a person with no earnings. Eligibility, annual allowances and contribution limits remain external confirmations. F4/F5/F6 concern M2 FX/disposal/share matching and are excluded from this M1 verification rather than represented as shipped.

## Supported cases and limitations

- **Jurisdiction/year:** only 6 April 2026–5 April 2027, full-year UK residence, England/Northern Ireland and standard Personal Allowance treatment. Part-year employment is supported with explicit zero-rate coverage for unpaid/out-of-employment days. Scotland, Wales, other years, nonstandard allowances, directors' special receipt rules, split-year/cross-border and nonresident cases are unsupported.
- **Salary and bonus:** inclusive effective-dated annual salary forecasts use calendar days divided by days in the selected tax year. Actual dated payroll replaces only explicitly linked service coverage; taxable receipt can differ from service dates. Earlier entitlement/payment-on-account matters. Uncertain material timing blocks totals; annual forecasts do not resolve payroll timing at 5/6 April.
- **Pensions/Gift Aid:** valid prospective salary/bonus sacrifice reduces employment pay once. Net pay uses dated deductions and the stated before/after pay basis; salary-rate net-pay forecasts are not supported. A net-pay deduction and its linked taxable receipt in different tax years are unsupported. Already reflected reductions apply zero again. Eligible gross pension without prior relief, relief-at-source and Gift Aid occupy their distinct HMRC steps. Net-only eligible RAS/Gift Aid grosses up at 20%; ordinary employer funding is evidence only. Eligibility, earnings, minimum wage, annual allowance/taper/carry-forward, scheme restrictions and sufficient Gift Aid tax are not independently determined by the app.
- **Benefits:** the user supplies a resolved taxable value, or confirms that daily apportionment of an annual taxable value is appropriate. Premiums/employee payments alone do not establish taxability. Actuals require confirmed in-year coverage; actual values crossing a tax-year boundary are not automatically prorated. Named payroll component links prevent adding an included benefit twice. Product-specific valuation and optional remuneration rules remain outside M1.
- **RSUs:** externally determined gross taxable GBP employment income and supported charge date only. Confirm ordinary supported award treatment and payroll inclusion. Sold-to-cover percentages never reduce gross income. No securities valuation, USD/FX conversion, withholding, share quantities, disposal ledger, share matching or CGT is calculated.
- **Other income:** gross UK taxable interest/dividends before nil-rate allowances; externally determined nonnegative net taxable UK trading/property profits allocated to a stated assessment year; explicitly supported exemptions retain a reason. Covered stream identities guard overlapping annual totals/components but cannot discover duplicates deliberately given unrelated identities. Negative profits/loss relief, foreign/trust/generic other income and unresolved allocation are unsupported.
- **Evidence/confidence:** every category requires coverage or explicit absence. Blank/null is unknown; zero is a known amount. Actuals replace forecasts only via explicit links and both remain evidence; matching values/dates alone do not identify duplicates. Material unknown/unsupported cases suppress ANI, allowance and headroom, retaining known evidence and warnings. Estimates remain labelled estimates.
- **Arithmetic/output:** decimal-string inputs, exact intermediate fractions, half-up GBP display rounding. Standard allowance is £12,570 less half of unrounded ANI above £100,000, floored at zero, then rounded up to whole pounds. Headroom is chosen target minus ANI and is separate from that statutory threshold; it is not a pension recommendation. Independently rounded waterfall rows can differ from rounded ANI; the UI discloses the difference.
- **Product boundary:** no full tax bill, PAYE/NI, take-home/spendable cash, HICBC, pension optimiser/scenario comparison, tax return, durable storage, import/export, account, cloud sync or bank/broker integration. Inputs are **not saved — data lost on refresh**. The first build/browser installation needs downloaded dependencies; installed core calculation uses no external service. The default host binding is `127.0.0.1`; authentication/public hosting is outside this release.

## Rules provenance

No financial rule or tax year changes in #12. Version remains `uk-eng-ni-2026-27-v1`, effective 6 April 2026–5 April 2027. The rules object records 6 November 2026; the contract records pension/benefit review on 6 November, RSU review on 7 November and combined ANI/allowance review on 8 November. These dates describe those source checks, not a promise of continuing automatic updates.

The [financial contract](M1_FINANCIAL_CONTRACT.md) places implementation-specific source links and assumptions beside each rule: [HMRC ANI](https://www.gov.uk/guidance/adjusted-net-income), [2026/27 allowances](https://www.gov.uk/government/publications/rates-and-allowances-income-tax/income-tax-rates-and-allowances-current-and-past), [ITA 2007 s35](https://www.legislation.gov.uk/ukpga/2007/3/section/35/data.html), [ordinary earnings receipt](https://www.gov.uk/hmrc-internal-manuals/employment-income-manual/eim42260), [net pay](https://www.gov.uk/hmrc-internal-manuals/pensions-tax-manual/ptm044230), [sacrifice timing](https://www.gov.uk/hmrc-internal-manuals/employment-income-manual/eim42765), [Gift Aid](https://www.gov.uk/donating-to-charity/gift-aid), [benefit valuation](https://www.gov.uk/expenses-and-benefits-medical-treatment/work-out-the-value) and [ordinary RSUs](https://www.gov.uk/hmrc-internal-manuals/employment-related-securities/ersm20194). Independent primary-source interpretation review passed on **9 November 2026**: ANI steps, 2026/27 allowances, statutory whole-pound ceiling, pension methods/dates, salary sacrifice and savings/ISA distinctions were checked against retrieved official sources. Calendar-day forecasts and half-up display remain documented conventions, not statutory payroll/benefit valuation rules.

SPEC F1–F3/F7–F10 and the financial contract's M1 fixture table are the release arithmetic scope. SPEC F4–F6 are M2 disposal/FX/matching fixtures; their gains are not M1 outputs.

## Implementation references

| Issue | Delivered scope | Merged PR |
| --- | --- | --- |
| #2 / M1.1 | Financial contract and fixtures | [#13](https://github.com/amberdemon/vestor/pull/13) |
| #3 / M1.2 | Local architecture and checks | [#14](https://github.com/amberdemon/vestor/pull/14) |
| #4 / M1.3 | Rules, dates and exact GBP evidence | [#15](https://github.com/amberdemon/vestor/pull/15) |
| #5 / M1.4 | Salary, payroll and bonus | [#16](https://github.com/amberdemon/vestor/pull/16) |
| #6 / M1.5 | Pension methods and Gift Aid | [#17](https://github.com/amberdemon/vestor/pull/17) |
| #7 / M1.6 | Benefits and renewals | [#18](https://github.com/amberdemon/vestor/pull/18) |
| #8 / M1.7 | Manual GBP RSU income | [#19](https://github.com/amberdemon/vestor/pull/19) |
| #9 / M1.8 | Supported other income | [#20](https://github.com/amberdemon/vestor/pull/20) |
| #10 / M1.9 | Combined ANI and allowance | [#21](https://github.com/amberdemon/vestor/pull/21) |
| #11 / M1.10 | Local calculator and strict API | [#22](https://github.com/amberdemon/vestor/pull/22) |

Release acceptance must also link the #12 PR, passing final CI and independent reviewer verdict in #12. Close tracker #1 only after the verification PR is accepted/merged and every child acceptance item is recorded complete.
