from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from app.config import get_settings
from app.utils.json_tools import derive_title


def get_database_backend() -> str:
    return "sqlite"


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    settings = get_settings()
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(settings.database_path)
    connection.row_factory = sqlite3.Row
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def initialize_database(database_path: Path | None = None) -> None:
    settings = get_settings()
    path = database_path or settings.database_path
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    try:
        connection.executescript(SCHEMA_SQL)
        _migrate_conversations(connection)
        connection.commit()
    finally:
        connection.close()


def _column_exists(connection: sqlite3.Connection, table: str, column: str) -> bool:
    return any(row["name"] == column for row in connection.execute(f"PRAGMA table_info({table})"))


def _derive_conversation_title(raw_prompt: str | None, task_type: str | None) -> str:
    return derive_title(raw_prompt, empty_default=(task_type or "Prompt").strip() or "Prompt")


def _migrate_conversations(connection: sqlite3.Connection) -> None:
    """Add conversation_id to prompt_history and backfill orphan runs into
    single-turn conversations so existing history shows up in the chat list."""
    if not _column_exists(connection, "prompt_history", "conversation_id"):
        connection.execute("ALTER TABLE prompt_history ADD COLUMN conversation_id TEXT")

    # Index must be created after the column exists (it is absent from
    # SCHEMA_SQL precisely so an upgraded DB doesn't fail here).
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_prompt_history_conversation_id ON prompt_history(conversation_id)"
    )

    orphans = connection.execute(
        """
        SELECT id, user_id, raw_prompt, task_type, created_at
        FROM prompt_history
        WHERE conversation_id IS NULL
        ORDER BY created_at ASC
        """
    ).fetchall()
    for row in orphans:
        conversation_id = str(uuid4())
        title = _derive_conversation_title(row["raw_prompt"], row["task_type"])
        connection.execute(
            """
            INSERT INTO conversations (id, user_id, title, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (conversation_id, row["user_id"], title, row["created_at"], row["created_at"]),
        )
        connection.execute(
            "UPDATE prompt_history SET conversation_id = ? WHERE id = ?",
            (conversation_id, row["id"]),
        )


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS api_keys (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    name TEXT NOT NULL,
    key_prefix TEXT NOT NULL,
    key_hash TEXT NOT NULL,
    revoked INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    last_used_at TEXT,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    title TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS prompt_history (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    raw_prompt TEXT NOT NULL,
    intent_json TEXT NOT NULL,
    task_type TEXT,
    target_model TEXT,
    conversation_id TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (conversation_id) REFERENCES conversations(id)
);

CREATE TABLE IF NOT EXISTS prompt_versions (
    id TEXT PRIMARY KEY,
    history_id TEXT NOT NULL,
    label TEXT NOT NULL,
    strategy TEXT,
    version_text TEXT NOT NULL,
    model TEXT,
    is_winner INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (history_id) REFERENCES prompt_history(id)
);

CREATE TABLE IF NOT EXISTS prompt_scores (
    id TEXT PRIMARY KEY,
    version_id TEXT NOT NULL,
    clarity INTEGER,
    specificity INTEGER,
    completeness INTEGER,
    context_strength INTEGER,
    constraint_quality INTEGER,
    output_control INTEGER,
    safety INTEGER,
    usefulness INTEGER,
    total INTEGER NOT NULL,
    score_json TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (version_id) REFERENCES prompt_versions(id)
);

CREATE TABLE IF NOT EXISTS feedback (
    id TEXT PRIMARY KEY,
    version_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    rating INTEGER NOT NULL,
    comment TEXT,
    outcome TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (version_id) REFERENCES prompt_versions(id),
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS agent_outputs (
    id TEXT PRIMARY KEY,
    history_id TEXT NOT NULL,
    agent_name TEXT NOT NULL,
    output_json TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (history_id) REFERENCES prompt_history(id)
);

CREATE INDEX IF NOT EXISTS idx_api_keys_user_id ON api_keys(user_id);
CREATE INDEX IF NOT EXISTS idx_conversations_user_id ON conversations(user_id);
CREATE INDEX IF NOT EXISTS idx_prompt_history_user_id ON prompt_history(user_id);
CREATE INDEX IF NOT EXISTS idx_prompt_versions_history_id ON prompt_versions(history_id);
CREATE INDEX IF NOT EXISTS idx_prompt_scores_version_id ON prompt_scores(version_id);
CREATE INDEX IF NOT EXISTS idx_feedback_user_id ON feedback(user_id);
CREATE INDEX IF NOT EXISTS idx_agent_outputs_history_id ON agent_outputs(history_id);
"""
