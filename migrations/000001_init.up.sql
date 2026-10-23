CREATE SCHEMA pravkiapp;

CREATE TABLE pravkiapp.users (
    id              SERIAL PRIMARY KEY,
    version         BIGINT NOT NULL DEFAULT 1,
    username        VARCHAR(30) NOT NULL,
    password_hash   TEXT NOT NULL,
    email           VARCHAR(254) NOT NULL UNIQUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT users_username_format CHECK (username ~ '^[A-Za-z0-9_]{3,30}$'),
    CONSTRAINT users_password_hash_len CHECK (length(password_hash) = 60),
    CONSTRAINT users_email_lowercase CHECK (email = lower(email)),
    CONSTRAINT users_email_format CHECK (email ~ '^[a-z0-9._+-]+@([a-z0-9-]+\.)+[a-z]{2,}$')
);

CREATE UNIQUE INDEX users_username_lower_uidx ON pravkiapp.users (lower(username));

CREATE TABLE pravkiapp.sessions (
    token_hash BYTEA PRIMARY KEY CHECK (octet_length(token_hash) = 32),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
    CHECK (expires_at > created_at),

    user_id    INT NOT NULL REFERENCES pravkiapp.users(id) ON DELETE CASCADE
);

CREATE INDEX sessions_user_id_idx    ON pravkiapp.sessions (user_id);
CREATE INDEX sessions_expires_at_idx ON pravkiapp.sessions (expires_at);
