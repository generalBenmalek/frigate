"""Peewee migrations -- 036_create_employee_and_group_tables.py.

Some examples (model - class or model_name)::

    > Model = migrator.orm['model_name']            # Return model in current state by name
    > migrator.sql(sql)                             # Run custom SQL
    > migrator.run(func, *args, **kwargs)           # Run python code
    > migrator.create_model(Model)                  # Create a model (could be used as decorator)
    > migrator.remove_model(model, cascade=True)    # Remove a model
    > migrator.add_fields(model, **fields)          # Add fields to a model
    > migrator.change_fields(model, **fields)       # Change fields
    > migrator.remove_fields(model, *field_names, cascade=True)
    > migrator.rename_field(model, old_field_name, new_field_name)
    > migrator.rename_table(model, new_table_name)
    > migrator.add_index(model, *col_names, unique=False)
    > migrator.drop_index(model, *col_names)
    > migrator.add_not_null(model, *field_names)
    > migrator.drop_not_null(model, *field_names)
    > migrator.add_default(model, field_name, default)

"""

import peewee as pw

SQL = pw.SQL


def migrate(migrator, database, fake=False, **kwargs):
    migrator.sql(
        """
        CREATE TABLE IF NOT EXISTS "group" (
            "id" VARCHAR(30) NOT NULL PRIMARY KEY,
            "group_name" VARCHAR(100) NOT NULL
        )
        """
    )
    migrator.sql(
        'CREATE INDEX IF NOT EXISTS "group_group_name" ON "group" ("group_name")'
    )

    migrator.sql(
        """
        CREATE TABLE IF NOT EXISTS "employee" (
            "id" VARCHAR(30) NOT NULL PRIMARY KEY,
            "first_name" VARCHAR(100) NOT NULL,
            "last_name" VARCHAR(100) NOT NULL,
            "group_id" VARCHAR(30) NOT NULL,
            FOREIGN KEY ("group_id") REFERENCES "group" ("id") ON DELETE RESTRICT ON UPDATE CASCADE
        )
        """
    )
    migrator.sql(
        'CREATE INDEX IF NOT EXISTS "employee_group_id" ON "employee" ("group_id")'
    )


def rollback(migrator, database, fake=False, **kwargs):
    pass
