-- A ranking recorded for a commit before its tests ran, so that shadow mode can measure what
-- skipping tests would have missed (docs/adr/0006).
CREATE TABLE predictions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    repo        TEXT    NOT NULL,
    commit_sha  TEXT    NOT NULL,
    base_sha    TEXT,
    -- The newest run in the history the ranking came from: only later runs are compared with it.
    last_run_id INTEGER NOT NULL REFERENCES runs (id) ON DELETE CASCADE,
    recorded_at TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
) STRICT;

CREATE INDEX predictions_by_commit ON predictions (repo, commit_sha);

-- Where each known test stood in that ranking.
CREATE TABLE prediction_positions (
    prediction_id INTEGER NOT NULL REFERENCES predictions (id) ON DELETE CASCADE,
    test_id       INTEGER NOT NULL REFERENCES tests (id),
    position      INTEGER NOT NULL CHECK (position >= 1),
    score         REAL    NOT NULL,
    PRIMARY KEY (prediction_id, test_id)
) STRICT;
