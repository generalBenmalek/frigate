"""Store card owners, controller checks, and access event verification."""


def migrate(migrator, database, fake=False, **kwargs):
    migrator.sql(
        'ALTER TABLE "access_control" ADD COLUMN "seconds_before" INTEGER NOT NULL DEFAULT 10'
    )
    migrator.sql(
        'ALTER TABLE "access_control" ADD COLUMN "seconds_after" INTEGER NOT NULL DEFAULT 10'
    )
    migrator.sql('ALTER TABLE "access_control" ADD COLUMN "last_checked_at" REAL NULL')
    migrator.sql(
        'ALTER TABLE "access_control" ADD COLUMN "event_tracking_started_at" REAL NULL'
    )
    migrator.sql('ALTER TABLE "access_control" ADD COLUMN "last_event_poll" REAL NULL')
    migrator.sql(
        'CREATE TABLE "access_card_owner" ('
        '"id" INTEGER NOT NULL PRIMARY KEY, '
        '"device_id" VARCHAR(30) NOT NULL, '
        '"card_number" VARCHAR(100) NOT NULL, '
        '"face_name" VARCHAR(100) NOT NULL)'
    )
    migrator.sql(
        'CREATE UNIQUE INDEX "access_card_owner_unique" '
        'ON "access_card_owner" ("device_id", "card_number", "face_name")'
    )
    migrator.sql(
        'CREATE INDEX "access_card_owner_device" ON "access_card_owner" ("device_id")'
    )
    migrator.sql(
        'CREATE TABLE "access_event" ('
        '"id" VARCHAR(64) NOT NULL PRIMARY KEY, '
        '"device_id" VARCHAR(30) NOT NULL, '
        '"occurred_at" REAL NOT NULL, '
        '"card_number" VARCHAR(100), '
        '"raw_record" TEXT NOT NULL, '
        "\"verification_status\" VARCHAR(20) NOT NULL DEFAULT 'unverified', "
        '"people" TEXT NOT NULL, '
        '"camera" VARCHAR(100), '
        '"seconds_before" INTEGER NOT NULL DEFAULT 10, '
        '"seconds_after" INTEGER NOT NULL DEFAULT 10)'
    )
    migrator.sql('CREATE INDEX "access_event_device" ON "access_event" ("device_id")')
    migrator.sql(
        'CREATE INDEX "access_event_occurred" ON "access_event" ("occurred_at")'
    )


def rollback(migrator, database, fake=False, **kwargs):
    migrator.sql('DROP TABLE IF EXISTS "access_event"')
    migrator.sql('DROP TABLE IF EXISTS "access_card_owner"')
