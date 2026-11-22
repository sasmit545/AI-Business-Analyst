CREATE SCHEMA IF NOT EXISTS analyst_meta AUTHORIZATION postgres;
REVOKE ALL ON SCHEMA analyst_meta FROM PUBLIC, ai_analyst, analyst_writer;
GRANT USAGE ON SCHEMA analyst_meta TO analyst_writer;

CREATE TABLE IF NOT EXISTS analyst_meta.control (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    scenario text NOT NULL CHECK (scenario IN
        ('scenario_a', 'scenario_b', 'scenario_a_dirty', 'phase2_baseline', 'phase2_incident', 'lifecycle_v1')),
    generation bigint NOT NULL CHECK (generation > 0),
    import_epoch bigint NOT NULL CHECK (import_epoch > 0),
    ready boolean NOT NULL
);
