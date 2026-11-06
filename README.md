# Vestor

**Know what your compensation is worth after tax — and what to put into your pension.**

Vestor is a planned local-first UK compensation planner for salary, bonuses, employee RSUs, taxable benefits, pension contributions and share disposals. It models actual and forecast events separately, helps estimate adjusted net income (ANI) around the £100,000 Personal Allowance taper, and explains spendable proceeds and pension trade-offs.

> **Status:** local app scaffold. No calculation engine has been implemented or verified yet. Estimates are planning aids, not tax advice.

- [Project overview and roadmap](PROJECT.md)
- [Product and financial rules specification](docs/SPEC.md)
- [M1 milestone specification](docs/M1_COMPENSATION_ANI.md) and [M1 implementation tracker](https://github.com/amberdemon/vestor/issues/1)
- [Instructions for coding agents](AGENTS.md)

## Run locally

Use Docker Engine 28 or later with Docker Compose v2 or later. The first build downloads base images and dependencies. [Docker loopback publishing details](https://docs.docker.com/engine/network/port-publishing/)

```sh
docker compose up --build
```

Open [Vestor](http://127.0.0.1:8000). The shell should show “Local API connected.” Check the API directly with `curl --fail http://127.0.0.1:8000/api/health`. It returns `{"status":"ok"}`.

After the image is built, start it without building or pulling, including when the host is offline.

```sh
docker compose up --no-build --pull never
```

Run `docker compose down` to stop the app. The scaffold accepts no financial inputs and saves no data.

## Run all tests and type checks

From a clean checkout with Docker running, execute the same commands as PR CI.

```sh
docker build --target backend-checks .
docker build --target frontend-checks .
```

The first command runs pytest and mypy. The second runs TypeScript and Vitest. CI also starts Compose and checks the UI and API over HTTP. Python and Node versions are recorded in `.python-version` and `.node-version`.

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
