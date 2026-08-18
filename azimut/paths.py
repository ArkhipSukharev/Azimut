from __future__ import annotations

import sys
from pathlib import Path


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_root() -> Path:
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def data_dir() -> Path:
    path = app_root()
    path.mkdir(parents=True, exist_ok=True)
    return path


def profiles_dir() -> Path:
    path = data_dir() / "profiles"
    path.mkdir(parents=True, exist_ok=True)
    return path


def cache_dir() -> Path:
    path = data_dir() / "cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


def logs_dir() -> Path:
    path = data_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def active_dir() -> Path:
    path = data_dir() / "active"
    path.mkdir(parents=True, exist_ok=True)
    return path


def settings_path() -> Path:
    return data_dir() / "settings.json"


def icon_path() -> Path:
    return app_root() / "assets" / "azimut-app.ico"


def pythonw_path() -> Path:
    if is_frozen():
        return Path(sys.executable).resolve()
    exe = Path(sys.executable)
    candidate = exe.with_name("pythonw.exe")
    return candidate if candidate.exists() else exe


def launch_script() -> Path:
    if is_frozen():
        return Path(sys.executable).resolve()
    return app_root() / "launch.pyw"


def launcher_target() -> Path:
    return pythonw_path().resolve()


def launcher_arguments() -> str:
    if is_frozen():
        return ""
    return f'"{launch_script().resolve()}"'


def desktop_dir() -> Path:
    import ctypes

    buffer = ctypes.create_unicode_buffer(260)
    ctypes.windll.shell32.SHGetFolderPathW(None, 0x10, None, 0, buffer)
    path = Path(buffer.value)
    if path.exists():
        return path
    return Path.home() / "Desktop"


def vault_path() -> Path:
    return data_dir() / "vault.azimut"


def engine_dir() -> Path:
    path = app_root() / "engine"
    path.mkdir(parents=True, exist_ok=True)
    return path
