import glob
import os
import stat
import tempfile
import unittest
from unittest.mock import patch

from app.db_manager import DBManager
from app.secret_store import PREFIX, SecretDecryptionError, decrypt_secret, encrypt_secret
from scripts.rotate_secrets import main as rotate_secrets


class SecretEncryptionTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "secrets.db")
        self.key_path = os.path.join(self.temp_dir.name, "app-encryption.key")
        self.backup_path = os.path.join(self.temp_dir.name, "snapshots")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_encrypts_and_decrypts_secret_values_at_rest(self):
        environment = {
            "APP_ENCRYPTION_KEY": "gAAAAAB-invalid",
            "APP_ENCRYPTION_KEY_FILE": self.key_path,
            "MIGRATION_BACKUP_DIR": self.backup_path,
        }
        from cryptography.fernet import Fernet

        with open(self.key_path, "wb") as key_file:
            key_file.write(Fernet.generate_key() + b"\n")
        os.chmod(self.key_path, 0o600)
        environment.pop("APP_ENCRYPTION_KEY")
        with patch.dict(os.environ, environment):
            manager = DBManager(self.db_path)
            try:
                manager.conn.execute(
                    "INSERT INTO users (id, username, email, password_hash) VALUES (88, 'secret-owner', 'secret@example.test', 'hash')"
                )
                manager.conn.commit()
                self.assertTrue(manager.save_cookie("secret-account", "session=secret", user_id=88))
                self.assertTrue(manager.save_ai_reply_settings(
                    "secret-account", {"api_key": "ai-secret", "ai_enabled": True}
                ))
                channel_id = manager.create_notification_channel(
                    "test", "webhook", '{"webhook_url":"https://example.test/secret"}', 88
                )
                self.assertGreater(channel_id, 0)
                self.assertTrue(manager.set_system_setting("smtp_password", "mail-secret"))

                self.assertTrue(manager.conn.execute(
                    "SELECT value FROM cookies WHERE id = 'secret-account'"
                ).fetchone()[0].startswith(PREFIX))
                self.assertTrue(manager.conn.execute(
                    "SELECT api_key FROM ai_reply_settings WHERE cookie_id = 'secret-account'"
                ).fetchone()[0].startswith(PREFIX))
                self.assertTrue(manager.conn.execute(
                    "SELECT config FROM notification_channels WHERE id = ?", (channel_id,)
                ).fetchone()[0].startswith(PREFIX))
                self.assertEqual("session=secret", manager.get_cookie("secret-account"))
                self.assertEqual("ai-secret", manager.get_ai_reply_settings("secret-account")["api_key"])
                self.assertEqual(
                    '{"webhook_url":"https://example.test/secret"}',
                    manager.get_notification_channels(88)[0]["config"],
                )
                self.assertEqual("mail-secret", manager.get_system_setting("smtp_password"))
            finally:
                manager.close()

    def test_rotation_preserves_access_and_creates_recovery_snapshot(self):
        manager = DBManager(self.db_path)
        manager.conn.execute(
            "INSERT INTO users (id, username, email, password_hash) VALUES (89, 'legacy-owner', 'legacy@example.test', 'hash')"
        )
        manager.conn.commit()
        self.assertTrue(manager.save_cookie("legacy-account", "sid=legacy", user_id=89))
        self.assertTrue(manager.set_system_setting("smtp_password", "legacy-mail-secret"))
        manager.close()

        with patch.dict(os.environ, {
            "DB_PATH": self.db_path,
            "APP_ENCRYPTION_KEY_FILE": self.key_path,
            "MIGRATION_BACKUP_DIR": self.backup_path,
        }):
            rotate_secrets()

        self.assertEqual(0o600, stat.S_IMODE(os.stat(self.key_path).st_mode))
        snapshots = glob.glob(os.path.join(self.backup_path, "*.db"))
        self.assertEqual(1, len(snapshots))
        with patch.dict(os.environ, {
            "APP_ENCRYPTION_KEY_FILE": self.key_path,
            "MIGRATION_BACKUP_DIR": self.backup_path,
        }):
            encrypted = DBManager(self.db_path)
            try:
                self.assertTrue(encrypted.conn.execute(
                    "SELECT value FROM cookies WHERE id = 'legacy-account'"
                ).fetchone()[0].startswith(PREFIX))
                self.assertEqual("sid=legacy", encrypted.get_cookie("legacy-account"))
                self.assertEqual("legacy-mail-secret", encrypted.get_system_setting("smtp_password"))
            finally:
                encrypted.close()

    def test_configured_key_migrates_existing_plaintext_on_startup(self):
        from cryptography.fernet import Fernet

        manager = DBManager(self.db_path)
        manager.conn.execute(
            "INSERT INTO users (id, username, email, password_hash) VALUES (90, 'plain-owner', 'plain@example.test', 'hash')"
        )
        manager.conn.commit()
        self.assertTrue(manager.save_cookie("plain-account", "sid=plain", user_id=90))
        manager.close()

        with open(self.key_path, "wb") as key_file:
            key_file.write(Fernet.generate_key() + b"\n")
        os.chmod(self.key_path, 0o600)
        with patch.dict(os.environ, {
            "APP_ENCRYPTION_KEY_FILE": self.key_path,
            "MIGRATION_BACKUP_DIR": self.backup_path,
        }):
            encrypted = DBManager(self.db_path)
            try:
                raw = encrypted.conn.execute(
                    "SELECT value FROM cookies WHERE id = 'plain-account'"
                ).fetchone()[0]
                self.assertTrue(raw.startswith(PREFIX))
                self.assertEqual("sid=plain", encrypted.get_cookie("plain-account"))
            finally:
                encrypted.close()

    def test_encrypted_values_fail_closed_without_the_correct_key(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(SecretDecryptionError, "require"):
                decrypt_secret(PREFIX + "token")

        from cryptography.fernet import Fernet

        key1 = Fernet.generate_key().decode("ascii")
        key2 = Fernet.generate_key().decode("ascii")
        with patch.dict(os.environ, {"APP_ENCRYPTION_KEY": key1}, clear=True):
            encrypted = encrypt_secret("do-not-leak")
        with patch.dict(os.environ, {"APP_ENCRYPTION_KEY": key2}, clear=True):
            with self.assertRaisesRegex(SecretDecryptionError, "could not be decrypted"):
                decrypt_secret(encrypted)


if __name__ == "__main__":
    unittest.main()
