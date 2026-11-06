-- Fresh multi-tenant schema; use python -m ytintel.migrate for version checks.
CREATE SCHEMA IF NOT EXISTS ytintel;
CREATE TABLE IF NOT EXISTS ytintel.access_tokens (
	digest VARCHAR NOT NULL, 
	user_id VARCHAR, 
	payload BYTEA NOT NULL, 
	expires FLOAT NOT NULL, 
	PRIMARY KEY (digest)
);

CREATE TABLE IF NOT EXISTS ytintel.auth_codes (
	digest VARCHAR NOT NULL, 
	user_id VARCHAR, 
	payload BYTEA NOT NULL, 
	expires FLOAT NOT NULL, 
	PRIMARY KEY (digest)
);

CREATE TABLE IF NOT EXISTS ytintel.drafts (
	user_id VARCHAR NOT NULL, 
	k VARCHAR NOT NULL, 
	v BYTEA NOT NULL, 
	expires FLOAT NOT NULL, 
	PRIMARY KEY (user_id, k)
);

CREATE TABLE IF NOT EXISTS ytintel.kv (
	k VARCHAR NOT NULL, 
	v BYTEA NOT NULL, 
	expires FLOAT NOT NULL, 
	PRIMARY KEY (k)
);

CREATE TABLE IF NOT EXISTS ytintel.login_transactions (
	digest VARCHAR NOT NULL, 
	user_id VARCHAR, 
	payload BYTEA NOT NULL, 
	expires FLOAT NOT NULL, 
	PRIMARY KEY (digest)
);

CREATE TABLE IF NOT EXISTS ytintel.oauth_clients (
	client_id VARCHAR NOT NULL, 
	user_id VARCHAR, 
	payload BYTEA NOT NULL, 
	expires FLOAT NOT NULL, 
	PRIMARY KEY (client_id)
);

CREATE TABLE IF NOT EXISTS ytintel.public_cache (
	k VARCHAR NOT NULL, 
	v BYTEA NOT NULL, 
	expires FLOAT NOT NULL, 
	PRIMARY KEY (k)
);

CREATE TABLE IF NOT EXISTS ytintel.quota (
	day VARCHAR NOT NULL, 
	units INTEGER NOT NULL, 
	searches INTEGER NOT NULL, 
	PRIMARY KEY (day)
);

CREATE TABLE IF NOT EXISTS ytintel.quota_ledger (
	day VARCHAR NOT NULL, 
	context_key VARCHAR NOT NULL, 
	user_id VARCHAR, 
	units INTEGER NOT NULL, 
	searches INTEGER NOT NULL, 
	PRIMARY KEY (day, context_key)
);

CREATE TABLE IF NOT EXISTS ytintel.refresh_tokens (
	digest VARCHAR NOT NULL, 
	user_id VARCHAR, 
	payload BYTEA NOT NULL, 
	expires FLOAT NOT NULL, 
	PRIMARY KEY (digest)
);

CREATE TABLE IF NOT EXISTS ytintel.schema_migrations (
	version SERIAL NOT NULL, 
	applied_at FLOAT NOT NULL, 
	PRIMARY KEY (version)
);

CREATE TABLE IF NOT EXISTS ytintel.tenant_cache (
	user_id VARCHAR NOT NULL, 
	k VARCHAR NOT NULL, 
	v BYTEA NOT NULL, 
	expires FLOAT NOT NULL, 
	PRIMARY KEY (user_id, k)
);

CREATE TABLE IF NOT EXISTS ytintel.token_families (
	family VARCHAR NOT NULL, 
	user_id VARCHAR, 
	payload BYTEA NOT NULL, 
	expires FLOAT NOT NULL, 
	PRIMARY KEY (family)
);

CREATE TABLE IF NOT EXISTS ytintel.user_google_tokens (
	user_id VARCHAR NOT NULL, 
	payload BYTEA NOT NULL, 
	PRIMARY KEY (user_id)
);

CREATE TABLE IF NOT EXISTS ytintel.users (
	user_id VARCHAR NOT NULL, 
	google_sub VARCHAR NOT NULL, 
	generation INTEGER DEFAULT '0' NOT NULL, 
	PRIMARY KEY (user_id), 
	UNIQUE (google_sub)
);

CREATE TABLE IF NOT EXISTS ytintel.web_sessions (
	digest VARCHAR NOT NULL, 
	user_id VARCHAR, 
	payload BYTEA NOT NULL, 
	expires FLOAT NOT NULL, 
	PRIMARY KEY (digest)
);
