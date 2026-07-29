# datarecon/infrastructure/security/crypto.py
from __future__ import annotations

import contextlib
import os
import stat
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken


class CredentialCipher:
    """AES-128-CBC + HMAC (Fernet) credential encryption. The key is generated
    once, stored outside version control, and locked to owner-only permissions."""

    def __init__(self, key_path: Path):
        self._key_path = key_path
        self._fernet = Fernet(self._load_or_create_key())

    def _load_or_create_key(self) -> bytes:
        if self._key_path.exists():
            return self._key_path.read_bytes().strip()
        key = Fernet.generate_key()
        self._key_path.parent.mkdir(parents=True, exist_ok=True)
        self._key_path.write_bytes(key)
        with contextlib.suppress(OSError):  # Windows: ACLs handled by OS defaults
            os.chmod(self._key_path, stat.S_IRUSR | stat.S_IWUSR)  # 0600
        return key

    def encrypt(self, plaintext: str | None) -> str | None:
        if not plaintext:
            return None
        return self._fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")

    def decrypt(self, ciphertext: str | None) -> str | None:
        if not ciphertext:
            return None
        try:
            return self._fernet.decrypt(ciphertext.encode("ascii")).decode("utf-8")
        except InvalidToken as exc:
            raise ValueError(
                "Credential decryption failed. Encryption key may have been rotated or corrupted."
            ) from exc
