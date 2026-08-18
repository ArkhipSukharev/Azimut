# -*- coding: utf-8 -*-
from __future__ import annotations

import base64
import ctypes
from ctypes import wintypes
from pathlib import Path

from .paths import data_dir
from .protect import atomic_write, harden_file, secure_delete

MAGIC = b"AZIMUTTK"
_CRYPTPROTECT_UI_FORBIDDEN = 0x01


class SecretError(RuntimeError):
    pass


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def token_path() -> Path:
    return data_dir() / "github.token"


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


def protect_bytes(data: bytes, label: str) -> bytes:
    incoming, _keep = _blob_in(data)
    outgoing = _DATA_BLOB()
    ok = ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(incoming),
        ctypes.c_wchar_p(label),
        None,
        None,
        None,
        _CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(outgoing),
    )
    if not ok:
        raise SecretError("Windows не смог защитить секрет.")
    return _blob_out(outgoing)


def unprotect_bytes(blob: bytes) -> bytes:
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
        raise SecretError(
            "Windows не смог открыть сохранённый секрет. Он привязан к этому пользователю Windows."
        )
    return _blob_out(outgoing)


def has_github_token() -> bool:
    path = token_path()
    return path.is_file() and path.stat().st_size > len(MAGIC)


def save_github_token(token: str) -> None:
    value = (token or "").strip()
    path = token_path()
    if not value:
        if path.exists():
            secure_delete(path)
        return
    wrapped = protect_bytes(value.encode("utf-8"), "AzimutGitHubToken")
    atomic_write(path, MAGIC + base64.b64encode(wrapped))
    harden_file(path)


def load_github_token() -> str:
    path = token_path()
    if not path.is_file():
        return ""
    raw = path.read_bytes()
    if not raw.startswith(MAGIC):
        raise SecretError("Файл токена GitHub повреждён.")
    try:
        wrapped = base64.b64decode(raw[len(MAGIC) :])
        return unprotect_bytes(wrapped).decode("utf-8")
    except SecretError:
        raise
    except Exception as exc:
        raise SecretError("Не удалось прочитать токен GitHub.") from exc


def migrate_github_token(token: str) -> None:
    value = (token or "").strip()
    if not value:
        return
    if has_github_token() and load_github_token():
        return
    save_github_token(value)
