# YouTube Intelligence design
Build the attached five functional requirements as a single-owner Python/FastAPI + MCP application. User requested one-pass execution, so architecture choices are implementation decisions, not claimed user approvals.

## Approaches
Use a modular monolith with SQLite and a provider protocol. This keeps deployment free on an existing computer. Microservices add hosting and operational costs; paid embeddings/LLMs are unnecessary for metadata similarity. Use deterministic token TF-IDF cosine similarity and bounded candidate search. The MCP client interprets unrestricted language; a built-in parser supports documented English duration/language forms without paid inference.

## Boundaries
Domain models and algorithms have no HTTP dependency. Service orchestrates provider calls and quota reservation. Google provider handles only official endpoints. Encrypted SQLite stores credentials, draft state, cache and project-wide quota. FastAPI offers typed REST, owner approval UI and OAuth; official MCP SDK offers tools, resources and prompt. One local owner, separate AI and owner credentials, loopback default. No public multi-tenant hosting claim.

## Safety and scope
Metadata is untrusted data. Summaries are metadata summaries, never pretend transcript summaries. Human reviews immutable expiring drafts and approves outside MCP. Private playlist creation is resumable, with partial progress persisted; ambiguous writes stop for inspection rather than blind retry. Rate limits and upstream errors have stable codes. Analysis reports bounded sample coverage and uses activity timestamps, never inferred watch history. Missing event dates are excluded from period statistics.

## Free operation
Offline test fixtures need no keys or paid AI. Production always uses the official Google provider. Real YouTube needs the user's Google OAuth app and account consent. Local hosting is the guaranteed zero-hosting-fee option; remote hosting requires HTTPS, persistence and a secure private access layer. No promise that third-party free tiers remain free.
