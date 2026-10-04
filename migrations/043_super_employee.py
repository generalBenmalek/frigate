"""Grant explicitly selected employees access to every portal door."""


def migrate(migrator, database, fake=False, **kwargs):
    """Keep existing employees restricted to their assigned doors."""
    migrator.sql(
        "ALTER TABLE employee ADD COLUMN super_employee INTEGER NOT NULL DEFAULT 0"
    )


def rollback(migrator, database, fake=False, **kwargs):
    """Remove the all-door privilege without changing door assignments."""
    migrator.sql("ALTER TABLE employee DROP COLUMN super_employee")
