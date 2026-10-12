import os
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken


PREFIX = "enc:v1:"


class SecretDecryptionError(RuntimeError):
    pass


def encryption_enabled() -> bool:
    return bool(_configured_key())


def _configured_key() -> str:
    value = os.getenv("APP_ENCRYPTION_KEY", "").strip()
    if value:
        return value
    key_path = os.getenv("APP_ENCRYPTION_KEY_FILE", "").strip()
    if not key_path:
        db_path = os.getenv("DB_PATH", "data/xianyu_data.db")
        key_path = os.path.join(
            os.path.dirname(os.path.abspath(db_path)),
            "app-encryption.key",
        )
    try:
        mode = os.stat(key_path).st_mode & 0o777
        if mode & 0o077:
            raise SecretDecryptionError(
                "APP_ENCRYPTION_KEY_FILE must not be accessible by group or other users"
            )
        with open(key_path, "r", encoding="ascii") as key_file:
            return key_file.read().strip()
    except FileNotFoundError:
        return ""


def _fernet(key: Optional[str] = None) -> Fernet:
    value = key if key is not None else _configured_key()
    try:
        return Fernet(value.encode("ascii"))
    except (TypeError, ValueError, UnicodeEncodeError) as error:
        raise SecretDecryptionError(
            "APP_ENCRYPTION_KEY must be a valid Fernet key"
        ) from error


def encrypt_secret(value: Optional[str], key: Optional[str] = None) -> Optional[str]:
    if value is None or value == "" or value.startswith(PREFIX):
        return value
    if key is None and not encryption_enabled():
        return value
    return PREFIX + _fernet(key).encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_secret(value: Optional[str], key: Optional[str] = None) -> Optional[str]:
    if value is None or not value.startswith(PREFIX):
        return value
    if key is None and not encryption_enabled():
        raise SecretDecryptionError(
            "Encrypted database secrets require APP_ENCRYPTION_KEY or APP_ENCRYPTION_KEY_FILE"
        )
    try:
        token = value[len(PREFIX):].encode("ascii")
        return _fernet(key).decrypt(token).decode("utf-8")
    except (InvalidToken, UnicodeEncodeError, UnicodeDecodeError) as error:
        raise SecretDecryptionError(
            "Database secrets could not be decrypted; check APP_ENCRYPTION_KEY"
        ) from error
