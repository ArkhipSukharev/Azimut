from __future__ import annotations

from datetime import datetime

from .paths import logs_dir


def log_path():
    return logs_dir() / "azimut.log"


def write_log(message: str) -> None:
    line = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  {message}"
    path = log_path()
    previous = path.read_text(encoding="utf-8") if path.exists() else ""
    lines = (previous + line + "\n").splitlines()[-400:]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def read_log() -> str:
    path = log_path()
    if not path.exists():
        return "Журнал пока пуст."
    return path.read_text(encoding="utf-8")
