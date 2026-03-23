"""
Migration script: Add view_token column to records table.

Connects to the SQLite database, adds a view_token (UUID4) column to the
records table, backfills existing records with unique UUIDs, and creates
a unique index for efficient lookups.

Requirements: 1.1, 1.2, 1.3
"""
import sqlite3
import uuid
import os
import sys
from typing import Optional


def get_db_path() -> str:
    """Resolve the database file path."""
    # Support DATABASE_URL env var (sqlite:///./data/era.db format)
    db_url = os.getenv("DATABASE_URL", "sqlite:///./data/era.db")
    if db_url.startswith("sqlite:///"):
        return db_url[len("sqlite:///"):]
    return "data/era.db"


def migrate(db_path: Optional[str] = None) -> None:
    """Run the view_token migration.

    1. Add view_token column (VARCHAR(36), nullable temporarily for ALTER TABLE)
    2. Backfill existing records with unique UUID4 values
    3. Create a unique index on view_token
    """
    if db_path is None:
        db_path = get_db_path()

    if not os.path.exists(db_path):
        print(f"Error: Database file not found at '{db_path}'")
        sys.exit(1)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        # Check if column already exists
        cursor.execute("PRAGMA table_info(records)")
        columns = [col[1] for col in cursor.fetchall()]

        if "view_token" in columns:
            print("view_token column already exists, skipping ALTER TABLE.")
        else:
            # Step 1: Add the column
            cursor.execute(
                "ALTER TABLE records ADD COLUMN view_token VARCHAR(36)"
            )
            print("Added view_token column to records table.")

        # Step 2: Backfill NULL view_tokens with unique UUID4 values
        cursor.execute("SELECT id FROM records WHERE view_token IS NULL")
        rows = cursor.fetchall()

        if rows:
            for (record_id,) in rows:
                token = str(uuid.uuid4())
                cursor.execute(
                    "UPDATE records SET view_token = ? WHERE id = ?",
                    (token, record_id),
                )
            print(f"Backfilled {len(rows)} record(s) with UUID4 view_tokens.")
        else:
            print("No records need backfilling.")

        # Step 3: Create unique index (IF NOT EXISTS for idempotency)
        cursor.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_records_view_token "
            "ON records (view_token)"
        )
        print("Created unique index ix_records_view_token.")

        conn.commit()
        print("Migration completed successfully.")

    except Exception as e:
        conn.rollback()
        print(f"Migration failed: {e}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    migrate()
