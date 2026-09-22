"""Peewee migrations -- 036_create_access_control_table.py."""

import peewee as pw

SQL = pw.SQL


def migrate(migrator, database, fake=False, **kwargs):

    # Remove old employee/group tables
    migrator.sql(
        'DROP TABLE IF EXISTS "employee"'
    )

    migrator.sql(
        'DROP TABLE IF EXISTS "group"'
    )

    # Create access control table
    migrator.sql(
        """
        CREATE TABLE IF NOT EXISTS "access_control" (
            "id" VARCHAR(30) NOT NULL PRIMARY KEY,
            "name" VARCHAR(100) NOT NULL,
            "ip_address" VARCHAR(45) NOT NULL,
            "type" VARCHAR(50) NOT NULL,
            "model" VARCHAR(100) NOT NULL,
            "port" INTEGER NOT NULL DEFAULT 37777,
            "channel_count" INTEGER NOT NULL DEFAULT 1,
            "serial_number" VARCHAR(100) NOT NULL,
            "username" VARCHAR(100) NOT NULL,
            "password" VARCHAR(255) NOT NULL,
            "status" VARCHAR(20) NOT NULL DEFAULT 'offline',
            "associated_camera" VARCHAR(100)
        )
        """
    )

    # Useful indexes
    migrator.sql(
        'CREATE INDEX IF NOT EXISTS '
        '"access_control_name" '
        'ON "access_control" ("name")'
    )

    migrator.sql(
        'CREATE INDEX IF NOT EXISTS '
        '"access_control_ip_address" '
        'ON "access_control" ("ip_address")'
    )

    migrator.sql(
        'CREATE INDEX IF NOT EXISTS '
        '"access_control_status" '
        'ON "access_control" ("status")'
    )


def rollback(migrator, database, fake=False, **kwargs):

    migrator.sql(
        'DROP TABLE IF EXISTS "access_control"'
    )

    # Recreate old group table
    migrator.sql(
        """
        CREATE TABLE IF NOT EXISTS "group" (
            "id" VARCHAR(30) NOT NULL PRIMARY KEY,
            "group_name" VARCHAR(100) NOT NULL
        )
        """
    )

    migrator.sql(
        'CREATE INDEX IF NOT EXISTS '
        '"group_group_name" '
        'ON "group" ("group_name")'
    )

    # Recreate old employee table
    migrator.sql(
        """
        CREATE TABLE IF NOT EXISTS "employee" (
            "id" VARCHAR(30) NOT NULL PRIMARY KEY,
            "first_name" VARCHAR(100) NOT NULL,
            "last_name" VARCHAR(100) NOT NULL,
            "group_id" VARCHAR(30) NOT NULL,
            FOREIGN KEY ("group_id")
                REFERENCES "group" ("id")
                ON DELETE RESTRICT
                ON UPDATE CASCADE
        )
        """
    )

    migrator.sql(
        'CREATE INDEX IF NOT EXISTS '
        '"employee_group_id" '
        'ON "employee" ("group_id")'
    )