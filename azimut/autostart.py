from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

from .paths import app_root, desktop_dir, icon_path, is_frozen, launcher_arguments, launcher_target

TASK_NAME = "Azimut"


def launcher_command() -> str:
    target = launcher_target()
    args = launcher_arguments()
    if args:
        return f'"{target}" {args}'
    return f'"{target}"'


def _hidden(args: list[str]) -> SimpleNamespace:
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    proc = subprocess.run(
        args,
        capture_output=True,
        startupinfo=startup,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    return SimpleNamespace(returncode=proc.returncode, stdout=proc.stdout or b"", stderr=proc.stderr or b"")


def _decode(raw: bytes) -> str:
    for encoding in ("cp866", "cp1251", "utf-8"):
        try:
            return raw.decode(encoding)
        except Exception:
            continue
    return raw.decode("utf-8", errors="replace")


def _clear_run_key() -> None:
    try:
        import winreg

        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_SET_VALUE,
        )
        try:
            winreg.DeleteValue(key, "Azimut")
        except FileNotFoundError:
            pass
        finally:
            winreg.CloseKey(key)
    except OSError:
        pass


def set_autostart(enabled: bool) -> None:
    _clear_run_key()
    if enabled:
        proc = _hidden(
            [
                "schtasks",
                "/Create",
                "/TN",
                TASK_NAME,
                "/TR",
                launcher_command(),
                "/SC",
                "ONLOGON",
                "/RL",
                "HIGHEST",
                "/F",
            ]
        )
        if proc.returncode != 0:
            details = (_decode(proc.stderr) or _decode(proc.stdout)).strip()
            raise RuntimeError(
                "Не удалось включить автозапуск через планировщик заданий Windows. "
                + (details or "Проверьте, что программа запущена с правами администратора.")
            )
        return
    _hidden(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"])


def _ps_quote(value: Path | str) -> str:
    return str(value).replace("'", "''")


def write_shortcut(path: Path) -> Path:
    from .icon import create_icon

    path = Path(path)
    icon = icon_path()
    if not icon.exists():
        create_icon(icon)
    target = launcher_target()
    args = launcher_arguments()
    work = app_root().resolve()
    command = (
        f"$link = (New-Object -ComObject WScript.Shell).CreateShortcut('{_ps_quote(path)}'); "
        f"$link.TargetPath = '{_ps_quote(target)}'; "
        f"$link.Arguments = '{_ps_quote(args)}'; "
        f"$link.WorkingDirectory = '{_ps_quote(work)}'; "
        f"$link.IconLocation = '{_ps_quote(icon)}'; "
        f"$link.WindowStyle = 1; "
        f"$link.Description = 'Azimut'; "
        f"$link.Save()"
    )
    proc = _hidden(["powershell", "-NoProfile", "-Command", command])
    if proc.returncode != 0 or not path.exists():
        details = _decode(proc.stderr or proc.stdout)
        raise RuntimeError("Не удалось создать ярлык Azimut. " + details[-400:])
    return path


def create_app_shortcut() -> Path:
    if is_frozen():
        return launcher_target()
    return write_shortcut(app_root() / "Azimut.lnk")


def create_desktop_shortcut() -> Path:
    return write_shortcut(desktop_dir() / "Azimut.lnk")
