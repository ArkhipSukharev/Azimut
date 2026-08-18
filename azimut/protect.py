from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

from .paths import app_root, engine_dir

TRUSTED_SHA256 = {
    "engine/amneziawg.exe": "dcd5ace18c26a58dd632b337f769673be14a288cfc04ba37f69587884d3806be",
    "engine/wintun.dll": "e5da8447dc2c320edc0fc52fa01885c103de8c118481f683643cacc3220dafce",
    "engine/awg.exe": "fb90a5dff7849987379889f37203186ff42aaff710c37d860d0a53100b89fa10",
    "zapret/bin/winws.exe": "2da71e80878dc270ac83f5893ecbb841f9752a57f1da8ff9325636b4346bc632",
    "zapret/bin/WinDivert.dll": "16abd6a029e65557c6a309bea7b13bf81fff4e193567582e1cddbf6719f323e0",
    "zapret/bin/WinDivert64.sys": "8da085332782708d8767bcace5327a6ec7283c17cfb85e40b03cd2323a90ddc2",
}

MSI_SHA256 = "1b7308d0c74685193dee5d30fd30f370b5a2748a7f648869cd16f25286efc784"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def verify_bytes(data: bytes, expected: str, label: str) -> None:
    got = sha256_bytes(data)
    if got.lower() != expected.lower():
        raise RuntimeError(
            f"Файл {label} повреждён или подменён. Ожидалась контрольная сумма, она не совпала. "
            "Не запускайте туннель, пока файл не будет восстановлен из проверенного источника."
        )


def _expected_hashes(relative: str) -> set[str]:
    allowed = set()
    builtin = TRUSTED_SHA256.get(relative)
    if builtin:
        allowed.add(builtin.lower())
    try:
        from .bypass_update import recorded_hashes

        extra = recorded_hashes().get(relative)
        if extra:
            allowed.add(extra.lower())
    except Exception:
        pass
    return allowed


def verify_named(relative: str) -> None:
    path = app_root() / relative.replace("/", os.sep)
    if not path.exists():
        raise RuntimeError(f"Не найден файл движка: {relative}")
    digest = sha256_file(path)
    allowed = _expected_hashes(relative)
    if not allowed:
        raise RuntimeError(f"Нет эталонной суммы для файла {relative}.")
    if digest.lower() not in allowed:
        raise RuntimeError(
            f"Файл {relative} не прошёл проверку целостности. "
            "Его могли изменить антивирус, сбой диска или посторонняя программа. "
            "Azimut не будет его запускать."
        )


def verify_tunnel_engine() -> None:
    verify_named("engine/amneziawg.exe")
    verify_named("engine/wintun.dll")
    if (engine_dir() / "awg.exe").exists():
        verify_named("engine/awg.exe")


def verify_zapret_engine() -> None:
    verify_named("zapret/bin/winws.exe")
    verify_named("zapret/bin/WinDivert.dll")
    verify_named("zapret/bin/WinDivert64.sys")


def _hidden(args: list[str]) -> None:
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    subprocess.run(args, capture_output=True, startupinfo=startup, creationflags=subprocess.CREATE_NO_WINDOW)


def harden_path(path: Path) -> None:
    """Leave access only to this Windows user, administrators and the system."""
    path.mkdir(parents=True, exist_ok=True)
    target = str(path)
    user = os.environ.get("USERNAME") or os.getlogin()
    _hidden(["icacls", target, "/inheritance:d"])
    for account in ("*S-1-1-0", "*S-1-5-11", "*S-1-5-32-545", "*S-1-5-32-546"):
        _hidden(["icacls", target, "/remove:g", account])
    _hidden(["icacls", target, "/grant:r", "SYSTEM:(OI)(CI)F"])
    _hidden(["icacls", target, "/grant:r", "Administrators:(OI)(CI)F"])
    _hidden(["icacls", target, "/grant:r", f"{user}:(OI)(CI)F"])


def harden_file(path: Path) -> None:
    if not path.exists():
        return
    target = str(path)
    user = os.environ.get("USERNAME") or os.getlogin()
    _hidden(["icacls", target, "/inheritance:d"])
    for account in ("*S-1-1-0", "*S-1-5-11", "*S-1-5-32-545"):
        _hidden(["icacls", target, "/remove:g", account])
    _hidden(["icacls", target, "/grant:r", "SYSTEM:F"])
    _hidden(["icacls", target, "/grant:r", "Administrators:F"])
    _hidden(["icacls", target, "/grant:r", f"{user}:F"])


def harden_app_folder() -> None:
    root = app_root()
    harden_path(root)
    for name in ("profiles", "active", "logs", "engine", "zapret"):
        harden_path(root / name)


def secure_delete(path: Path) -> None:
    if not path.exists() or not path.is_file():
        return
    size = path.stat().st_size
    try:
        with path.open("r+b") as handle:
            for _ in range(2):
                handle.seek(0)
                remaining = size
                while remaining > 0:
                    chunk = min(remaining, 1024 * 1024)
                    handle.write(os.urandom(chunk))
                    remaining -= chunk
                handle.flush()
                os.fsync(handle.fileno())
            handle.seek(0)
            remaining = size
            while remaining > 0:
                chunk = min(remaining, 1024 * 1024)
                handle.write(b"\x00" * chunk)
                remaining -= chunk
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        pass
    path.unlink(missing_ok=True)


def wipe_active_configs() -> None:
    from .paths import active_dir

    folder = active_dir()
    for item in folder.glob("*.conf"):
        secure_delete(item)


def atomic_write(path: Path, data: bytes) -> None:
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)
    harden_file(path)
