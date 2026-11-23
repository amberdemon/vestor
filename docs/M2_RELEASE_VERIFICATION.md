# M2 release verification

[M2 tracker #24](https://github.com/amberdemon/vestor/issues/24) · [Verification issue #36](https://github.com/amberdemon/vestor/issues/36) · [M2 financial contract](M2_RSU_FX_CGT.md) · [M1 release evidence](M1_RELEASE_VERIFICATION.md)

The implementation candidate was clean main commit `937bbec9e5ba69f82d75d033bf7d8500dd27fa3d`, containing all eleven implementation merges. The release PR records the verification and extends the disconnected smoke test to the versioned calculation route. All test cases and browser captures use synthetic data.

## Observed checks

| Check | Method and result |
| --- | --- |
| Backend and API | Fresh Docker backend stage passed 497 pytest cases, dependency and import checks, and strict mypy over 22 files. M1 and M2 scenarios include malformed fields and rejected-value redaction. |
| Frontend | Fresh Docker frontend stage passed TypeScript and 14 Vitest tests. |
| Production startup and restart | Built and started Compose. Health returned `{"status":"ok"}` and host publishing was `127.0.0.1:8000`. Both checks also passed after shutdown and restart with `--no-build --pull never`. |
| Network isolation | A read-only runtime with `--network none` served health, HTML and JS/CSS. Synthetic M1 F1 returned ANI £78,400. Synthetic M2 F4 returned integrated ANI £79,200, acquisition basis £800, exact gain £90 and no estimate without annual evidence. |
| Desktop and mobile | All 18 Playwright cases passed using the local Chrome channel against Compose. F4, F5, F6 and the 5/6 April case passed both viewports. Candidate main CI also passed the pinned Linux browser suite. |
| Privacy and interaction | Browsers exercised keyboard submission, linked errors, result focus, expansion of source evidence, responsive layout, same-origin requests, empty browser storage and refresh discarding inputs. The API tests check that validation errors omit submitted values. |

The [candidate main CI run](https://github.com/amberdemon/vestor/actions/runs/43967615689) covers both builds, Compose, disconnected runtime and the pinned browser suite. The [UI PR browser evidence](https://github.com/amberdemon/vestor/actions/runs/43916105168/artifacts/14250810606) includes synthetic F4 and cross-year desktop/mobile screenshots. The final release merge, main CI and final-artifact review are recorded in [#36](https://github.com/amberdemon/vestor/issues/36).

### Reproduce

```sh
docker buildx build --no-cache-filter backend-checks --target backend-checks --progress=plain .
docker buildx build --no-cache-filter frontend-checks --target frontend-checks --progress=plain .
docker compose up --build -d
curl --fail http://127.0.0.1:8000/api/health
test "$(docker compose port app 8000)" = '127.0.0.1:8000'
docker compose down
docker compose up --no-build --pull never -d
curl --fail http://127.0.0.1:8000/api/health
test "$(docker compose port app 8000)" = '127.0.0.1:8000'
docker run --rm --network none --read-only \
  -v "$PWD/backend/tests/offline_smoke.py:/app/offline_smoke.py:ro" \
  --entrypoint python "$(docker compose images -q app)" /app/offline_smoke.py
(cd frontend && PLAYWRIGHT_CHANNEL=chrome npm run e2e -- --workers=1)
docker compose down
```

Install browser test dependencies as described in the [local verification commands](../README.md#run-all-tests-and-type-checks). CI tests pinned Chromium with the repository workflow.

## Supported cases and limitations

- Ordinary, unrestricted, listed shares held personally in a taxable account, with identified issuer, class, owner and capacity. Supported RSUs settle in shares at the employment charge. Employer GBP taxable income and allowable CGT cost are independently evidenced. Cash-settled awards, net share withholding, other schemes, joint holdings, corporate actions, wrappers and cross-border or split-year cases are outside supported scope.
- The opening pool needs reconciled history and dated GBP cost, including an explicit zero where coverage starts before any holding. Sales require coverage through their 30-day windows. Same-day and following-30-day allocations precede Section 104. Unresolved history, shorts and the exceptional later acquisition fallback prevent qualified matching.
- The 2026/27 qualified annual CGT estimate applies to the supported England/Northern Ireland scope. It requires other gains and allowable losses, confirmed annual exemption eligibility and an externally evidenced income band. Forecast gains remain estimates. Unsupported reliefs and incomplete annual evidence suppress the tax estimate and preserve separately valid gains.
- The application exposes evidenced withholding and liabilities separately from cash transfer and receipt figures. The cover remainder needs reconciled GBP evidence. Full PAYE, NI, spendable cash, tax filing, bank or broker integration, pension optimisation and durable storage are outside this release.
- The app runs locally with no background network calls. Inputs live in page memory and are discarded on refresh. Initial image and browser dependency installation requires network access.

The separate rate and allowance version is `uk-eng-ni-cgt-2026-27-v1`, effective 6 April 2026 through 5 April 2027 inclusive. The M1 ANI version remains `uk-eng-ni-2026-27-v1`. The governing rules and sources are in the [financial contract](M2_RSU_FX_CGT.md).

## Verified implementation merges

| Issue | PR | Main commit |
| --- | --- | --- |
| #25 | [#37](https://github.com/amberdemon/vestor/pull/37) | `cdcae1c` |
| #26 | [#38](https://github.com/amberdemon/vestor/pull/38) | `c632e7f` |
| #27 | [#39](https://github.com/amberdemon/vestor/pull/39) | `31c6929` |
| #28 | [#40](https://github.com/amberdemon/vestor/pull/40) | `d1b8184` |
| #29 | [#41](https://github.com/amberdemon/vestor/pull/41) | `b83d98e` |
| #30 | [#42](https://github.com/amberdemon/vestor/pull/42) | `afdb61f` |
| #31 | [#43](https://github.com/amberdemon/vestor/pull/43) | `adfe0d3` |
| #32 | [#44](https://github.com/amberdemon/vestor/pull/44) | `0cbc519` |
| #33 | [#45](https://github.com/amberdemon/vestor/pull/45) | `bb082d8` |
| #34 | [#46](https://github.com/amberdemon/vestor/pull/46) | `00180fc` |
| #35 | [#47](https://github.com/amberdemon/vestor/pull/47) | `937bbec` |

## Independent financial audit

GPT-6 Astra at high effort independently constructed raw API requests and a standard-library Fraction oracle for implementation commit `937bbec`. It imported no application or test helpers. All 20 cases passed, including the 17 contract cases, separate forecast and replacement states, day 29 and settlement isolation. Exact quantity and cost conservation passed for all 19 supported ledger cases. The oversale case suppressed gain and tax.

| Scenario | Expected values, also observed exactly |
| --- | --- |
| 01 F4 | gains {'s': Fraction(90, 1)}; ani 80800; pool (0, 0) |
| 02 F5 | gains {'s': 440, 'cover': 20}; ani 80320; pool (20, 100) |
| 03 F6 | gains {'s': Fraction(10, 1)}; ani 80070; pool (0, 0) |
| 04 daily weighted | gains {'s1': Fraction(29, 2), 's2': Fraction(63, 2)}; ani 80000; pool (18, 72) |
| 05 competing sales | gains {'s1': 50, 's2': 87}; ani 80000; pool (25, 100) |
| 06 day30 day31 | gains {'s': 32}; ani 80000; pool (17, 94) |
| 07 tax-year boundary | gains {'s': 54, 'cover': 2}; ani 80000; pool (9, 27); annual known 54 |
| 08 recurring fraction | gains {'s1': Fraction(5, 3), 's2': Fraction(2, 3)}; ani 80000; pool (1, Fraction(10, 3)); annual known 7/3 |
| 09 payroll and fee isolation | gains {'s': Fraction(71, 1)}; ani 10000; pool (6, 486); payroll difference 20 |
| 10a forecast | gains {'s': 40}; ani 80000; pool (5, 50); gain status estimated |
| 10b actual replacement | gains {'s': 50}; ani 80000; pool (5, 50); gain status confirmed |
| 11 loss | gains {'s': -23}; ani 80000; pool (0, 0); tax 0; excess loss 23 |
| 12 annual split | gains {'s': 10000}; ani 80000; pool (0, 0); tax 1140; bf used 2000; bf remaining 0 |
| 13 preserve loss | gains {'s': 4000}; ani 80000; pool (0, 0); tax 0; bf used 800; bf remaining 1200 |
| 16 band extension | gains {'s': 8000}; ani 80000; pool (0, 0); tax 1110; bf used 0; bf remaining 0 |
| 14 incomplete band | gains {'s': 4400}; ani 80000; pool (0, 0); annual status incomplete; tax None |
| 15 oversale | gains {'s': None}; ani 80000; gain status unsupported; tax None |
| 17 missing income FX | gains {'s': 15}; ani None; pool (0, 0) |
| 18 day29 | gains {'s': 20}; ani 80000; pool (10, 50) |
| 19 cash isolation | gains {'s': 71}; ani 10000; pool (6, 486); cash received 387/5; cash difference 0; payroll owed 75; withheld 225; payroll reconciliation 0 |

The auditor rechecked same-day aggregation and statutory priority, proportional pool cost, separate GBP FX, loss ordering and 2026/27 allowance and rates against the primary sources in the contract. The API requests used synthetic values throughout. No monetary discrepancy remained. The independent script ran with `python3 /tmp/vestor_audit36.py` against the local Compose endpoint. The detailed expectations and responses are recorded in verification issue #36.
