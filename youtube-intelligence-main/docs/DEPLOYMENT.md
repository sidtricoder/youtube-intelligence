# Deployment guide

Use [Deploy on Render + Neon](DEPLOY_RENDER.md) for the current multi-account release. It documents the private source repository, manual secret configuration, idempotent migration, exact Google callback, per-user consent and plain OAuth-enabled `/mcp/` connector URL.

Earlier fixed-owner, static-header and query-key deployment flows are superseded. Only `.env.example` belongs in the handoff; existing `.env` and data remain untouched. See [security](SECURITY.md) and [end-user acceptance](TESTING.md) before wider use.
