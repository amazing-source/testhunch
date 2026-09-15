-- A token that opens one repository and nothing else (docs/adr/0022).
--
-- Only the SHA-256 of the token is kept. A token is 32 random bytes, so there is no password to
-- guess and no reason for a slow hash; but a database that leaks must not hand over working keys.
CREATE TABLE api_tokens (
    id           BIGINT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    repo         TEXT        NOT NULL,
    token_sha256 TEXT        NOT NULL UNIQUE,
    label        TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_at   TIMESTAMPTZ
);

CREATE INDEX api_tokens_by_repo ON api_tokens (repo, id);
