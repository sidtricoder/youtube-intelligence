# Google-only integration plan

> Execute inline, as requested; deliver updated ZIP including private .env and .gitignore.

Goal: Remove the runtime demo provider and integrate the supplied Google project credentials.
Architecture: Always use official GoogleProvider in production. Public metadata may use the supplied YouTube API key; private reads and all writes still require OAuth consent. Retain synthetic fixtures only under tests. Include credentials in the private delivery because the user explicitly requested this; never put them in source, tests, logs or report text.

- [x] Write failing tests: no runtime demo module; default Google composition; public API-key access without OAuth; personal/write endpoints never use API key alone; credential importer; no secrets in safe errors.
- [x] Move synthetic provider to test utilities, remove runtime mode and update all app/browser/MCP test composition.
- [x] Implement public API-key routing and stable Google configuration errors; keep existing OAuth write confirmation.
- [x] Add safe JSON credential import/setup, .env and Git exclusions; update UI/docs to live-only use.
- [x] Run full offline Python suite, lint, browser test, live public checks and OAuth readiness checks with bounded quota. Report failures/blocked checks explicitly.
- [x] Review and package the private project with its .env, verify archive and replace the existing Library ZIP.

Review focus: API key cannot read private data or approve writes; test fixtures cannot silently run live; actual keys never appear in reports; OAuth redirect needs registration; end-to-end private workflows need the user's sign-in.
