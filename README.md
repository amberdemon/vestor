# Vestor

**Plan adjusted net income and trace RSU share gains.**

Vestor is a local-first UK compensation planner with an optional RSU and share ledger. The 2026/27 calculator explains adjusted net income (ANI), the Personal Allowance taper, GBP acquisition and sale values, matched share gains, qualified Capital Gains Tax (CGT), and separate payroll withholding and cash receipts.

- [Project overview and roadmap](PROJECT.md)
- [Product and financial rules specification](docs/SPEC.md)
- [M2 financial contract](docs/M2_RSU_FX_CGT.md) and [M2 release verification](docs/M2_RELEASE_VERIFICATION.md)
- [M1 release verification](docs/M1_RELEASE_VERIFICATION.md)
- [Instructions for coding agents](AGENTS.md)

## Run locally

Use Docker Engine 28 or later with Docker Compose v2 or later. The first build downloads base images and dependencies. [Docker loopback publishing details](https://docs.docker.com/engine/network/port-publishing/)

```sh
docker compose up --build
```

Open [Vestor](http://127.0.0.1:8000). The page shows “Your adjusted net income”. Check the API directly with `curl --fail http://127.0.0.1:8000/api/health`. It returns `{"status":"ok"}`.

After the image is built, start it without building or pulling, including when the host is offline.

```sh
docker compose up --no-build --pull never
```

Run `docker compose down` to stop the app. The calculator keeps financial inputs in page memory. **Not saved — data lost on refresh.**

## Run all tests and type checks

From a clean checkout with Docker running, execute the same commands as PR CI.

```sh
docker build --target backend-checks .
docker build --target frontend-checks .
```

The first command runs pytest and mypy. The second runs TypeScript and Vitest. CI also starts Compose and runs Playwright desktop/mobile scenarios against the real API, with synthetic screenshots attached as artifacts. Python and Node versions are recorded in `.python-version` and `.node-version`.

To run the same browser scenarios against a running Compose service:

```sh
cd frontend
npm ci
npm exec -- playwright install chromium
npm run e2e
```

`VESTOR_URL` can select a different local port. `PLAYWRIGHT_CHANNEL=chrome` optionally uses installed Chrome instead of the default pinned test browser. Browser screenshots and reports are ignored by Git. Browser installation downloads dependencies once; the built application itself needs no external service.

Read the [M1.2 architecture decision](docs/M1_APP_ARCHITECTURE.md) for the package and deployment boundaries.

## Principles

- Keep financial information local and private; never commit real payroll, vesting or account data.
- Use UK-tax-year-aware, versioned rules and explicit GBP currency conversions.
- Distinguish taxable vesting income from gains on later share sales.
- Separate actual values from forecasts, and estimates from confirmed payroll deductions.
- Make every result auditable from its underlying events, rates and assumptions.
- Build deterministic, tested rules before dashboards or external integrations.

## Release scope and roadmap

M1 — Implemented compensation inputs, pension methods, ANI, standard Personal Allowance and target headroom; acceptance tracked in [#12](https://github.com/amberdemon/vestor/issues/12).

M2 — Implemented RSU ledger, dated USD-to-GBP evidence, UK share matching, qualified 2026/27 CGT and separate settlement evidence. See [release verification and limitations](docs/M2_RELEASE_VERIFICATION.md).

M3 — Planned scenario comparisons, pension optimisation and cash projections.

M4 — Planned local persistence, export/restore and further product polish.

See [PROJECT.md](PROJECT.md) for milestone boundaries. The [release evidence](docs/M1_RELEASE_VERIFICATION.md) links the M1 implementation PRs.

## Privacy

This repository is public. **Do not commit real compensation amounts, employer records, tax statements, account details, trade confirmations, or imported statements.** Any examples in the documentation are fictional.

## Using the M1 calculator

Choose tax year, jurisdiction and residence/standard-allowance confirmation, then add effective-dated salary periods. Include zero-rate periods for unpaid time so full-year coverage is explicit. Add dated payroll only when overriding covered salary days; identify any bonus, benefit or RSU components already in its taxable total. The generated source IDs remain stable when changing actual/forecast status and can be used in linked records. An actual can retain a separate forecast as evidence through explicit replacement links.

Add payroll pension reductions (salary sacrifice or net pay), personal pensions/Gift Aid, benefits and renewals, gross GBP RSU vest income and supported other income as applicable. Blank money means unknown; explicit zero means known zero. Coverage checkboxes confirm all evidence or explicit absence for each category. Click **Calculate ANI** after edits; stale results disappear immediately. Source notes are required. No input is automatically saved or sent beyond the local API.

Results show status, ANI, signed target headroom, standard Personal Allowance, source-linked waterfall and expandable rule/date/rounding evidence. Unsupported or incomplete inputs suppress final amounts. Only 2026/27 England/Northern Ireland standard full-year UK-resident cases are supported. Annual salary and supported annual benefits use an inclusive calendar-day forecast, not payroll timing. Externally determined taxable values, eligibility and tax-year profit allocation remain the user's evidence; no insurance valuation, annual allowance check, tax bill, NI, CGT, FX conversion, spendable cash or optimisation is provided. See the [M1 financial contract](docs/M1_FINANCIAL_CONTRACT.md).

Net-pay forecasts require dated earnings and deductions; a deduction and its linked taxable receipt in different tax years are unsupported. Relief-at-source pension and Gift Aid require qualification confirmation and use the gross amount once. Salary sacrifice requires a prospective valid election; ordinary employer pension funding is evidence, not a separate ANI deduction. See the [release limitations](docs/M1_RELEASE_VERIFICATION.md#supported-cases-and-limitations).

`POST /api/calculate` accepts the immutable `AniInputs` shape: money/percentages are exact decimal strings or explicit null, dates are ISO date-only strings, confirmations are strict booleans or null where permitted. Unknown keys and coercions are rejected with field errors without echoing rejected input. It calls the existing `calculate_ani` once and returns its exact wire result. No financial calculations run in React.

Browser CI uses Node 24.18.0 on Debian Bookworm and the package-pinned Playwright 1.56.1 Chromium build. The `npm exec --` separator passes `--with-deps` to Playwright, so its required Linux libraries are installed before launching the pinned browser. Calculation errors map to labelled form controls or sections; unassigned errors remain accessible general text without dead links or rejected source identities.

## Using the share ledger

Enable **Include share ledger and CGT** in the calculator. Give each holding a consistent issuer, share class, owner and capacity. Enter a reconciled opening snapshot or an explicitly evidenced zero opening holding. Confirm coverage through 30 calendar days after the last disposal, even where the coverage crosses 5 April.

Add dated grants and vests, manual FX rates by purpose, sale and cover trades, and allowable dealing expenses. Use the source IDs to link the records. Confirm gross taxable payroll GBP where available. Confirm separately evidenced acquisition cost and name any existing ANI payroll or manual vest entry that represents the same income.

Use **Calculate ANI and shares** to inspect exact disposal matches, Section 104 movements and the annual estimate. The latter requires known other gains and losses, allowance eligibility and external band evidence. Payroll remittances, repayments, wire fees and observed receipts appear in the settlement section. Unsupported awards, incomplete holding history and unresolved annual evidence are flagged. See the [supported release boundaries](docs/M2_RELEASE_VERIFICATION.md#supported-cases-and-limitations).

The optional ledger sends the combined request to `POST /api/v2/calculate`. The original `POST /api/calculate` accepts the standalone ANI request.
