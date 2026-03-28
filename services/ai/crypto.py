"""Password decryption utility for credentials stored in public.databases.

Passwords may be stored as plaintext or as Fernet-encrypted strings prefixed
with 'enc#_'.  Use `decrypt_password` to transparently handle both forms.

Encryption scheme (mirrors the datafusion backend):
  key  = HKDF(SHA-256, length=32, salt=None, info=None).derive(PASSWORD_SALT)
  key  = base64.urlsafe_b64encode(key)          # Fernet-compatible key
  ciphertext = Fernet(key).encrypt(plaintext)
  stored = "enc#_" + ciphertext.decode()
"""
from __future__ import annotations

import base64
import os

_password_salt: str | None = None


def _get_salt() -> str:
    global _password_salt
    if _password_salt is None:
        _password_salt = os.getenv("PASSWORD_SALT") or os.getenv("DOMAIN") or "algo_fusion_secret"
    return _password_salt


def _derive_key(salt: str) -> bytes:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=None,
        backend=default_backend(),
    )
    return base64.urlsafe_b64encode(hkdf.derive(salt.encode()))


def decrypt_password(value: str) -> str:
    """Return the plaintext password.

    If *value* starts with 'enc#_' it is decrypted using the Fernet key
    derived from PASSWORD_SALT (env var).  Otherwise the value is returned
    unchanged, supporting plaintext passwords stored without encryption.
    """
    if not value or not value.startswith("enc#_"):
        return value

    import cryptography.fernet

    key = _derive_key(_get_salt())
    ciphertext = value[5:].encode()
    return cryptography.fernet.Fernet(key).decrypt(ciphertext).decode()