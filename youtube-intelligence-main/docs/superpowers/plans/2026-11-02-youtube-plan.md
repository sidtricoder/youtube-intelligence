# YouTube Intelligence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Deliver all five brief workflows, tested and packaged as one zip.
**Architecture:** Single-owner modular monolith. Provider protocol separates Google HTTP from test fixtures; encrypted SQLite, deterministic domain algorithms, service orchestration, FastAPI and official MCP SDK transports.
**Tech Stack:** Python 3.12, FastAPI, MCP Python SDK v1, httpx, cryptography, SQLite, pytest.
**Spec:** docs/superpowers/specs/2026-11-02-youtube-design.md

## Global Constraints
Official YouTube API only. No paid inference dependency. Confirm outside MCP before every playlist write. Tests use synthetic fixtures, never real user data. Quota is reserved before any workflow API call.

## Review Focus
- Concurrent/replayed confirmations must not duplicate playlists.
- Quota reservation must reject before network and account failed requests.
- Metadata cannot grant approval or become HTML.
- OAuth state is expiring, single-use, browser-bound; tokens encrypted.
- Partial API writes must retain progress and avoid unsafe automatic retry.

### Task 1: Domain
Files: src/ytintel/domain.py, tests/test_domain.py.
- [x] Write tests for URL/ID validation, ISO durations, TF-IDF similarity, strict language/runtime selection, request parsing and activity periods.
- [x] Run tests RED, implement pure models/functions, run GREEN.

### Task 2: Persistence and providers
Files: store.py, quota.py, auth.py, providers/base.py, google.py, tests/fakes.py; tests/test_infrastructure.py.
- [x] Write tests for encryption, reservations, expiry/replay, OAuth refresh, pagination and error mapping.
- [x] Run RED, implement transactional SQLite, bounded official API adapter and deterministic fixtures, run GREEN.

### Task 3: Application workflows and transports
Files: service.py, app.py, mcp_server.py, owner.html; tests/test_workflows.py, test_mcp.py.
- [x] Write FR1-FR5 system tests through real MCP wire, auth, approval, partial failures and prompt-injection negative tests.
- [x] Run RED, implement typed endpoints and tools with independent owner approval, run GREEN.

### Task 4: Delivery
Files: README.md, docs/*, skills/video-to-playlist/SKILL.md, Dockerfile, compose.yaml, .github/workflows/*.
- [x] Document local setup on Windows/Linux, Google OAuth, free hosting, MCP configuration, limitations and FR/TQ traceability.
- [x] Run lint, full unit/integration/wire suite, packaging and fresh install smoke. Save exact evidence and create zip excluding secrets and caches.
