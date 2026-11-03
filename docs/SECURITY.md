# Security posture and production boundaries

**Reporting a vulnerability:** use private vulnerability reporting on this repository (Security → Report a vulnerability). Do not open a public issue for an unfixed vulnerability.

**Safe-by-default:** synthetic data in demo mode, network writes gated by a separate API key, no actuator endpoints. This is a software reference, not an audited production security product.

## Authentication

`RACKHELM_OPERATOR_KEY` must have at least 32 characters and six distinct characters. Use a secret manager and TLS terminator; never commit a real key, send it in URL queries, use browser local storage or expose it to static frontends. The key is compared with `secrets.compare_digest`. Operator writes and the Prometheus endpoint are always protected. In demo mode, telemetry ingestion is disabled unless `RACKHELM_ALLOW_DEMO_INGEST=1` is explicitly set in the server environment; never use that switch with private or real customer telemetry because demo reads are public. In `RACKHELM_MODE=secure` all read APIs require the key; the UI is not served. Secure mode requires a writable database outside `/tmp`, and any unexpected mode name is rejected at initialization.

**Still missing:** distinct users and least-privilege roles, OIDC/JWKS, MFA, device identity, workload mTLS, audit-log external anchoring, tenancy isolation, session/revocation controls and authorization on each asset/facility. Do not expose the demo with real data or publish the secure API to the public internet.

## Data integrity

Pydantic v2 validates strict schemas and UTC timestamps; unknown fields and NaN/Infinity are rejected. Batch writes are atomic and idempotent by rack/time; changed replay payloads fail and roll back. Audit events are chained with SHA-256 and verified before reporting integrity. Without an independent signing key or outside-of-DB anchor, a privileged attacker could rewrite the entire chain. **It is tamper-evident only against partial alteration, not immutable audit evidence.**

## Host and container

Compose binds only to localhost, drops Linux capabilities, uses nonroot UID 65532 and read-only root, restricts processes/memory/CPU, and stores state in a dedicated volume. The host and volume still need encryption, disk quotas, firewall policies, patching and tested backup/restore procedures. For deployment into a real facility, operators should put an allowlisted, authenticated gateway between monitoring networks and the application and keep BMC/IPMI networks segmented.

## Operational prerequisites before real use

1. Introduce a hardened IdP with named analysts, role-based authorization, mTLS from collectors and short-lived access credentials.
2. Move time series to a durable HA cluster with migration tests and encrypted retention/backups.
3. Enforce inbound telemetry provenance, rate limits per agent, replay windows, inventory signing and collector identity.
4. Add centralized structured logs, security monitoring, network policies, key rotation, off-host audit anchoring, alerts and a reviewed on-call response plan.
5. Penetration-test auth/data isolation and prove denial of all physical control endpoints.
6. Independently test sensor accuracy and site-specific engineering limits. A validated advisory is not a safety-rated controller.

## Controls implemented in the application

| Control | Behaviour | Limit |
|---|---|---|
| Rate limiting | Fixed-window counter per peer address, `RACKHELM_RATE_LIMIT_PER_MINUTE` (default 600/min), `/health` exempt, `0` disables | Per process only; use an edge proxy or WAF for multiple replicas |
| Body size cap | `RACKHELM_MAX_BODY_BYTES` (default 1 MB) enforced before routing | Applies to write methods |
| Chunked writes | Rejected with 411 because no length can be enforced | Standard JSON clients send `Content-Length` |
| Peer identity | Uses the socket peer, never client-supplied `X-Forwarded-For` | Behind a proxy, set `--proxy-headers` with a restricted `--forwarded-allow-ips` |
| Error handling | Unhandled exceptions return a generic 500; tracebacks stay in server logs | — |
| Response headers | CSP, HSTS, COOP/CORP, `Permissions-Policy`, `noindex`, `no-store` | HSTS only takes effect over TLS |
| Cross-origin reads | No CORS headers are issued, so browsers block foreign-origin reads | Same-origin only |
| Supply chain | GitHub Actions pinned to commit SHAs; `pip-audit` and gitleaks in CI; CodeQL; weekly Dependabot | Scanners reduce, but do not eliminate, risk |

**Nothing here makes the service unhackable.** The rate limiter is in-memory and resets on restart, SQLite is single-node storage, and there is no account system, MFA or per-asset authorization. Complete the prerequisites above before handling real facility data.