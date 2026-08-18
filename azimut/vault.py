from __future__ import annotations

import base64
import ctypes
import json
import os
import time
from ctypes import wintypes
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.argon2 import Argon2id

from .paths import profiles_dir, vault_path
from .protect import atomic_write, harden_file, secure_delete
from .tunnel import is_amnezia_config, safe_name

MAGIC_V1 = b"AZIMUTV1"
MAGIC_V2 = b"AZIMUTV2"
AAD_DEK = b"azimut-dek-v1"
AAD_VAULT = b"azimut-vault-v1"
ITERATIONS = 3
MEMORY_KIB = 65536
LANES = 4
MIN_PASSWORD = 12


class VaultError(RuntimeError):
    pass


@dataclass
class Profile:
    name: str
    kind: str
    text: str
    updated: float = 0.0
    source: str = ""

    @property
    def path(self):
        from pathlib import Path

        return Path(self.name + ".conf")


_session_dek: bytearray | None = None
_session_data: dict | None = None
_fail_until = 0.0


def vault_exists() -> bool:
    return vault_path().exists()


def vault_needs_password() -> bool:
    path = vault_path()
    if not path.exists():
        return False
    return path.read_bytes()[:8] == MAGIC_V1


def is_unlocked() -> bool:
    return _session_dek is not None and _session_data is not None


def plaintext_profiles() -> dict[str, str]:
    found: dict[str, str] = {}
    folder = profiles_dir()
    if not folder.exists():
        return found
    for path in folder.glob("*.conf"):
        found[safe_name(path.name)] = path.read_text(encoding="utf-8", errors="replace")
    return found


def check_password_strength(password: str) -> str | None:
    value = password.strip()
    if len(value) < MIN_PASSWORD:
        return f"Пароль должен быть не короче {MIN_PASSWORD} символов."
    lowered = value.lower()
    bad = ("123456789012", "password1234", "azimut123456", "qwertyuiopas", "abcdefghijkl")
    if lowered in bad or lowered.startswith("password") or value.isdigit():
        return "Этот пароль слишком простой. Смешайте буквы, цифры и обычные слова, которых нет в словарях."
    letters = any(ch.isalpha() for ch in value)
    digits = any(ch.isdigit() for ch in value)
    if not (letters and digits) and len(value) < 16:
        return "Добавьте и буквы, и цифры — или сделайте пароль длиннее 16 символов."
    return None


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.b64decode(text.encode("ascii"))


def _derive_kek(password: str, salt: bytes) -> bytes:
    kdf = Argon2id(salt=salt, length=32, iterations=ITERATIONS, lanes=LANES, memory_cost=MEMORY_KIB)
    return kdf.derive(password.encode("utf-8"))


def _zero(buffer: bytearray | None) -> None:
    if buffer is None:
        return
    for index in range(len(buffer)):
        buffer[index] = 0


def _payload_bytes() -> bytes:
    if _session_data is None:
        raise VaultError("Хранилище закрыто.")
    return json.dumps(_session_data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


_CRYPTPROTECT_UI_FORBIDDEN = 0x01


def _blob_in(data: bytes) -> tuple[_DATA_BLOB, ctypes.Array]:
    buffer = ctypes.create_string_buffer(data, len(data))
    blob = _DATA_BLOB(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
    return blob, buffer


def _blob_out(blob: _DATA_BLOB) -> bytes:
    if not blob.cbData or not blob.pbData:
        return b""
    value = ctypes.string_at(blob.pbData, blob.cbData)
    ctypes.windll.kernel32.LocalFree(blob.pbData)
    return value


def _dpapi_protect(data: bytes) -> bytes:
    incoming, _keep = _blob_in(data)
    outgoing = _DATA_BLOB()
    ok = ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(incoming),
        ctypes.c_wchar_p("AzimutVault"),
        None,
        None,
        None,
        _CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(outgoing),
    )
    if not ok:
        raise VaultError("Windows не смог защитить ключ хранилища.")
    return _blob_out(outgoing)


def _dpapi_unprotect(blob: bytes) -> bytes:
    incoming, _keep = _blob_in(blob)
    outgoing = _DATA_BLOB()
    ok = ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(incoming),
        None,
        None,
        None,
        None,
        _CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(outgoing),
    )
    if not ok:
        raise VaultError(
            "Windows не смог открыть хранилище. Оно привязано к этому пользователю Windows — "
            "скопированный файл на другом компьютере или под другой учётной записью не откроется."
        )
    return _blob_out(outgoing)


def _write_vault() -> None:
    if _session_dek is None or _session_data is None:
        raise VaultError("Хранилище закрыто.")
    wrapped_dek = _dpapi_protect(bytes(_session_dek))
    data_nonce = os.urandom(12)
    body = AESGCM(bytes(_session_dek)).encrypt(data_nonce, _payload_bytes(), AAD_VAULT)
    header = {
        "kdf": "dpapi",
        "wrapped_dek": _b64(wrapped_dek),
        "data_nonce": _b64(data_nonce),
    }
    encoded = json.dumps(header, separators=(",", ":")).encode("utf-8")
    atomic_write(vault_path(), MAGIC_V2 + len(encoded).to_bytes(4, "big") + encoded + body)


def create_vault(profiles: dict[str, str] | None = None) -> None:
    global _session_dek, _session_data
    lock()
    now = time.time()
    stored = {}
    for name, text in (profiles or {}).items():
        clean = safe_name(name)
        stored[clean] = {
            "text": text,
            "updated": now,
            "kind": "AmneziaWG" if is_amnezia_config(text) else "WireGuard",
        }
    _session_dek = bytearray(os.urandom(32))
    _session_data = {"profiles": stored}
    _write_vault()
    for name in stored:
        secure_delete(profiles_dir() / f"{name}.conf")


def unlock_dpapi() -> None:
    global _session_dek, _session_data
    path = vault_path()
    raw = path.read_bytes()
    if not raw.startswith(MAGIC_V2):
        raise VaultError("Файл хранилища повреждён.")
    header_len = int.from_bytes(raw[8:12], "big")
    header = json.loads(raw[12 : 12 + header_len].decode("utf-8"))
    body = raw[12 + header_len :]
    dek = _dpapi_unprotect(_unb64(header["wrapped_dek"]))
    payload = AESGCM(dek).decrypt(_unb64(header["data_nonce"]), body, AAD_VAULT)
    lock()
    _session_dek = bytearray(dek)
    _session_data = json.loads(payload.decode("utf-8"))
    harden_file(path)


def open_or_create() -> None:
    from .protect import harden_app_folder

    path = vault_path()
    if path.exists() and path.read_bytes()[:8] == MAGIC_V1:
        raise VaultError("Нужен старый пароль, чтобы снять его с хранилища.")
    if path.exists() and path.read_bytes()[:8] == MAGIC_V2:
        unlock_dpapi()
        _ingest_plaintext()
        harden_app_folder()
        return
    create_vault(plaintext_profiles())
    harden_app_folder()


def unlock(password: str) -> None:
    """Один раз: старое хранилище с паролем → Windows-хранилище без пароля."""
    global _session_dek, _session_data, _fail_until
    wait = _fail_until - time.time()
    if wait > 0:
        time.sleep(min(wait, 8))
    path = vault_path()
    if not path.exists():
        raise VaultError("Зашифрованное хранилище ещё не создано.")
    raw = path.read_bytes()
    if not raw.startswith(MAGIC_V1):
        raise VaultError("Это уже новое хранилище без пароля.")
    header_len = int.from_bytes(raw[8:12], "big")
    header = json.loads(raw[12 : 12 + header_len].decode("utf-8"))
    body = raw[12 + header_len :]
    try:
        kek = _derive_kek(password, _unb64(header["salt"]))
        dek = AESGCM(kek).decrypt(_unb64(header["wrap_nonce"]), _unb64(header["wrapped_dek"]), AAD_DEK)
        payload = AESGCM(dek).decrypt(_unb64(header["data_nonce"]), body, AAD_VAULT)
    except InvalidTag as exc:
        _fail_until = time.time() + 2
        raise VaultError("Неверный пароль.") from exc
    except Exception as exc:
        _fail_until = time.time() + 2
        raise VaultError("Неверный пароль или файл хранилища повреждён.") from exc
    lock()
    _session_dek = bytearray(dek)
    _session_data = json.loads(payload.decode("utf-8"))
    _write_vault()
    _ingest_plaintext()


def lock() -> None:
    global _session_dek, _session_data
    _zero(_session_dek)
    _session_dek = None
    _session_data = None


def _ingest_plaintext() -> None:
    leftover = plaintext_profiles()
    for name, text in leftover.items():
        save_profile(name, text)
        secure_delete(profiles_dir() / f"{name}.conf")


def _require() -> dict:
    if _session_data is None:
        raise VaultError("Хранилище ещё не открыто.")
    return _session_data.setdefault("profiles", {})


def list_profiles() -> list[Profile]:
    items = []
    for name, item in _require().items():
        text = item["text"]
        items.append(
            Profile(
                name=name,
                kind=item.get("kind") or ("AmneziaWG" if is_amnezia_config(text) else "WireGuard"),
                text=text,
                updated=float(item.get("updated") or 0),
                source=str(item.get("source") or ""),
            )
        )
    items.sort(key=lambda row: row.updated, reverse=True)
    return items


def find_profile(name: str) -> Profile | None:
    for item in list_profiles():
        if item.name == name:
            return item
    return None


def save_profile(name: str, text: str, source: str | None = None) -> Profile:
    clean = safe_name(name)
    profiles = _require()
    previous = profiles.get(clean) or {}
    kind = "AmneziaWG" if is_amnezia_config(text) else "WireGuard"
    from .warp import is_generated_warp

    chosen = source if source is not None else str(previous.get("source") or "")
    if not chosen and is_generated_warp(text, clean, ""):
        chosen = "warp"
    profiles[clean] = {"text": text, "updated": time.time(), "kind": kind, "source": chosen}
    _write_vault()
    return Profile(name=clean, kind=kind, text=text, updated=time.time(), source=chosen)


def import_profile(source) -> Profile:
    text = source.read_text(encoding="utf-8", errors="replace")
    from .warp import is_generated_warp

    origin = "warp" if is_generated_warp(text, source.stem, "") else "import"
    return save_profile(source.stem, text, source=origin)


def export_profile(name: str, dest) -> None:
    profile = find_profile(name)
    if not profile:
        raise VaultError("Профиль не найден.")
    dest.write_text(profile.text, encoding="utf-8")


def delete_profile(name: str) -> None:
    profiles = _require()
    profiles.pop(safe_name(name), None)
    _write_vault()


def rename_profile(name: str, new_name: str) -> Profile:
    profile = find_profile(name)
    if not profile:
        raise VaultError("Профиль не найден.")
    created = save_profile(new_name, profile.text, source=profile.source)
    if created.name != profile.name:
        profiles = _require()
        profiles.pop(profile.name, None)
        _write_vault()
        created = find_profile(created.name)
        if not created:
            raise VaultError("Не удалось переименовать профиль.")
    return created


def new_warp_name() -> str:
    from datetime import datetime

    return "WARP_" + datetime.now().strftime("%Y%m%d_%H%M%S")
