CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS backends (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    display_name TEXT NOT NULL,
    config TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT,
    last_error TEXT
);

CREATE TABLE IF NOT EXISTS backend_credentials (
    id TEXT PRIMARY KEY,
    backend_id TEXT NOT NULL UNIQUE REFERENCES backends(id) ON DELETE CASCADE,
    ciphertext BLOB NOT NULL,
    key_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT
);

CREATE TABLE IF NOT EXISTS chat_sessions (
    id TEXT PRIMARY KEY,
    backend_id TEXT NOT NULL REFERENCES backends(id) ON DELETE CASCADE,
    title TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT,
    model TEXT
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL,
    model TEXT,
    tokens_in INTEGER,
    tokens_out INTEGER
);

CREATE INDEX IF NOT EXISTS idx_chat_messages_session ON chat_messages(session_id);

CREATE TABLE IF NOT EXISTS live_sessions (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    backend_id TEXT NOT NULL,
    state TEXT NOT NULL,
    started_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS onboarding (
    id TEXT PRIMARY KEY,
    current_step TEXT NOT NULL,
    selected_backend_kind TEXT,
    created_backend_id TEXT,
    error TEXT
);
