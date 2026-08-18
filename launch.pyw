# -*- coding: utf-8 -*-
import ctypes
import os
import subprocess
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CREATE_NO_WINDOW = 0x08000000


def alert(text: str, title: str = "Azimut") -> None:
    ctypes.windll.user32.MessageBoxW(None, text, title, 0x10)


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def write_crash(text: str) -> None:
    folder = ROOT / "logs"
    folder.mkdir(exist_ok=True)
    (folder / "crash.log").write_text(text, encoding="utf-8")


def is_stub(path: Path) -> bool:
    try:
        if not path.is_file():
            return True
        text = str(path).lower()
        if "windowsapps" in text:
            return True
        return path.stat().st_size < 50000
    except OSError:
        return True


def has_packages(python_exe: Path) -> bool:
    if is_stub(python_exe):
        return False
    try:
        proc = subprocess.run(
            [
                str(python_exe),
                "-c",
                "import customtkinter, cryptography, PIL, pystray",
            ],
            capture_output=True,
            creationflags=CREATE_NO_WINDOW,
        )
        return proc.returncode == 0
    except OSError:
        return False


def current_has_packages() -> bool:
    if is_stub(Path(sys.executable)):
        return False
    try:
        import cryptography  # noqa: F401
        import customtkinter  # noqa: F401
        import PIL  # noqa: F401
        import pystray  # noqa: F401

        return True
    except ImportError:
        return False


def python_candidates() -> list[Path]:
    found: list[Path] = []
    seen: set[str] = set()

    def add(path: Path | None) -> None:
        if path is None:
            return
        path = path.resolve()
        key = str(path).lower()
        if key in seen:
            return
        seen.add(key)
        found.append(path)

    current = Path(sys.executable)
    add(current)
    add(current.with_name("python.exe"))
    add(current.with_name("pythonw.exe"))

    local = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Python"
    if local.is_dir():
        for item in sorted(local.glob("Python*/python.exe"), reverse=True):
            add(item)

    for name in ("py", "py.exe"):
        try:
            proc = subprocess.run(
                [name, "-3", "-c", "import sys; print(sys.executable)"],
                capture_output=True,
                text=True,
                creationflags=CREATE_NO_WINDOW,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                add(Path(proc.stdout.strip()))
        except OSError:
            pass

    return found


def find_python() -> Path | None:
    if current_has_packages():
        return Path(sys.executable)
    for candidate in python_candidates():
        if has_packages(candidate):
            return candidate
    return None


def pythonw_for(python_exe: Path) -> Path:
    candidate = python_exe.with_name("pythonw.exe")
    return candidate if candidate.exists() else python_exe


def relaunch(python_exe: Path, as_admin: bool) -> None:
    script = str(Path(__file__).resolve())
    exe = str(pythonw_for(python_exe))
    if as_admin:
        ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, f'"{script}"', str(ROOT), 1)
        return
    os.execv(exe, [exe, script])


python = find_python()
if python is None:
    alert(
        "Azimut не нашёл Python с нужными библиотеками.\n\n"
        "Установите Python 3.11 или новее с python.org, затем в папке программы выполните:\n\n"
        "python install.py\n\n"
        "или:\n\n"
        "python -m pip install -r requirements.txt"
    )
    sys.exit(1)

if Path(sys.executable).resolve() != python.resolve() and Path(sys.executable).resolve() != pythonw_for(python).resolve():
    relaunch(python, as_admin=not is_admin())
    sys.exit(0)

if not is_admin():
    relaunch(python, as_admin=True)
    sys.exit(0)

try:
    from azimut.app import run

    run()
except Exception:
    text = traceback.format_exc()
    write_crash(text)
    alert("Azimut не открылся.\n\nПричина записана в файл:\n" + str(ROOT / "logs" / "crash.log"))
    raise
