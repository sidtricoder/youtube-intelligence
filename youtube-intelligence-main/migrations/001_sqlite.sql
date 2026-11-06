-- Fresh multi-tenant schema; use python -m ytintel.migrate for version checks.
CREATE TABLE IF NOT EXISTS access_tokens (
	digest VARCHAR NOT NULL, 
	user_id VARCHAR, 
	payload BLOB NOT NULL, 
	expires FLOAT NOT NULL, 
	PRIMARY KEY (digest)
);

CREATE TABLE IF NOT EXISTS auth_codes (
	digest VARCHAR NOT NULL, 
	user_id VARCHAR, 
	payload BLOB NOT NULL, 
	expires FLOAT NOT NULL, 
	PRIMARY KEY (digest)
);

CREATE TABLE IF NOT EXISTS drafts (
	user_id VARCHAR NOT NULL, 
	k VARCHAR NOT NULL, 
	v BLOB NOT NULL, 
	expires FLOAT NOT NULL, 
	PRIMARY KEY (user_id, k)
);

CREATE TABLE IF NOT EXISTS kv (
	k VARCHAR NOT NULL, 
	v BLOB NOT NULL, 
	expires FLOAT NOT NULL, 
	PRIMARY KEY (k)
);

CREATE TABLE IF NOT EXISTS login_transactions (
	digest VARCHAR NOT NULL, 
	user_id VARCHAR, 
	payload BLOB NOT NULL, 
	expires FLOAT NOT NULL, 
	PRIMARY KEY (digest)
);

CREATE TABLE IF NOT EXISTS oauth_clients (
	client_id VARCHAR NOT NULL, 
	user_id VARCHAR, 
	payload BLOB NOT NULL, 
	expires FLOAT NOT NULL, 
	PRIMARY KEY (client_id)
);

CREATE TABLE IF NOT EXISTS public_cache (
	k VARCHAR NOT NULL, 
	v BLOB NOT NULL, 
	expires FLOAT NOT NULL, 
	PRIMARY KEY (k)
);

CREATE TABLE IF NOT EXISTS quota (
	day VARCHAR NOT NULL, 
	units INTEGER NOT NULL, 
	searches INTEGER NOT NULL, 
	PRIMARY KEY (day)
);

CREATE TABLE IF NOT EXISTS quota_ledger (
	day VARCHAR NOT NULL, 
	context_key VARCHAR NOT NULL, 
	user_id VARCHAR, 
	units INTEGER NOT NULL, 
	searches INTEGER NOT NULL, 
	PRIMARY KEY (day, context_key)
);

CREATE TABLE IF NOT EXISTS refresh_tokens (
	digest VARCHAR NOT NULL, 
	user_id VARCHAR, 
	payload BLOB NOT NULL, 
	expires FLOAT NOT NULL, 
	PRIMARY KEY (digest)
);

CREATE TABLE IF NOT EXISTS schema_migrations (
	version INTEGER NOT NULL, 
	applied_at FLOAT NOT NULL, 
	PRIMARY KEY (version)
);

CREATE TABLE IF NOT EXISTS tenant_cache (
	user_id VARCHAR NOT NULL, 
	k VARCHAR NOT NULL, 
	v BLOB NOT NULL, 
	expires FLOAT NOT NULL, 
	PRIMARY KEY (user_id, k)
);

CREATE TABLE IF NOT EXISTS token_families (
	family VARCHAR NOT NULL, 
	user_id VARCHAR, 
	payload BLOB NOT NULL, 
	expires FLOAT NOT NULL, 
	PRIMARY KEY (family)
);

CREATE TABLE IF NOT EXISTS user_google_tokens (
	user_id VARCHAR NOT NULL, 
	payload BLOB NOT NULL, 
	PRIMARY KEY (user_id)
);

CREATE TABLE IF NOT EXISTS users (
	user_id VARCHAR NOT NULL, 
	google_sub VARCHAR NOT NULL, 
	generation INTEGER DEFAULT '0' NOT NULL, 
	PRIMARY KEY (user_id), 
	UNIQUE (google_sub)
);

CREATE TABLE IF NOT EXISTS web_sessions (
	digest VARCHAR NOT NULL, 
	user_id VARCHAR, 
	payload BLOB NOT NULL, 
	expires FLOAT NOT NULL, 
	PRIMARY KEY (digest)
);
