import os
import sqlite3
import tempfile
import unittest

from app.db_manager import DBManager


class DatabaseBackupTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "live.db")
        self.snapshot_path = os.path.join(self.temp_dir.name, "snapshot.db")
        self.db = DBManager(self.db_path)

    def tearDown(self):
        self.db.close()
        self.temp_dir.cleanup()

    def test_backup_includes_committed_wal_data(self):
        with self.db.lock:
            self.db.conn.execute("PRAGMA journal_mode=WAL")
            self.db.conn.execute(
                """
                INSERT INTO users (username, email, password_hash)
                VALUES ('snapshot-user', 'snapshot@example.com', 'hash')
                """
            )
            self.db.conn.commit()

        self.db.backup_to(self.snapshot_path)

        snapshot = sqlite3.connect(self.snapshot_path)
        try:
            integrity = snapshot.execute("PRAGMA quick_check").fetchone()[0]
            username = snapshot.execute(
                "SELECT username FROM users WHERE email = ?",
                ("snapshot@example.com",),
            ).fetchone()[0]
        finally:
            snapshot.close()

        self.assertEqual("ok", integrity)
        self.assertEqual("snapshot-user", username)

    def test_backup_fails_explicitly_when_database_is_closed(self):
        self.db.close()

        with self.assertRaisesRegex(RuntimeError, "connection is closed"):
            self.db.backup_to(self.snapshot_path)

    def test_restore_replaces_live_database_without_reopening_manager(self):
        with self.db.lock:
            self.db.conn.execute(
                """
                INSERT INTO users (username, email, password_hash)
                VALUES ('live-user', 'live@example.com', 'hash')
                """
            )
            self.db.conn.commit()

        source = DBManager(os.path.join(self.temp_dir.name, "source.db"))
        try:
            with source.lock:
                source.conn.execute(
                    """
                    INSERT INTO users (username, email, password_hash)
                    VALUES ('restored-user', 'restored@example.com', 'hash')
                    """
                )
                source.conn.commit()
            source.backup_to(self.snapshot_path)
        finally:
            source.close()

        connection_before_restore = self.db.conn
        self.db.restore_from_backup(self.snapshot_path)

        self.assertIs(connection_before_restore, self.db.conn)
        self.assertIsNone(
            self.db.conn.execute(
                "SELECT id FROM users WHERE email = 'live@example.com'"
            ).fetchone()
        )
        self.assertIsNotNone(
            self.db.conn.execute(
                "SELECT id FROM users WHERE email = 'restored@example.com'"
            ).fetchone()
        )
        self.assertEqual("ok", self.db.conn.execute("PRAGMA quick_check").fetchone()[0])


if __name__ == "__main__":
    unittest.main()
