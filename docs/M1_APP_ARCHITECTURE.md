# M1.2 local app architecture

Accepted for the [M1.2 scaffold](https://github.com/amberdemon/vestor/issues/3) after the [M1.1 financial contract](M1_FINANCIAL_CONTRACT.md).

- **Domain.** `backend/vestor_domain` uses only the Python standard library. Frozen dataclasses define typed inputs and outputs. A synthetic addition demonstrates the pure `Decimal` boundary with a fixed 28-digit context. Financial validation, precision policy and rules follow the M1.1 contract in their own issues.
- **HTTP.** FastAPI serves the Vite build and `GET /api/health` on one origin. The health response reports server availability. One runtime container keeps startup simple and removes the need for a separate static server or CORS policy.
- **UI.** React, TypeScript and Vite provide a semantic shell with an announced connection status. The typed client validates the health response. Future forms can use the same origin to call Python calculations. All runtime assets ship in the image.
- **Local operation.** Docker Compose publishes port 8000 on IPv4 loopback. The runtime runs as a non-root user with access logging disabled. All runtime requests stay on the local origin. The scaffold has no financial inputs, telemetry, authentication or persistence.
- **Checks.** Docker stages pin Python and Node to patch versions and install locked dependencies. Backend checks run pytest and strict mypy. Frontend checks run TypeScript and Vitest. CI runs both and checks the built app over HTTP on every pull request.

See [README](../README.md#run-locally) for startup and test commands. The milestone release remains tracked in [#1](https://github.com/amberdemon/vestor/issues/1).
