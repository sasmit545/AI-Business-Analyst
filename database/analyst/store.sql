CREATE TABLE IF NOT EXISTS analyst_meta.evidence (
    id text PRIMARY KEY,
    session_id text NOT NULL,
    investigation_id text NOT NULL,
    version integer NOT NULL,
    step text NOT NULL,
    payload jsonb NOT NULL,
    UNIQUE (session_id, investigation_id, version, step)
);

CREATE TABLE IF NOT EXISTS analyst_meta.budgets (
    session_id text NOT NULL,
    investigation_id text NOT NULL,
    deadline timestamptz NOT NULL,
    statements integer NOT NULL,
    tools integer NOT NULL,
    repairs integer NOT NULL,
    tokens integer NOT NULL,
    PRIMARY KEY (session_id, investigation_id)
);

CREATE TABLE IF NOT EXISTS analyst_meta.bundles (
    session_id text NOT NULL,
    investigation_id text NOT NULL,
    version integer NOT NULL,
    request jsonb NOT NULL,
    generation bigint NOT NULL,
    import_epoch bigint NOT NULL,
    initial_statements integer NOT NULL,
    receipt jsonb,
    digest text,
    CHECK ((receipt IS NULL) = (digest IS NULL)),
    PRIMARY KEY (session_id, investigation_id, version)
);
