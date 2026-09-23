"""Remove the redundant local card-owner mapping table."""


def migrate(migrator, database, fake=False, **kwargs):
    migrator.sql('DROP TABLE IF EXISTS "access_card_owner"')


def rollback(migrator, database, fake=False, **kwargs):
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
