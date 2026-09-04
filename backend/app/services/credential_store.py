"""Encrypted local credential storage for cloud logbook connections.

Secrets never leave the backend.  A random AES-256 key is created in the user's
QSO Manager data directory and used with AES-GCM.  The browser only receives
masked connection metadata, never stored passwords/API keys.
"""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Any, Dict

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from ..core.runtime import user_data_root


class CredentialStore:
    VERSION = 1

    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root or user_data_root())
        self.root.mkdir(parents=True, exist_ok=True)
        self.key_path = self.root / ".cloud-secret-key"
        self.store_path = self.root / "cloud-connections.enc"

    def _key(self) -> bytes:
        if self.key_path.exists():
            raw = self.key_path.read_bytes()
            if len(raw) != 32:
                raise RuntimeError("Invalid local credential key")
            return raw
        raw = AESGCM.generate_key(bit_length=256)
        self.key_path.write_bytes(raw)
        try:
            os.chmod(self.key_path, 0o600)
        except OSError:
            pass
        return raw

    def _read_all(self) -> Dict[str, Dict[str, Any]]:
        if not self.store_path.exists():
            return {}
        payload = json.loads(self.store_path.read_text(encoding="utf-8"))
        if payload.get("version") != self.VERSION:
            raise RuntimeError("Unsupported credential store version")
        nonce = base64.b64decode(payload["nonce"])
        ciphertext = base64.b64decode(payload["ciphertext"])
        plain = AESGCM(self._key()).decrypt(nonce, ciphertext, b"PU2BRU-QSO-Manager")
        value = json.loads(plain.decode("utf-8"))
        return value if isinstance(value, dict) else {}

    def _write_all(self, value: Dict[str, Dict[str, Any]]) -> None:
        key = self._key()
        nonce = os.urandom(12)
        plain = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        ciphertext = AESGCM(key).encrypt(nonce, plain, b"PU2BRU-QSO-Manager")
        payload = {
            "version": self.VERSION,
            "nonce": base64.b64encode(nonce).decode("ascii"),
            "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
        }
        temp = self.store_path.with_suffix(".tmp")
        temp.write_text(json.dumps(payload), encoding="utf-8")
        temp.replace(self.store_path)
        try:
            os.chmod(self.store_path, 0o600)
        except OSError:
            pass

    def get(self, provider: str) -> Dict[str, Any]:
        return dict(self._read_all().get(provider.upper(), {}))

    def set(self, provider: str, values: Dict[str, Any]) -> None:
        all_values = self._read_all()
        all_values[provider.upper()] = {k: v for k, v in values.items() if v is not None}
        self._write_all(all_values)

    def delete(self, provider: str) -> None:
        all_values = self._read_all()
        all_values.pop(provider.upper(), None)
        self._write_all(all_values)

    def configured(self, provider: str) -> bool:
        return bool(self.get(provider))

    @staticmethod
    def masked(values: Dict[str, Any]) -> Dict[str, Any]:
        secret_names = {"api_key", "password", "app_password", "key"}
        out: Dict[str, Any] = {}
        for name, value in values.items():
            if name in secret_names and value:
                text = str(value)
                out[name] = "••••" + text[-4:] if len(text) >= 4 else "••••"
            else:
                out[name] = value
        return out
