# Fix Windows CI and blocked OAuth consent — 2.0.1

## What failed

The bootstrap test unconditionally asserted POSIX permission mode 0600. Windows reports different
mode bits, even when creation requested 0600; these bits do not describe Windows ACLs. The mode
assertion is now POSIX-only. Encryption, exclusive file creation and refusal to overwrite existing
configuration remain tested on every platform. A new test checks the requested creation flags/mode.

The browser failure is a code-level Content Security Policy bug. Chrome applies `form-action` to
redirects following a form POST. A self-only consent page blocked the redirect from this server back
to Claude. The consent page now permits its validated, registered callback origin, while normal
pages remain self-only. The write-enable form similarly permits the Google accounts origin.
CSRF, exact redirect registration, account matching and the other CSP directives remain enforced.

## Replace code cleanly

Commit the contents of `youtube-intelligence-main/` at the repository root, where Dockerfile and
pyproject.toml are. Replace matching files. Preserve your real `.env` and `data/` untouched.

Your coverage includes the removed singleton `src/ytintel/auth.py`, indicating files from an older
release remain. Remove these two obsolete tracked files if present:

```powershell
git rm --ignore-unmatch src/ytintel/auth.py src/ytintel/owner.html
```

GitHub web users can delete those exact files with the file menu. Keep the current `security/`
package. This is a source-code update; it requires no database reset or schema migration.

## Render

Check these exact values for your deployment (no surrounding shell quotes):

| Variable | Value |
|---|---|
| `YT_PUBLIC_BASE_URL` | `https://youtube-intelligence-vbyf.onrender.com` |
| `YT_REDIRECT_URI` | `https://youtube-intelligence-vbyf.onrender.com/oauth/callback` |

Alternatively omit both overrides and let `RENDER_EXTERNAL_URL` derive the origin and callback.
Keep your current encryption key, Neon URL(s), Google client ID/secret and YouTube API key unchanged.
Those credentials do not cause either reported failure. Do not enable wildcard CSP/CORS or trust
all proxy headers to work around the browser error. Deploy the new commit after CI completes.

## Google Cloud and Claude

In the Google Web OAuth client, Authorized redirect URIs must include exactly:

```text
https://youtube-intelligence-vbyf.onrender.com/oauth/callback
```

If it already matches, no Google Cloud change is required for these fixes. Claude's callback is
registered with this server through MCP DCR, not pasted into Google's Web client. Existing test-user
and scope requirements remain as described in DEPLOY_RENDER.md.

After deployment, close the stuck consent tab and start a fresh sign-in from the Claude connector.
The previous form may already have consumed its one-use transaction, and an open tab retains its
old CSP. Use `https://youtube-intelligence-vbyf.onrender.com/mcp/`, Streamable HTTP, Sign In When
Needed, Register Automatically. Click Allow this client in the new flow. Public tools remain
anonymous; account tools use your own Google sign-in.

## Verification and limits

Linux offline pytest: 220 passed, 10 optional PostgreSQL tests skipped; 91.22% coverage.
Ruff/format checks and Chromium browser regression passed. The old self-only policy was reproduced
as a browser failure in an isolated copy, then the fixed callback and code exchange passed.
Google write-consent navigation is intercepted with synthetic content; no live Google calls occur.
Native Windows and hosted Render/Google were not run here. Re-run the included Windows GitHub
Actions job to obtain native Windows evidence. Existing upstream TestClient deprecation warnings
are informational; no dependency replacement was required for the reported test failure.
