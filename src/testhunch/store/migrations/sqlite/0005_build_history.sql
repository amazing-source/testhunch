-- A build is every run of one commit, numbered per repository in the order of its first run
-- (docs/adr/0015).
CREATE TABLE builds (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    repo       TEXT    NOT NULL,
    commit_sha TEXT    NOT NULL,
    number     INTEGER NOT NULL CHECK (number >= 0),
    UNIQUE (repo, commit_sha),
    UNIQUE (repo, number)
) STRICT;

-- A test's outcome in one build, across the build's runs, and the durations reported for it.
CREATE TABLE build_tests (
    build_id        INTEGER NOT NULL REFERENCES builds (id) ON DELETE CASCADE,
    test_id         INTEGER NOT NULL REFERENCES tests (id),
    failed          INTEGER NOT NULL CHECK (failed IN (0, 1)),
    duration_sum_ms INTEGER NOT NULL CHECK (duration_sum_ms >= 0),
    duration_count  INTEGER NOT NULL CHECK (duration_count >= 0),
    PRIMARY KEY (build_id, test_id)
) STRICT;

-- A test's history over the builds it passed or failed in, kept up to date at ingest.
-- priority is RTPTorrent's failure priority as of last_failure (docs/adr/0014, 0015);
-- duration_total_ms sums each build's mean duration, rounded half to even.
CREATE TABLE test_history (
    test_id           INTEGER PRIMARY KEY REFERENCES tests (id),
    builds            INTEGER NOT NULL CHECK (builds >= 1),
    failures          INTEGER NOT NULL CHECK (failures >= 0),
    last_failure      INTEGER CHECK (last_failure >= 0),
    priority          REAL    NOT NULL CHECK (priority >= 0),
    duration_total_ms INTEGER NOT NULL CHECK (duration_total_ms >= 0),
    duration_builds   INTEGER NOT NULL CHECK (duration_builds >= 0)
) STRICT;
