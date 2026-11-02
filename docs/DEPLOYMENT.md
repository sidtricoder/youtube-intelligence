# Free deployment and operation

## Recommended: your existing laptop or desktop

Follow README's Windows/Linux instructions. The server binds **127.0.0.1:8000**, so it is accessible only on that computer. Software and metadata scoring require no paid subscription. Real Google API use is constrained to your project's free quota; there is no paid API-key dependency. Your existing internet/electricity/hardware costs still apply.

This is a complete deployment, not just a development screenshot: encrypted SQLite persists drafts, tokens, cache and quota; the server can be stopped/restarted without losing them. Keep one process. Do not use uvicorn `--reload` for a long-running deployment. For automatic start, use Windows Task Scheduler (run the full path to `.venv\Scripts\python.exe -m ytintel` with project folder as working directory) or your OS service manager with the project folder as WorkingDirectory. Do not put keys in command-line arguments.

## Optional: Docker Engine + Compose

Use a compatible free container engine for your situation; Docker Desktop's license eligibility is your responsibility. Docker is not necessary for the free Python path.

1. Generate `.env` using `python scripts/bootstrap.py` after installing the Python dependencies. The private ZIP already includes the Google configuration in .env.
2. From the project root:

   ```bash
   docker compose up --build -d
   docker compose logs --tail=30
   ```

3. Open http://localhost:8000. The port remains bound only to loopback. A named volume persists `/app/data` across container replacement. The container runs as UID 10001.
4. Stop with `docker compose down`. **Do not add `-v` unless you intend to erase the database.** Keep the original `.env` because its encryption key is required to decrypt that volume.

The image installs the exact tested dependency lock (which includes development tools) for reproducibility. The Python install and test flow is verified in the delivered environment; container build/run requires Docker on your host and is not claimed to have been executed in a Docker daemon here.

## Access from another device, without buying hosting

If you already have an always-on Linux computer and SSH access, run this app there and use a private SSH tunnel from your computer:

```bash
ssh -L 8000:127.0.0.1:8000 your-user@your-existing-server
```

Then browse http://localhost:8000 locally; the server still listens only on its own loopback. A `localhost` OAuth callback can traverse that tunnel. If your local port differs, update the tunnel, application redirect URI and Google client redirect URI together. This assumes an existing host and SSH access; it does not provision a free VPS.

## Public hosting

No indefinitely free third-party tier is guaranteed. This deliverable does not require one, and does not claim that a sleeping/ephemeral free web host safely persists OAuth tokens or SQLite. If you choose public deployment, you must add HTTPS, persistent storage, strong private access controls, correct trusted hosts/proxy settings and a Google-registered HTTPS callback. The application uses private bearer credentials and is **not** a public multi-user OAuth resource server. A cloud-only ChatGPT client needs a reachable secured endpoint and compatible authentication; localhost cannot be reached from the cloud.

## Backups and upgrades

Stop the app, back up `data/ytintel.db` and `.env` separately in private encrypted storage, then restart. Restore the matching database and encryption key together. Backups contain personal data; never put them in public git or share them with teammates. Disconnect can clear current local records and revoke Google tokens, but cannot erase your external backups. Run offline tests after upgrades. No automatic database migration is needed for this initial schema.

## Troubleshooting

| Symptom | Action |
|---|---|
| Missing settings / invalid key | Use the configured `.env` from the private ZIP; run from project root |
| `unauthorized` | Use owner key in owner page, API key in MCP; check trailing spaces |
| `owner_required` | MCP/API key cannot approve; approve manually in owner page |
| `redirect_uri_mismatch` | Match Google registered URI and `.env` exactly |
| `reauthorization_required` | Connect Google again; Testing refresh tokens may expire |
| `channel_required` | Create a YouTube channel for that Google account |
| `quota_exceeded` | Stop requests; check local ledger and Console; wait for Pacific midnight |
| `no_matches` | Try another topic or explicitly revise runtime/language constraints |
| `partial` | Fix reported error; review and explicitly resume before draft expiry |
| `uncertain` or stuck `writing` | Inspect actual YouTube playlist manually; no blind retry |
| Cannot decrypt after replacing `.env` | Restore original encryption key or intentionally start a clean DB |
| AI cannot reach localhost | Use a local MCP client or included Python MCP client |
