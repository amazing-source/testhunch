-- The test both failed and passed within this run, e.g. on a retry (docs/adr/0005).
-- Results recorded before this migration were never marked, so they default to not flaky.
ALTER TABLE results ADD COLUMN flaky BOOLEAN NOT NULL DEFAULT false;
