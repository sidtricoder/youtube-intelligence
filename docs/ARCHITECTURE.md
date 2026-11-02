# Architecture and API

## Module ownership and SOLID

| Module | Responsibility |
|---|---|
| `domain.py` | Immutable validated domain models; URL/duration parsing; TF-IDF; constraints; statistics |
| `providers/base.py` | Narrow provider protocol for reads and playlist operations |
| `providers/google.py` | Official Google HTTP adapter, response normalization and bounded pagination |
| `tests/fakes.py` | Test-only synthetic adapter, never selected by production |
| `store.py` | Encrypted JSON records, TTL and atomic state transitions |
| `quota.py` | Project-level transactional daily budget/reservations |
| `auth.py` | Google OAuth, encrypted token storage, scope escalation and revocation |
| `service.py` | FR1–FR5 orchestration and state machine |
| `mcp_server.py` | Official SDK tools/resources/prompt; no write-authorizing tool |
| `app.py` | Composition root, FastAPI, credential roles, rate limiting, lifespan |
| `owner.html` | Browser review and explicit human confirmation |

Single responsibility is enforced by these boundaries. New providers implement the protocol without changing domain algorithms. The Google adapter and isolated test fixtures use the same service contract. HTTP, OAuth and storage details do not enter the scoring code. Orchestration depends on the provider protocol rather than the Google implementation. Small infrastructure classes remain concrete where another abstraction would add no current value. This is a modular monolith, not gratuitous microservices.

## Ranking

Tokenization uses Unicode word tokens, case-folded. For the query and candidate documents, TF = 1 + ln(count), IDF = 1 + ln((1 + number_of_documents)/(1 + document_frequency)); cosine similarity is normalized to [0,1]. Video text combines title, first 2,000 description characters and available tags. Candidate search is metadata-based. Channel similarity combines title, description and available channel keywords. Scores explain textual overlap, not educational quality.

Recommendations search up to three seeds: one liked title, one playlist title and one subscription title; duplicates collapse. Previously sampled liked/playlist video IDs are excluded. This is intentionally a transparent baseline, not an exhaustive preference model.

## State and failures

A draft stores exact ordered video IDs, metadata snapshot, constraints, expiry and progress; no endpoint edits it. `pending → writing → complete` claims ownership with an atomic SQL transaction. Before each external write, the application persists `uncertain`; a successful response records the resulting playlist ID or inserted video ID. A known rejected request transitions to `partial` and permits explicit owner resume. Ambiguous network/server errors remain `uncertain`; a process crash around a write also blocks auto-resume. Exactly-once remote creation cannot be guaranteed by a third-party API without idempotency support, so the server never pretends otherwise.

## REST map

All `/api/*` accept the API key or owner key as `Authorization: Bearer ...`; `/owner/*` accepts only the owner key. MCP accepts only the API key. No credentials in URL/query parameters. No wildcard CORS.

| Method/path | Payload / parameters |
|---|---|
| GET `/health` | Public mode and liveness |
| GET `/` | Public owner-page shell, no user data |
| GET `/api/quota` | Budget counters |
| GET `/api/similar-videos?video=...` | ID or HTTPS canonical video URL |
| GET `/api/similar-channels?channel=...` | UC ID, @handle, or canonical channel URL |
| GET `/api/recommendations` | Preferences-based recommendations |
| GET `/api/analysis` | Optional `start`, `end`, `previous_start` ISO dates |
| POST `/api/drafts` | `{topic,total_seconds,max_seconds,language?}` |
| POST `/api/drafts/from-request` | `{request}` documented English grammar |
| GET `/api/drafts/{id}` | Immutable draft + progress |
| POST `/owner/drafts/{id}/approve` | `{confirmation: "CREATE"}` after human review |
| POST `/owner/drafts/{id}/resume` | `{confirmation: "RESUME"}` for known partial failure |
| GET `/owner/oauth/start?write=false` | Browser-bound authorization URL + HttpOnly binding cookie |
| GET `/oauth/callback` | Google redirect with validated code/state and matching cookie |
| POST `/owner/disconnect` | `{}` revoke and clear local user state |
| POST/GET `/mcp/` | MCP Streamable HTTP via official SDK |

Constraints: topic 2–200 characters; total 60–14,400 seconds; maximum individual length 30–7,200 seconds; optional language code (`en`, `hi`, `en-US`, etc.). Live searches exclude duration-zero entries (unavailable/live/unknown). Each selected video must independently satisfy the maximum runtime and language; aggregate runtime never exceeds total. No duplicate video IDs in a draft.

Errors have stable safe codes, including `invalid_input`, `not_found`, `no_matches`, `rate_limited`, `quota_exceeded`, `reauthorization_required`, `channel_required`, `write_scope_required` and `invalid_draft_state`. REST validation returns 422. MCP domain errors return `{error:{code,message}}`; malformed tool schemas are also rejected by the SDK. Rate limit: 60 authenticated HTTP requests/minute per credential role per process; the SDK may use multiple requests for a single client operation. HTTP clients can honor `Retry-After`; this app does not automatically retry Google calls.
