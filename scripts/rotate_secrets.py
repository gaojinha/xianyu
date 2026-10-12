import os
import sqlite3
import sys
from datetime import datetime

from cryptography.fernet import Fernet

from app.secret_store import _configured_key, decrypt_secret, encrypt_secret


def _rewrite_column(connection, table, key_column, value_column, old_key, new_key):
    cursor = connection.execute(
        f"SELECT {key_column}, {value_column} FROM {table} "
        f"WHERE {value_column} IS NOT NULL AND {value_column} != ''"
    )
    for row_key, raw_value in cursor.fetchall():
        plaintext = decrypt_secret(raw_value, old_key)
        connection.execute(
            f"UPDATE {table} SET {value_column} = ? WHERE {key_column} = ?",
            (encrypt_secret(plaintext, new_key), row_key),
        )


def main():
    if os.getenv("APP_ENCRYPTION_KEY", "").strip():
        raise RuntimeError(
            "Use APP_ENCRYPTION_KEY_FILE as the active key source before rotating; "
            "APP_ENCRYPTION_KEY would override the rotated key file"
        )
    db_path = os.getenv("DB_PATH", "data/xianyu_data.db")
    key_path = os.getenv(
        "APP_ENCRYPTION_KEY_FILE",
        os.path.join(os.path.dirname(os.path.abspath(db_path)), "app-encryption.key"),
    )
    key_path = os.path.abspath(key_path)
    key_dir = os.path.dirname(key_path)
    os.makedirs(key_dir, mode=0o700, exist_ok=True)
    os.chmod(key_dir, 0o700)
    next_key_path = key_path + ".next"
    if os.path.exists(next_key_path):
        raise RuntimeError(
            f"Recovery key already exists at {next_key_path}; inspect it before rotating again"
        )

    old_key = _configured_key() or None
    if old_key:
        Fernet(old_key.encode("ascii"))
    new_key = Fernet.generate_key().decode("ascii")
    descriptor = os.open(
        next_key_path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o600,
    )
    with os.fdopen(descriptor, "w", encoding="ascii") as key_file:
        key_file.write(new_key + "\n")
        key_file.flush()
        os.fsync(key_file.fileno())

    if not os.path.isfile(db_path):
        os.replace(next_key_path, key_path)
        os.chmod(key_path, 0o600)
        print(f"Encryption key initialized: {key_path}")
        return

    backup_dir = os.getenv(
        "MIGRATION_BACKUP_DIR",
        os.path.join(os.path.dirname(os.path.abspath(db_path)), "backups", "migrations"),
    )
    os.makedirs(backup_dir, mode=0o700, exist_ok=True)
    os.chmod(backup_dir, 0o700)
    snapshot_path = os.path.join(
        backup_dir,
        f"xianyu-pre-secret-rotation-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}.db",
    )
    source = sqlite3.connect(db_path)
    snapshot = sqlite3.connect(snapshot_path)
    try:
        source.backup(snapshot)
        integrity = snapshot.execute("PRAGMA quick_check").fetchone()
        if not integrity or integrity[0] != "ok":
            raise sqlite3.DatabaseError("Secret rotation snapshot integrity check failed")
    except Exception:
        snapshot.close()
        source.close()
        os.remove(snapshot_path)
        os.remove(next_key_path)
        raise
    snapshot.close()
    os.chmod(snapshot_path, 0o600)

    committed = False
    try:
        source.execute("BEGIN IMMEDIATE")
        for table, key_column, value_column in (
            ("cookies", "id", "value"),
            ("cookies", "id", "password"),
            ("ai_reply_settings", "cookie_id", "api_key"),
            ("notification_channels", "id", "config"),
        ):
            _rewrite_column(source, table, key_column, value_column, old_key, new_key)

        for key in ("smtp_password", "qq_reply_secret_key"):
            row = source.execute(
                "SELECT value FROM system_settings WHERE key = ?",
                (key,),
            ).fetchone()
            if row and row[0]:
                clear_value = decrypt_secret(row[0], old_key)
                source.execute(
                    "UPDATE system_settings SET value = ? WHERE key = ?",
                    (encrypt_secret(clear_value, new_key), key),
                )
        source.commit()
        committed = True
        os.replace(next_key_path, key_path)
        os.chmod(key_path, 0o600)
    except Exception:
        source.rollback()
        if not committed and os.path.exists(next_key_path):
            os.remove(next_key_path)
        raise
    finally:
        source.close()

    print(f"Secrets rotated successfully. New key: {key_path}")
    print(f"Pre-rotation database snapshot: {snapshot_path}")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Secret rotation failed: {error}", file=sys.stderr)
        raise
