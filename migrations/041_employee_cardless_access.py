"""Add local employee accounts, imported permissions, and cardless audits."""


def migrate(migrator, database, fake=False, **kwargs):
    """Create employee tables without modifying physical access-control data."""
    statements = [
        '''CREATE TABLE employee (
            id VARCHAR(32) PRIMARY KEY, name VARCHAR(50),
            name_key VARCHAR(100) UNIQUE, username VARCHAR(100) UNIQUE,
            password_hash VARCHAR(120), enabled INTEGER NOT NULL DEFAULT 1,
            auth_version INTEGER NOT NULL DEFAULT 0, face_name VARCHAR(50) UNIQUE
        )''',
        '''CREATE TABLE employeesource (
            id VARCHAR(64) PRIMARY KEY, controller_id VARCHAR(30) NOT NULL,
            user_id VARCHAR(100) NOT NULL, employee_id VARCHAR(32),
            name VARCHAR(100) NOT NULL, active INTEGER NOT NULL DEFAULT 1,
            doors TEXT NOT NULL DEFAULT '[]', suppressed INTEGER NOT NULL DEFAULT 0
        )''',
        '''CREATE TABLE employeedooroverride (
            employee_id VARCHAR(32) NOT NULL, controller_id VARCHAR(30) NOT NULL,
            doors TEXT NOT NULL DEFAULT '[]', PRIMARY KEY (employee_id, controller_id)
        )''',
        '''CREATE TABLE employeeaccesssettings (
            id INTEGER PRIMARY KEY, enabled INTEGER NOT NULL DEFAULT 0,
            generation INTEGER NOT NULL DEFAULT 0
        )''',
        '''CREATE TABLE employeeaccessattempt (
            id VARCHAR(36) PRIMARY KEY, employee_id VARCHAR(32) NOT NULL,
            camera VARCHAR(100) NOT NULL, controller_id VARCHAR(30) NOT NULL,
            door_id VARCHAR(100) NOT NULL, created_at REAL NOT NULL,
            status VARCHAR(30) NOT NULL DEFAULT 'verifying', score REAL,
            result TEXT NOT NULL DEFAULT '{}'
        )''',
        '''CREATE TABLE employeecontrollersync (
            controller_id VARCHAR(30) PRIMARY KEY, checked_at REAL NOT NULL,
            last_success REAL, status VARCHAR(30) NOT NULL
        )''',
        'CREATE INDEX employee_source_controller ON employeesource (controller_id)',
        'CREATE INDEX employee_source_employee ON employeesource (employee_id)',
        'CREATE INDEX employee_attempt_employee ON employeeaccessattempt (employee_id)',
        'CREATE INDEX employee_attempt_created ON employeeaccessattempt (created_at)',
        'INSERT INTO employeeaccesssettings (id, enabled, generation) VALUES (1, 0, 0)',
    ]
    for statement in statements:
        migrator.sql(statement)


def rollback(migrator, database, fake=False, **kwargs):
    """Remove only the employee feature's tables."""
    for table in (
        "employeecontrollersync", "employeeaccessattempt", "employeeaccesssettings",
        "employeedooroverride", "employeesource", "employee",
    ):
        migrator.sql(f'DROP TABLE IF EXISTS "{table}"')
