# Requirements interpretation

We interpret the addendum as superseding the earlier requirement that FR1 and FR2 require authentication. We expose public discovery and stateless previews while protecting every operation that accesses an account or persists a user-owned workflow.

We interpret “authorized user” as a role held by each signed-in user, not a fixed operator or owner account. Each user connects their own Google account, identified by a verified Google OIDC `sub`. We do not use the operator's account as a shared bot. FR3 needs the requesting user's likes, subscriptions and playlists; FR4 analyzes that user's bounded activity sample; FR5 creates a playlist in that user's account after that same user agrees to the exact draft (via AI conversation confirmation or optional browser button). We reject a shared operator account because it would place every user’s playlist in the operator’s library and expose those playlists and associated preferences to the operator instead of keeping them within each user’s own account.

| Requirement | Interpretation |
|---|---|
| FR1 | Public metadata-based similar videos; no personal profile required |
| FR2 | Public metadata-based similar channels; no personal profile required |
| FR3 | Protected recommendations using the caller's own bounded Google profile sample |
| FR4 | Protected engagement analysis for the caller's own account, with disclosed sample/date limits |
| FR5 | Public stateless preview; protected immutable draft, AI or browser-button confirmation, private playlist write and status |
| Skill | Metadata summary → public candidates/preview → sign-in and owned draft → AI confirmation after agreement (or optional browser button) → owned status |

`similar_videos`, `similar_channels`, `video_summary` (metadata only), `propose_playlist`, `playlist_from_request` and `video_to_playlist` are public. Public preview tools do not persist drafts or return an approval that can authorize a write. Signing in adds profile-aware exclusion and access to personal workflows. `recommendations`, `engagement_analysis`, `create_playlist_draft`, `playlist_status` and `disconnect` are protected. Unknown operations fail closed as protected. Protocol initialization, lists, ping and notifications remain reachable without authentication; a supplied invalid bearer token is rejected even on public requests.

We keep app/MCP authorization and Google authorization distinct. The MCP resource scope is `youtube:read`; it is not a Google scope and cannot authorize a playlist write. We request `openid`, `https://www.googleapis.com/auth/youtube.readonly` and `https://www.googleapis.com/auth/youtube` on initial sign-in, as required by the 2.1 change request. Explicit per-draft confirmation (via AI tool after user agreement in conversation, or optional browser button) remains separate from that grant. Scope consent and approval of an exact immutable draft are separate decisions.

We require isolation of identities, tokens, refresh, caches, drafts, quota and approvals. No configuration may switch the public service into an operator-account or single-user bypass. Browser sessions and MCP tokens resolve to the same subject; client arguments never select another user's identity. An unknown or another user's draft cannot be read, approved, resumed or written by guessing its ID.

We interpret the latest explicit change request as superseding local TQ-6 preflight budgets and fair-share controls: we impose no application unit budgets, daily/search caps or request-rate limits. We let Google enforce its actual project allowance and surface its errors. We retain usage accounting only; no counter can block a call. We preserve account isolation, authentication and explicit per-playlist confirmation (AI-mediated or browser button). We do not promise quota fairness or availability across callers.

We retain valid domain, workflow and Google-provider tests. Earlier fixed-owner/static-key tests must be adapted to the multi-account contract rather than removed to obtain a passing suite. TQ1–TQ6 traceability and the required real-TCP mixed MCP coverage are documented in TESTING.md. Production consent verification and live writes require actual end-user completion; test fixtures cannot establish those facts.

We ship source and `.env.example` only. Existing `.env` and data are not edited, copied into handoff archives or treated as test fixtures. Render secrets are entered manually, Neon provides persistent encrypted storage, and the exact Google callback is the HTTPS root origin plus `/oauth/callback`.

## Implementation and test traceability

We interpret the following mapping as part of the requirements, not a substitute for observed test results. The named tests use synthetic users/provider responses; actual Google consent and writes remain end-user acceptance work.

| Requirement | Implementing modules | Specific tests |
|---|---|---|
| FR-1 similar videos | `domain.py`, `service.py`, `providers/google.py`, `policy.py`, `http_gate.py`, `mcp_server.py` | `test_domain.py::test_similarity_and_missing_tags`; `test_google_only.py::test_public_video_reads_use_key_without_oauth`; `test_mcp.py` real-TCP public tool workflow |
| FR-2 similar channels | `domain.py`, `service.py`, `providers/google.py`, `policy.py`, `mcp_server.py` | `test_infrastructure.py::test_channel_lookup_ranking_adapter_and_private_write_bodies`; `test_workflows.py::test_all_read_workflows`; `test_mcp.py` real-TCP channel workflow |
| FR-3 own recommendations | `context.py`, `credentials.py`, `tenancy.py`, `service.py`, `providers/google.py`, `api.py`, `mcp_server.py` | `test_google_only.py::test_private_google_requests_use_each_request_account_and_isolated_cache`; `test_infrastructure.py::test_parallel_workflows_keep_immutable_request_identity`; `test_mixed_mcp.py::test_protected_calls_are_http_challenges_before_dispatch` |
| FR-4 own engagement analysis | `domain.py`, `service.py`, `credentials.py`, `tenancy.py`, `api.py`, `mcp_server.py` | `test_domain.py::test_analysis_dated_activity_not_publication`; `test_domain.py::test_equivalent_timezone_boundaries_have_equivalent_period_counts`; `test_workflows.py::test_all_read_workflows`; `test_mixed_mcp.py` protected-call cases |
| FR-5 reviewed private playlist | `service.py`, `tenancy.py`, `credentials.py`, `web.py`, `oauth_routes.py`, `providers/google.py` | `test_domain.py::test_selection_strict_and_deduplicated`; `test_approval.py::test_approval_own_session_csrf_exact_confirmation_and_escape`; `test_approval.py::test_other_user_cannot_infer_draft_and_bearer_cannot_approve`; `test_workflows.py::test_partial_known_failure_resumes_without_duplicate_create`; `test_workflows.py::test_ambiguous_write_stops_retry` |
| Video-to-playlist skill | `skills/video-to-playlist/SKILL.md`, `service.py`, `mcp_server.py`, `web.py` | `test_tenancy.py::test_public_summary_and_preview_have_metadata_links`; `test_tenancy.py::test_anonymous_preview_has_no_draft_or_user_writes`; `test_workflows.py::test_preview_confirm_idempotence_and_metadata_cannot_approve`; `test_mcp.py` skill/prompt/resource workflow |
| TQ-1 unit tests | `domain.py`, `config.py`, `security/store.py`, `security/protocols.py`, `policy.py` | `test_domain.py`; `test_setup.py`; `test_oauth_security.py::test_expiry_audience_and_cross_client_isolation`; `test_http_gate.py::test_unknown_defaults_protected_and_untrusted_forwarded_ip_ignored` |
| TQ-2 integration tests | `providers/google.py`, `identity.py`, `credentials.py`, `store.py`, `tenancy.py` | `test_infrastructure.py::test_profile_pagination_sample_and_missing_private_videos`; `test_identity.py::test_exchange_verifies_google_subject_and_normalizes_credentials`; `test_credentials.py::test_refresh_cannot_restore_disconnected_or_replaced_grant`; `test_postgres.py` opt-in disposable-schema tests |
| TQ-3 MCP system tests | `app.py`, `http_boundary.py`, `http_gate.py`, `mcp_server.py`, `security/oauth.py`, `oauth_routes.py` | `test_mcp.py`; `test_mixed_mcp.py::test_mixed_batch_is_preflighted_atomically`; `test_mixed_mcp.py::test_authorization_requires_s256_resource_and_registered_redirect`; `test_mixed_mcp.py::test_public_client_revocation_over_http` |
| TQ-4 negative cases | `domain.py`, `identity.py`, `credentials.py`, `http_gate.py`, `security/oauth.py`, `web.py` | `test_identity.py::test_exchange_rejects_invalid_identity_claims`; `test_mixed_mcp.py::test_bad_expired_revoked_wrong_audience_reject_even_public`; `test_mixed_mcp.py::test_insufficient_scope_and_malformed_batch_fail_before_provider`; `test_oauth_security.py::test_invalid_redirects_rejected`; `test_workflows.py::test_ambiguous_write_stops_retry` |
| TQ-5 isolated live checks | `scripts/live_smoke.py`, CI configuration, test fixture injection | `test_scripts.py`; `test_google_only.py::test_production_public_lookup_uses_google_api_without_fixture_provider`; ordinary tests use fakes/MockTransport and never call live Google; only optional `TEST_DATABASE_URL` enables live disposable PostgreSQL tests |
| TQ-6 current override: Google enforcement only | `quota.py`, `tenant_quota.py`, `providers/google.py`, `http_gate.py` | `test_google_quota_only.py`; revised accounting/concurrency regressions in `test_tenancy.py` and `test_infrastructure.py` |

We interpret credential lifecycle isolation to include races, not just ordinary lookups. Persistent credential generations advance on fresh login and revocation. Read/write operations and refresh compare their captured generation with current state; stale results cannot restore a disconnected grant, overwrite a newer login or continue a revoked workflow. `test_credentials.py`, `test_oauth_security.py::test_refresh_cannot_restore_revoked_or_replaced_google_grant` and `test_tenancy.py::test_stale_scoped_store_refuses_operations_after_revocation` exercise those guarantees.

We interpret Google external Testing as a bounded evaluation stage: at most 100 test users and seven-day refresh-token expiry for this non-basic YouTube scope flow. Production use requires applicable Google verification/review and correct consent-screen configuration. We do not claim that offline tests or a reachable consent URL complete that verification.

We require an explicit `RESUME` browser confirmation for known partial writes. Ambiguous/unknown write outcomes remain blocked from automatic retry; the user inspects YouTube manually. These negative and recovery tests remain mandatory even when happy-path playlist creation works.


We interpret the 2.1.0 request as removing application-imposed playlist duration floors/ceilings
and making caller-supplied duration bounds optional. Positive integer values remain necessary
when a bound is provided; null/omitted values are unbounded. We still enforce explicit user/AI
bounds and disclose API sampling/quota limits. `test_duration_freedom.py` and
`test_mixed_mcp.py::test_initial_connection_requests_write_permission_and_long_draft_needs_no_step_up`
cover that behavior. We request Google writes at initial sign-in as the new default, while
per-account isolation and explicit per-draft human approval remain unchanged.

We interpret browser-dialog simplification as a presentation change, not permission for an AI tool to approve its own draft. We use native confirm/prompt boxes and keep results in the AI conversation; the same user’s cookie, CSRF token, exact draft and typed confirmation remain mandatory.
