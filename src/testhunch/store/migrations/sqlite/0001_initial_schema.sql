-- One row per ingested CI run (one or more report files for one commit).
-- AUTOINCREMENT keeps ids increasing even after old runs are deleted: "recent" means highest id.
CREATE TABLE runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    repo          TEXT    NOT NULL,
    commit_sha    TEXT    NOT NULL,
    branch        TEXT,
    base_sha      TEXT,
    report_digest TEXT    NOT NULL,
    ingested_at   TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (repo, commit_sha, report_digest)
) STRICT;

CREATE INDEX runs_by_repo ON runs (repo, id);
CREATE INDEX runs_by_commit ON runs (repo, commit_sha);

-- A test's identity within a repository. test_key is the parser's normalized key.
CREATE TABLE tests (
    id       INTEGER PRIMARY KEY,
    repo     TEXT NOT NULL,
    test_key TEXT NOT NULL,
    name     TEXT NOT NULL,
    suite    TEXT,
    file     TEXT,
    UNIQUE (repo, test_key)
) STRICT;

-- One outcome per test per run.
CREATE TABLE results (
    run_id      INTEGER NOT NULL REFERENCES runs (id) ON DELETE CASCADE,
    test_id     INTEGER NOT NULL REFERENCES tests (id),
    status      TEXT    NOT NULL CHECK (status IN ('passed', 'failed', 'error', 'skipped')),
    duration_ms INTEGER CHECK (duration_ms >= 0),
    occurrences INTEGER NOT NULL DEFAULT 1 CHECK (occurrences >= 1),
    message     TEXT,
    PRIMARY KEY (run_id, test_id)
) STRICT;

CREATE INDEX results_by_test ON results (test_id);

-- Files changed between the run's base and its commit (git diff --name-status letters).
CREATE TABLE run_changes (
    run_id      INTEGER NOT NULL REFERENCES runs (id) ON DELETE CASCADE,
    path        TEXT    NOT NULL,
    change_type TEXT    NOT NULL CHECK (change_type IN ('A', 'C', 'D', 'M', 'R', 'T', 'U', 'X')),
    old_path    TEXT,
    PRIMARY KEY (run_id, path)
) STRICT;
