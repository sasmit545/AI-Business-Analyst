CREATE TABLE IF NOT EXISTS analyst_meta.sessions (
    session_id text PRIMARY KEY,
    subject text NOT NULL,
    scenario text NOT NULL,
    generation bigint NOT NULL,
    import_epoch bigint NOT NULL,
    key_digest text NOT NULL,
    owner_token text NOT NULL,
    revoked boolean NOT NULL DEFAULT false
);

CREATE TABLE IF NOT EXISTS analyst_meta.investigations (
    session_id text NOT NULL REFERENCES analyst_meta.sessions(session_id),
    investigation_id text NOT NULL,
    state jsonb NOT NULL,
    PRIMARY KEY (session_id, investigation_id)
);
