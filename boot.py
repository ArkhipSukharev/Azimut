# -*- coding: utf-8 -*-
import ctypes
import sys
import traceback
from pathlib import Path


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def alert(text: str) -> None:
    ctypes.windll.user32.MessageBoxW(None, text, "Azimut", 0x10)


def write_crash(text: str) -> None:
    folder = app_dir() / "logs"
    folder.mkdir(exist_ok=True)
    (folder / "crash.log").write_text(text, encoding="utf-8")


if not is_admin():
    if getattr(sys, "frozen", False):
        exe = sys.executable
        params = ""
    else:
        exe = sys.executable
        params = f'"{Path(__file__).resolve()}"'
    ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, str(app_dir()), 1)
    sys.exit(0)

try:
    from azimut.app import run

    run()
except Exception:
    text = traceback.format_exc()
    write_crash(text)
    alert("Azimut не открылся.\n\nПричина записана в файл:\n" + str(app_dir() / "logs" / "crash.log"))
    raise
