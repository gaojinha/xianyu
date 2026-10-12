import glob
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from app.db_manager import DBManager
from app import reply_server


class DatabaseBackupApiTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.live_path = os.path.join(self.temp_dir.name, "live.db")
        self.source_path = os.path.join(self.temp_dir.name, "source.db")
        self.live = DBManager(self.live_path)
        self.source = DBManager(self.source_path)
        self._insert_user(self.live, 2, "live-user", "live@example.com")
        self._insert_user(self.source, 2, "restore-user", "restore@example.com")
        self.source.backup_to(os.path.join(self.temp_dir.name, "upload.db"))

        self.old_overrides = reply_server.app.dependency_overrides.copy()
        reply_server.app.dependency_overrides[reply_server.require_admin] = lambda: {
            "user_id": 1,
            "username": "admin",
            "is_admin": True,
        }
        self.db_patch = patch("app.db_manager.db_manager", self.live)
        self.cookie_manager_patch = patch("app.cookie_manager.manager", None)
        self.db_patch.start()
        self.cookie_manager_patch.start()
        self.client = TestClient(reply_server.app)

    def tearDown(self):
        self.client.close()
        self.db_patch.stop()
        self.cookie_manager_patch.stop()
        reply_server.app.dependency_overrides.clear()
        reply_server.app.dependency_overrides.update(self.old_overrides)
        self.live.close()
        self.source.close()
        self.temp_dir.cleanup()

    @staticmethod
    def _insert_user(manager, user_id, username, email):
        manager.conn.execute(
            """
            INSERT INTO users (id, username, email, password_hash)
            VALUES (?, ?, ?, 'hash')
            """,
            (user_id, username, email),
        )
        manager.conn.commit()

    def _upload(self, filename="upload.db", content=None):
        if content is None:
            with open(os.path.join(self.temp_dir.name, "upload.db"), "rb") as source:
                content = source.read()
        return self.client.post(
            "/admin/backup/upload",
            files={"backup_file": (filename, content, "application/octet-stream")},
        )

    def test_upload_restores_live_database_through_sqlite_backup_api(self):
        response = self._upload()

        self.assertEqual(200, response.status_code, response.text)
        self.assertEqual(
            [],
            glob.glob(os.path.join(self.temp_dir.name, "xianyu-restore-upload-*.db")),
        )
        self.assertIsNone(
            self.live.conn.execute(
                "SELECT id FROM users WHERE email = 'live@example.com'"
            ).fetchone()
        )
        self.assertIsNotNone(
            self.live.conn.execute(
                "SELECT id FROM users WHERE email = 'restore@example.com'"
            ).fetchone()
        )

    def test_invalid_upload_does_not_modify_live_database(self):
        response = self._upload(content=b"not a SQLite database")

        self.assertEqual(400, response.status_code)
        self.assertIsNotNone(
            self.live.conn.execute(
                "SELECT id FROM users WHERE email = 'live@example.com'"
            ).fetchone()
        )

    def test_cache_reload_failure_rolls_back_database_snapshot(self):
        manager = SimpleNamespace(
            tasks={},
            cookies={},
            reload_from_db=Mock(side_effect=[RuntimeError("cache reload failed"), None]),
        )
        with patch.object(reply_server.cookie_manager, "manager", manager):
            response = self._upload()

        self.assertEqual(500, response.status_code)
        self.assertIsNotNone(
            self.live.conn.execute(
                "SELECT id FROM users WHERE email = 'live@example.com'"
            ).fetchone()
        )
        self.assertIsNone(
            self.live.conn.execute(
                "SELECT id FROM users WHERE email = 'restore@example.com'"
            ).fetchone()
        )
        self.assertEqual(2, manager.reload_from_db.call_count)


if __name__ == "__main__":
    unittest.main()
