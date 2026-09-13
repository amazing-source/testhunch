-- How many times the test ran in the run, retries included (docs/adr/0008). Results recorded
-- before this migration were parsed without counting retries, so their attempts stay unknown.
ALTER TABLE results ADD COLUMN attempts INTEGER CHECK (attempts >= 1);
