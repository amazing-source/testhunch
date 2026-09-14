-- What the ranking expected each test to cost when it was recorded, so that shadow mode can cut a
-- time budget with the durations known before the run, not the run's own (docs/adr/0017).
-- Rankings recorded before this migration have none: those runs are left out of time budgets.
ALTER TABLE prediction_positions ADD COLUMN expected_ms REAL CHECK (expected_ms >= 0);
