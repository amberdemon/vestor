# Vestor

**Know what your compensation is worth after tax — and what to put into your pension.**

Vestor is a planned local-first UK compensation planner for salary, bonuses, employee RSUs, taxable benefits, pension contributions and share disposals. It models actual and forecast events separately, helps estimate adjusted net income (ANI) around the £100,000 Personal Allowance taper, and explains spendable proceeds and pension trade-offs.

> **Status:** M1 calculator and deterministic ANI engine implemented. M1 release remains subject to independent verification in #12. Estimates are planning aids, not tax advice.

- [Project overview and roadmap](PROJECT.md)
- [Product and financial rules specification](docs/SPEC.md)
- [M1 milestone specification](docs/M1_COMPENSATION_ANI.md) and [M1 implementation tracker](https://github.com/amberdemon/vestor/issues/1)
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

Run `docker compose down` to stop the app. The calculator accepts M1 financial inputs in memory only. **Not saved — data lost on refresh.**

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

## Planned development

M1 — Compensation, adjusted net income and pension calculations

M2 — RSU vesting, share disposals, GBP FX and CGT matching

M3 — Scenario comparisons, pension optimisation and cash projections

M4 — Local persistence, reporting, usability and verification

See [PROJECT.md](PROJECT.md) for milestone boundaries. GitHub issues will be created separately.

## Privacy

This repository is public. **Do not commit real compensation amounts, employer records, tax statements, account details, trade confirmations, or imported statements.** Any examples in the documentation are fictional.

## Using the M1 calculator

Choose tax year, jurisdiction and residence/standard-allowance confirmation, then add effective-dated salary periods. Include zero-rate periods for unpaid time so full-year coverage is explicit. Add dated payroll only when overriding covered salary days; identify any bonus, benefit or RSU components already in its taxable total. The generated source IDs remain stable when changing actual/forecast status and can be used in linked records. An actual can retain a separate forecast as evidence through explicit replacement links.

Add payroll pension reductions (salary sacrifice or net pay), personal pensions/Gift Aid, benefits and renewals, gross GBP RSU vest income and supported other income as applicable. Blank money means unknown; explicit zero means known zero. Coverage checkboxes confirm all evidence or explicit absence for each category. Click **Calculate ANI** after edits; stale results disappear immediately. Source notes are required. No input is automatically saved or sent beyond the local API.

Results show status, ANI, signed target headroom, standard Personal Allowance, source-linked waterfall and expandable rule/date/rounding evidence. Unsupported or incomplete inputs suppress final amounts. Only 2026/27 England/Northern Ireland standard full-year UK-resident cases are supported. Annual salary and supported annual benefits use an inclusive calendar-day forecast, not payroll timing. Externally determined taxable values, eligibility and tax-year profit allocation remain the user's evidence; no insurance valuation, annual allowance check, tax bill, NI, CGT, FX conversion, spendable cash or optimisation is provided. See the [M1 financial contract](docs/M1_FINANCIAL_CONTRACT.md).

`POST /api/calculate` accepts the immutable `AniInputs` shape: money/percentages are exact decimal strings or explicit null, dates are ISO date-only strings, confirmations are strict booleans or null where permitted. Unknown keys and coercions are rejected with field errors without echoing rejected input. It calls the existing `calculate_ani` once and returns its exact wire result. No financial calculations run in React.

Browser CI uses Node 24.18.0 on Debian Bookworm and the package-pinned Playwright 1.56.1 Chromium build. The `npm exec --` separator passes `--with-deps` to Playwright, so its required Linux libraries are installed before launching the pinned browser. Calculation errors map to labelled form controls or sections; unassigned errors remain accessible general text without dead links or rejected source identities.
