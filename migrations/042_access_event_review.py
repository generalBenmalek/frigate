"""Add shared access-event decisions and immutable review history."""


def migrate(migrator, database, fake=False, **kwargs):
    """Preserve existing events as unreviewed."""
    for statement in (
        "ALTER TABLE access_event ADD COLUMN review_status VARCHAR(20)",
        "ALTER TABLE access_event ADD COLUMN reviewed_at REAL",
        "ALTER TABLE access_event ADD COLUMN reviewed_by VARCHAR(100)",
        "ALTER TABLE access_event ADD COLUMN review_revision INTEGER NOT NULL DEFAULT 0",
        """CREATE TABLE access_event_review (
            id INTEGER PRIMARY KEY, event_id VARCHAR(64) NOT NULL,
            revision INTEGER NOT NULL, reviewer VARCHAR(100) NOT NULL,
            reviewed_at REAL NOT NULL, previous_status VARCHAR(20) NOT NULL,
            status VARCHAR(20) NOT NULL, action VARCHAR(20) NOT NULL
        )""",
        "CREATE INDEX access_event_review_event_id ON access_event_review (event_id)",
        "CREATE UNIQUE INDEX access_event_review_revision ON access_event_review (event_id, revision)",
    ):
        migrator.sql(statement)


def rollback(migrator, database, fake=False, **kwargs):
    """Remove review metadata without deleting access events."""
    migrator.sql("DROP TABLE IF EXISTS access_event_review")
    for column in ("review_status", "reviewed_at", "reviewed_by", "review_revision"):
        migrator.sql(f"ALTER TABLE access_event DROP COLUMN {column}")
