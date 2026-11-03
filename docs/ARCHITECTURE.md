# Architecture and API

The application is a modular monolith. Pure immutable domain algorithms depend on no HTTP or identity machinery. The composition root creates request-scoped services using either an anonymous context or a verified user context; Google credentials are never a process-wide current account.

| Boundary / module | Responsibility |
|---|---|
| `domain.py` | Validation, URL/duration parsing, TF-IDF, constraints, statistics |
| `providers/base.py`, `providers/google.py` | Narrow provider protocol and official Google normalization/bounded pagination |
| `context.py` | Immutable anonymous/user request contexts |
| `identity.py`, `credentials.py` | Google OIDC verification and subject-bound credential access/refresh |
| `tenancy.py`, `store.py` | Encrypted public/tenant persistence, ownership and atomic transitions |
| `quota.py`, `tenant_quota.py` | Project, anonymous/IP and individual transactional reservations |
| `security/protocols.py`, clock port in `security/store.py` | Narrow security ports and injectable time |
| `security/store.py`, `security/oauth.py` | Encrypted OAuth clients/grants/tokens and official SDK provider implementation |
| `policy.py`, `http_gate.py`, `http_boundary.py` | Explicit public allowlist and JSON-RPC-aware mixed-auth HTTP gate |
| `service.py` | FR1–FR5 orchestration and immutable draft state machine |
| `mcp_server.py` | SDK tools/resources/prompts bound to request context |
| `app.py` | FastAPI composition and lifespan |
| `api.py`, `web.py`, `oauth_routes.py` | User-scoped API, browser review/approval, and OAuth/session routes |
| `web.py` | User's own browser review and explicit confirmation |

Security modules keep provider/storage/policy/transport concerns separate. Some compatibility names may remain at these boundaries; responsibility and request identity must remain explicit. A new provider implements the read/write protocol without changing ranking. Test fixtures are injected only in tests, never selected as a production demo provider.

## Access and identity

Public calls: `similar_videos`, `similar_channels`, metadata-only `video_summary`, `propose_playlist`, `playlist_from_request`, `video_to_playlist`. Preview responses are stateless: they cannot authorize writes or allocate a persistent user draft. Authentication adds profile-aware exclusion where appropriate.

Protected calls: `recommendations`, `engagement_analysis`, `create_playlist_draft`, `playlist_status`, `disconnect`. Each resolves a verified subject and a user-scoped repository/quota/provider. No input argument selects another user. Protocol initialization/lists/ping/notifications are anonymously reachable, but a supplied invalid token is rejected before dispatch. Unknown operations require authorization. Mixed batches apply policy to every member; one protected member cannot be smuggled through a public wrapper.

The SDK's OAuth routes advertise dynamic registration. Redirects are HTTPS or HTTP loopback, registered exactly. CIMD is unsupported and not advertised. Protected-resource discovery is rooted at `/.well-known/oauth-protected-resource`, and the resource challenge names `youtube:read`. This app scope does not grant Google's write permission. The root Google callback remains `/oauth/callback` under the configured origin; `/mcp/` is only the Streamable HTTP endpoint.

## Ranking and samples

TF-IDF uses Unicode case-folded tokens, logarithmic term frequencies and smoothed inverse document frequencies; cosine scores are normalized to [0,1]. Video text includes title, a bounded description and available tags. Channel similarity uses available title, description and keywords. These are transparent metadata heuristics, not verified quality rankings.

Recommendations derive bounded seeds from the caller's likes, playlists and subscriptions, deduplicate candidates and exclude sampled known videos. Candidate discovery is capped at 50 videos or 25 channels; profile samples at 100 likes, 100 subscriptions and 10 playlists × 100 items, with truncation disclosed. No watch history is claimed. Activity comparisons use available playlist-add dates; unavailable liked dates are not replaced with publication dates. UTC/offset conversion is explicit.

## Draft state and failures

A protected draft stores exact ordered video IDs, metadata snapshot, constraints, expiry, owner subject and progress. No endpoint mutates its content. Browser approval validates that same subject and exact draft. Persistent credential generations invalidate stale read/write/refresh operations after disconnect or a newer login, so an in-flight response cannot resurrect an old grant. `pending → writing → complete` uses atomic claims. Before an external write, progress is persisted as uncertain; a successful response records the playlist/inserted item. A known rejection may become partial and permit explicit browser resume with `RESUME` confirmation. Ambiguous failures remain uncertain. Remote exactly-once delivery cannot be guaranteed without Google idempotency support.

Constraints include topic 2–200 characters and optional positive integer duration values. There is no fixed server minimum/maximum total or per-video duration; omitted/null duration values are unbounded. Optional language requires exact declared metadata; unknown language is excluded. Duration-zero/unavailable/live candidates are excluded, duplicates collapse, and total runtime never exceeds its ceiling. The algorithm may leave unused runtime rather than relax constraints.

## Persistence and quota

Neon pooled PostgreSQL is preferred. This release runs one instance and one worker; database quota/rotation operations remain atomic, but in-process request rate windows are not a distributed limiter. Tenant ownership is part of personal record predicates, not just an encrypted payload field. Public metadata caches never contain a personal profile. Configured database failures fail closed without SQLite fallback. Explicit local SQLite remains a development option. `python -m ytintel.migrate --database-url-env DATABASE_URL_POOLED` (or explicit `--sqlite /path/to/local.db`) runs the same idempotent version-1 table initialization as startup. Existing single-owner records are ignored and never assigned to a signed-in user.

Short transactions, schema-scoped transaction advisory locks and atomic reservations support Neon transaction pooling. Quotas check project units and searches, anonymous pool/IP, and signed-in-user allocation before the workflow starts. Attempted calls consume quota; unused reservation is refunded. The ledger cannot observe external project consumers.

REST browser actions include the root shell, `/oauth/callback`, user sign-in/write-consent entry points, user-owned draft read/approve/resume and disconnect. `/health` is liveness. Consult the generated OpenAPI `/docs` for the exact current REST schemas rather than reusing legacy API/owner keys. The MCP endpoint is `/mcp/`; tokens go through the OAuth client flow, never the URL.


## Protocol reference and SDK compatibility

The implementation was checked against the installed MCP Python SDK 1.30.0 and the
[2026-07-28 authorization specification](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization).
The resource gate uses SDK `BearerAuthBackend` and `ProviderTokenVerifier` with the configured
resource URL, alongside the provider's strict audience/expiry lookup. SDK OAuth handlers implement
registration, code-verifier checks, token exchange, revocation and metadata. The HTTP boundary adds
explicit S256 and token-request resource validation where the SDK does not forward those fields.
CIMD is recommended by the current specification but has no authorization-server primitive in this
SDK version; DCR remains the supported interoperability path. We do not claim 2026 protocol-wide
support beyond this authorization compatibility: MCP wire negotiation uses the pinned SDK.

## Browser presentation

`ui.py` contains escaped HTML renderers; `ui_theme.py` contains the responsive self-contained CSS. `web.py` owns session, CSRF and authorization decisions. `http_boundary.py` negotiates browser error HTML while preserving API responses. `browser_policy.py` builds restricted form-origin policies and the consent script's per-response nonce policy. OAuth denial is consumed atomically by `AuthServer.complete_login(approved=False)` without creating a code.

## Request diagnostics

`observability.py` owns stdout event formatting, allow-listed fields, safe validation guidance and the outer ASGI correlation boundary. `mcp_observer.py` extends the SDK dispatch method to observe validation before tool execution and sanitize unexpected tool failures. Transport code contains no playlist decision logic. Domain/service/provider/auth layers emit aggregate stage events without credentials or personal metadata. The request context ID flows through ContextVar and is never accepted from a client header.
