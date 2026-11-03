# Security model

The service supports multiple independent Google accounts. The trust boundary is the verified Google OIDC subject (`sub`), not email, an operator key, a client-supplied user ID or the first person to sign in. Every personal token, refresh, cache, draft, quota debit and approval belongs to that subject. Public workflows use API-key-backed metadata only and cannot access an operator's private profile.

## Authentication and consent

The official MCP SDK 1.30 authorization-provider interfaces and routes implement MCP authorization with PKCE, browser-bound state and dynamically registered clients. MCP access is audience/resource-bound to the configured HTTPS server. The protected resource metadata is at the HTTPS root `/.well-known/oauth-protected-resource`; protected failures return a real `WWW-Authenticate: Bearer` challenge containing that HTTPS `resource_metadata` URL and `scope="youtube:read"`.

The HTTP gate examines JSON-RPC calls, including batches. Initialization, capability/tool/resource/prompt lists, ping and notifications are allowed without sign-in. Explicit public tools are available anonymously; unknown methods/tools are protected. If a caller supplies an invalid, expired, revoked or wrong-audience token, it receives 401 even when the requested tool is public. An insufficient scope cannot acquire personal access. No legacy URL key or fixed API/owner key grants user identity.

Google's authorization-code flow uses PKCE, state, nonce and a browser-bound cookie. OIDC validation checks signature, issuer, audience, expiry and nonce before accepting `sub`. Default consent requests `openid` plus `https://www.googleapis.com/auth/youtube.readonly`. Write enablement is a separate explicit browser action requesting `https://www.googleapis.com/auth/youtube`. A broad write grant never substitutes for exact-draft human approval. Refresh preserves the original subject and cannot switch the request to another account; invalid grants require reauthorization. Disconnect revokes that user's grant and removes their retained personal state. A persistent credential generation advances on fresh login and revocation. Read/write and refresh paths validate the captured generation and compare current credentials atomically; stale in-flight refreshes cannot resurrect a disconnected grant or overwrite a newer login.

Dynamic registration accepts exact HTTPS redirect URIs and HTTP loopback development redirects only, rejecting credentials, fragments and malformed URLs. Client metadata is not trusted to choose identity, scopes or redirects. Client ID Metadata Documents (CIMD) are unsupported by the pinned authorization-server API and are not advertised. No arbitrary remote client metadata document is fetched.

SDK 1.30 has a public-client revocation form issue: its revocation request model requires a nullable `client_secret` field even for a public client that correctly omits it. A narrow compatibility shim supplies only the missing empty form field and delegates to the original SDK handler. SDK client authentication, token ownership and revocation behavior remain authoritative; the shim does not replace the authorization server.

## Isolation, approval and persistence

Browser sessions and MCP access tokens bind to a verified subject. Every protected lookup applies that subject in storage, including draft status and atomic claims. A draft ID is a reference, not a capability. Another user's ID is unavailable. Google calls obtain credentials from the request's subject; shared mutable “current user” state and single-user overrides are forbidden.

Browser write actions require the user's session, CSRF protection, same-origin checks and explicit confirmation of the immutable ordered draft. MCP exposes draft creation/status, never approve/create-remote/resume authority. Drafts expire after 30 minutes. Before each external write, progress is persisted conservatively; known rejections may allow explicit `RESUME` browser confirmation, but ambiguous network failures and crashes remain uncertain. Inspect YouTube manually; automatic retry could duplicate remote writes.

Fernet authenticated encryption protects stored credentials and personal payloads in Neon PostgreSQL (or explicit local SQLite). Relational user ownership and quotas still expose structural metadata to database administrators. Store the encryption key separately in Render secrets, preserve it across deploys, and plan key rotation with migration/re-encryption before removing old key material. Losing the key loses access to retained records. Database deletion does not promise forensic erasure of backups. A compromised application host can decrypt records and is outside encryption-at-rest protection.

## Threats and controls

| Threat | Control and remaining boundary |
|---|---|
| Bearer/token theft | HTTPS, HttpOnly secure browser cookies, expiry/revocation, redacted logs, no query keys; stolen valid tokens remain usable until expiry/revocation |
| Confused deputy | Verified subject and resource/audience checks; Google credentials selected per request; no operator-account fallback |
| Cross-tenant access | User-scoped queries, claims, caches, quotas and approval checks; ID guessing does not grant access |
| Redirect abuse / login CSRF | Exact registered redirects, PKCE, single-use expiring state, nonce, browser binding and origin/CSRF checks |
| Prompt injection in metadata | Treat titles/descriptions/tags as data; escaped UI text; no tool can approve a write |
| Client metadata SSRF | CIMD unsupported and unadvertised; no arbitrary document URL fetch |
| Credential rotation/revocation | Expiring app credentials, refresh grant failure handled safely, per-user disconnect; coordinated encryption-key rotation |
| Public quota exhaustion | Atomic global/anonymous/IP/search reservations, rate limits and per-user budgets |

Quota is reserved transactionally before provider calls. Attempted upstream calls count even when they fail; unused reservations are refunded. Pacific-midnight rollover and a separate search ceiling are enforced. The default anonymous pool is 30% of the daily general-unit budget; signed-in users default to 1,000 units/day. The ledger cannot see unrelated software consuming the Google project.

Trust proxy headers only from explicitly configured ingress addresses. Set `YT_TRUSTED_PROXIES` to explicit comma-separated IPs/CIDRs only (empty by default), never `*`; spoofed forwarding headers would defeat IP quotas and origin assumptions. Configure the public HTTPS origin and accepted MCP host/origin explicitly. Do not enable wildcard CORS. CSP, frame denial, `nosniff` and `strict-origin` referrer headers (no path/query disclosure) protect the browser shell. Keep access/debug logs from capturing bearer credentials, OAuth codes, query metadata or personal responses.

Only `.env.example` belongs in source/handoff packages. Existing `.env` and data must not be read into reports, edited or included in archives. Store database URLs, Google API/client secrets and the Fernet key in Render's secret environment. Report security issues privately without credentials or personal account data.
