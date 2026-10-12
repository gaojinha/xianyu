import glob
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from app.db_manager import DBManager


class DatabaseMigrationSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "live.db")
        self.backup_dir = os.path.join(self.temp_dir.name, "migration-backups")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_existing_database_is_snapshotted_before_schema_upgrade(self):
        original = DBManager(self.db_path)
        original.conn.execute(
            "INSERT INTO users (username, email, password_hash) VALUES ('before', 'before@example.test', 'hash')"
        )
        original.conn.execute(
            "UPDATE system_settings SET value = '1.7' WHERE key = 'db_version'"
        )
        original.conn.commit()
        original.close()

        with patch.dict(os.environ, {"MIGRATION_BACKUP_DIR": self.backup_dir}):
            upgraded = DBManager(self.db_path)
        try:
            paths = glob.glob(os.path.join(self.backup_dir, "*.db"))
            self.assertEqual(1, len(paths))
            snapshot = sqlite3.connect(paths[0])
            try:
                self.assertEqual(
                    "before",
                    snapshot.execute(
                        "SELECT username FROM users WHERE email = 'before@example.test'"
                    ).fetchone()[0],
                )
                self.assertEqual(
                    "1.7",
                    snapshot.execute(
                        "SELECT value FROM system_settings WHERE key = 'db_version'"
                    ).fetchone()[0],
                )
                self.assertEqual("ok", snapshot.execute("PRAGMA quick_check").fetchone()[0])
            finally:
                snapshot.close()
            self.assertEqual(
                "1.8",
                upgraded.conn.execute(
                    "SELECT value FROM system_settings WHERE key = 'db_version'"
                ).fetchone()[0],
            )
            self.assertTrue(os.path.isfile(paths[0]))
            self.assertEqual(0o600, os.stat(paths[0]).st_mode & 0o777)
        finally:
            upgraded.close()

    def test_new_database_does_not_create_migration_snapshot(self):
        with patch.dict(os.environ, {"MIGRATION_BACKUP_DIR": self.backup_dir}):
            manager = DBManager(self.db_path)
        try:
            self.assertFalse(os.path.exists(self.backup_dir))
        finally:
            manager.close()

    def test_snapshot_failure_aborts_migration_before_schema_changes(self):
        manager = DBManager(self.db_path)
        manager.conn.execute(
            "UPDATE system_settings SET value = '1.7' WHERE key = 'db_version'"
        )
        manager.conn.commit()
        manager.close()
        not_a_directory = os.path.join(self.temp_dir.name, "backup-file")
        with open(not_a_directory, "w", encoding="utf-8") as target:
            target.write("occupied")

        with patch.dict(os.environ, {"MIGRATION_BACKUP_DIR": not_a_directory}):
            with self.assertRaises(OSError):
                DBManager(self.db_path)

        connection = sqlite3.connect(self.db_path)
        try:
            self.assertEqual(
                "1.7",
                connection.execute(
                    "SELECT value FROM system_settings WHERE key = 'db_version'"
                ).fetchone()[0],
            )
        finally:
            connection.close()


if __name__ == "__main__":
    unittest.main()
