# Health checklist (sweep; every real finding becomes a task)

**Security**
- Secrets: none in repo/history/logs; `.env*` ignored; secret scanning enabled on the repo.
- AuthN/AuthZ on every entry point; least privilege; session/token lifetime; password/credential storage.
- Input validation and output encoding (injection, XSS, SSRF, path traversal, deserialisation); file-upload limits.
- Dependencies: known CVEs, unmaintained packages, licences; lockfile committed; update cadence.
- Transport and headers (TLS, CORS, CSRF, rate limiting, security headers); PII minimised, retention defined, backups encrypted.

**Performance & server cost**
- Hot paths profiled; DB: indexes for real queries, N+1, pagination, connection pooling, slow-query log.
- Caching strategy (what, where, TTL, invalidation); payload sizes; compression; static assets/CDN.
- Resource limits: memory, goroutines/threads, timeouts, backpressure; load test for the main journey; cost per request/user known.

**Reliability & operability**
- Health/readiness endpoints; graceful shutdown; retries with backoff and idempotency; timeouts everywhere.
- Logging (structured, no PII), metrics, tracing, alerts on user-visible failures; runbook for the top 3 incidents.
- Migrations safe and reversible; backups restored at least once; config via environment; reproducible builds.

**Quality & delivery**
- CI runs build, lint, unit + integration tests on every PR; `main` protected (required checks, no force-push).
- Test pyramid sane; flaky tests fixed; coverage trend not dropping; e2e smoke for the main journeys.
- TODO/FIXME debt, dead code, duplicated logic, overly large modules; architecture docs current.

**Product & docs**
- README quick start works from a clean clone; API/docs match behaviour; changelog/release notes; onboarding for contributors.
- Accessibility and i18n basics for user-facing UI; analytics/feedback loop to decide what to build next.
